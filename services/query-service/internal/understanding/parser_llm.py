import json
import logging
import os

logger = logging.getLogger(__name__)

LLM_PARSER_TIMEOUT_MS = int(os.environ.get("LLM_PARSER_TIMEOUT_MS", "2000"))
LLM_PARSER_MODEL = os.environ.get("LLM_PARSER_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = """You are a query parser. Extract structured fields from the user query.
Return ONLY a JSON object with these fields:
  keywords: array of key terms (max 5)
  topic: one of [finance, hr, legal, engineering, null]
  doc_type: one of [regulation, policy, report, memo, null]
  time_range: {"year": int} or null
  intent: one of [factual_lookup, comparison, policy_lookup, summary]"""


async def parse_llm(query: str, llm_client) -> dict | None:
    """Attempt LLM-based query parsing. Returns None on failure (caller falls back to rules)."""
    try:
        response = await llm_client.complete(
            system=_SYSTEM_PROMPT,
            user=query,
            model=LLM_PARSER_MODEL,
            max_tokens=200,
            timeout=LLM_PARSER_TIMEOUT_MS / 1000,
        )
        return json.loads(response)
    except Exception as exc:
        logger.warning("LLM parser failed; falling back to rules", extra={"error": str(exc)})
        return None
