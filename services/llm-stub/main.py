"""
Stub LLM service that mimics the OpenAI chat completions API for local E2E testing.
Returns a deterministic answer derived from the system prompt context.
"""
import re

from fastapi import FastAPI
from pydantic import BaseModel

_STOPWORDS = {
    "what", "the", "is", "are", "for", "and", "or", "to", "in", "of", "on",
    "at", "do", "does", "our", "can", "will", "have", "has", "had", "was",
    "were", "be", "been", "that", "this", "with", "from", "how", "why",
    "when", "where", "who", "which", "a", "an",
}


def _relevant(user_content: str, system_content: str) -> bool:
    """Return True when the query has enough lexical grounding in the document content."""
    def meaningful(text: str) -> set:
        return {w.lower() for w in re.findall(r'\b\w+\b', text)
                if len(w) > 3 and w.lower() not in _STOPWORDS}
    qw = meaningful(user_content)
    if not qw:
        return True

    # If the query mentions a specific year or identifier absent from context,
    # treat it as unsupported even if generic words like "policy" overlap.
    query_numbers = set(re.findall(r'\b\d{4,}\b', user_content))
    context_numbers = set(re.findall(r'\b\d{4,}\b', system_content))
    if query_numbers and not query_numbers <= context_numbers:
        return False

    return len(qw & meaningful(system_content)) / len(qw) >= 0.5


def _grounded_answer(system_content: str) -> str:
    """Return a short answer derived from the first document excerpt."""
    match = re.search(r"\[Document 1\]\n(?P<content>.*?)(?:\nSource:|$)", system_content, re.DOTALL)
    if not match:
        return "Insufficient data"
    content = " ".join(match.group("content").split())
    words = content.split()
    return " ".join(words[:40])

app = FastAPI(title="llm-stub")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "stub"
    messages: list[Message]
    max_tokens: int = 1024
    temperature: float = 0.0


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    system_content = next((m.content for m in req.messages if m.role == "system"), "")
    user_content = next((m.content for m in req.messages if m.role == "user"), "")

    # Return "Insufficient data" if context has no document excerpts or query is irrelevant
    has_documents = "<documents>" in system_content and "[Document" in system_content
    if not has_documents or not _relevant(user_content, system_content):
        answer = "Insufficient data"
    else:
        # Use only the system prompt documents — never echo the raw user query
        # to avoid leaking any terms like "acl_tokens" back to the test
        answer = _grounded_answer(system_content)

    return {
        "id": "stub-response",
        "object": "chat.completion",
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
