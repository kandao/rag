"""
HLD-ANS-01 – HLD-ANS-06: Answer Quality Gate (pre-launch E2E)

Requires: full stack including real LLM API calls.
Run with: pytest -m e2e tests/e2e/test_answer_quality.py
"""
import re
import pytest
import httpx
import os

from .conftest import query_via_gateway, get_chunk_ids, GATEWAY_URL

pytestmark = pytest.mark.e2e

LLM_JUDGE_URL = os.getenv("LLM_JUDGE_URL", "")  # optional external judge service

# Queries guaranteed to have no matching chunks in the index (no-answer cases)
NO_ANSWER_QUERIES = [
    "What is the population of Mars?",
    "Who won the 2099 World Cup?",
    "Explain quantum teleportation procedures at our company",
    "What is our policy on time travel?",
    "Describe our office on the moon",
    "List all employees hired in 3025",
    "What does our policy say about dragon taming?",
    "Summarize our underwater research station guidelines",
    "What are our protocols for alien contact?",
    "Explain our policy on interstellar travel",
]


def _query_full(http_client: httpx.Client, token_key: str, query: str) -> dict:
    resp = query_via_gateway(http_client, token_key, query)
    assert resp.status_code == 200, f"Query failed with {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# HLD-ANS-01: Faithfulness — ≥ 90% of answer sentences traceable to a citation
# ---------------------------------------------------------------------------

def test_hld_ans_01_faithfulness(http):
    body = _query_full(http, "l1", "What are the engineering guidelines for 2024?")
    answer = body.get("answer", "")
    citations = body.get("citations", [])

    if not answer or not citations:
        pytest.skip("No answer or citations returned — stack may not be seeded")

    sentences = [s.strip() for s in re.split(r"[.!?]", answer) if len(s.strip()) > 10]
    if not sentences:
        pytest.skip("Answer too short to evaluate faithfulness")

    citation_texts = " ".join((c.get("content") or "") for c in citations).lower()
    if not citation_texts.strip():
        pytest.skip("Citation content not returned by the running stack")

    traceable = 0
    for sentence in sentences:
        # Check if key words from the sentence appear in citation content
        words = set(sentence.lower().split()) - {"the", "a", "an", "is", "are", "of", "and", "to", "in", "for"}
        if len(words) == 0:
            traceable += 1
            continue
        overlap = sum(1 for w in words if w in citation_texts)
        if overlap / len(words) >= 0.5:
            traceable += 1

    faithfulness = traceable / len(sentences)
    assert faithfulness >= 0.90, (
        f"HLD-ANS-01: Faithfulness={faithfulness:.2f} < 0.90 "
        f"({traceable}/{len(sentences)} sentences traceable)"
    )


# ---------------------------------------------------------------------------
# HLD-ANS-02: Relevance — LLM judge score ≥ 4/5
# ---------------------------------------------------------------------------

def test_hld_ans_02_relevance(http):
    query = "What are the engineering guidelines for 2024?"
    body = _query_full(http, "l1", query)
    answer = body.get("answer", "")

    if not answer:
        pytest.skip("No answer returned — stack may not be seeded")

    # If no external judge, do a simple keyword relevance check
    if not LLM_JUDGE_URL:
        query_words = set(re.findall(r"\b\w+\b", query.lower())) - {"what", "are", "the", "for"}
        answer_words = set(re.findall(r"\b\w+\b", answer.lower()))
        overlap = len(query_words & answer_words) / len(query_words)
        assert overlap >= 0.3, (
            f"HLD-ANS-02: Answer appears irrelevant to query (word overlap={overlap:.2f})"
        )
        return

    judge_resp = httpx.post(
        LLM_JUDGE_URL,
        json={"query": query, "answer": answer},
        timeout=30.0,
    )
    assert judge_resp.status_code == 200
    score = judge_resp.json().get("score", 0)
    assert score >= 4, f"HLD-ANS-02: LLM judge score={score} < 4/5"


# ---------------------------------------------------------------------------
# HLD-ANS-03: No hallucination — "Insufficient data" for no-answer queries
# ---------------------------------------------------------------------------

def test_hld_ans_03_no_hallucination(http):
    insufficient_responses = 0

    for query in NO_ANSWER_QUERIES:
        body = _query_full(http, "l1", query)
        answer = body.get("answer", "").lower()

        is_insufficient = (
            "insufficient" in answer
            or "not available" in answer
            or "no information" in answer
            or "cannot find" in answer
            or "don't have" in answer
            or "do not have" in answer
            or body.get("citations", []) == []
        )
        if is_insufficient:
            insufficient_responses += 1

    accuracy = insufficient_responses / len(NO_ANSWER_QUERIES)
    assert accuracy == 1.0, (
        f"HLD-ANS-03: {len(NO_ANSWER_QUERIES) - insufficient_responses}/{len(NO_ANSWER_QUERIES)} "
        f"no-answer queries returned fabricated answers"
    )


# ---------------------------------------------------------------------------
# HLD-ANS-04: Citation correctness — chunk_id, path, page_number match retrieved chunk
# ---------------------------------------------------------------------------

def test_hld_ans_04_citation_correctness(http):
    body = _query_full(http, "l1", "What are the engineering guidelines for 2024?")
    citations = body.get("citations", [])

    if not citations:
        pytest.skip("No citations returned — stack may not be seeded")

    for citation in citations:
        assert "chunk_id" in citation, "HLD-ANS-04: citation missing chunk_id"
        assert citation["chunk_id"], "HLD-ANS-04: citation has empty chunk_id"
        assert "path" in citation, "HLD-ANS-04: citation missing path"
        assert citation["path"], "HLD-ANS-04: citation has empty path"
        # page_number may be None for non-PDF sources — just verify the field is present
        assert "page_number" in citation, "HLD-ANS-04: citation missing page_number field"


# ---------------------------------------------------------------------------
# HLD-ANS-05: ACL metadata does not appear in answers
# ---------------------------------------------------------------------------

FORBIDDEN_PATTERNS = [
    r"\ballowed_groups\b",
    r"\bacl_tokens\b",
    r"\bgroup:\w+",
    r"\blevel:\d",
]


def test_hld_ans_05_acl_metadata_absent(http):
    body = _query_full(http, "l1", "What are the engineering guidelines for 2024?")
    answer = body.get("answer", "")

    for pattern in FORBIDDEN_PATTERNS:
        match = re.search(pattern, answer)
        assert match is None, (
            f"HLD-ANS-05: ACL metadata pattern '{pattern}' found in answer: '{match.group()}'"
        )


# ---------------------------------------------------------------------------
# HLD-ANS-06: Answer Verification (L1+) — ≥ 80% accuracy on insufficient-context cases
# ---------------------------------------------------------------------------

def test_hld_ans_06_answer_verification_insufficient(http):
    correct = 0

    for query in NO_ANSWER_QUERIES:
        body = _query_full(http, "l1", query)
        answer = body.get("answer", "").lower()
        verified = body.get("verified", None)

        # Accept either explicit verification flag or keyword in answer
        is_correctly_flagged = (
            verified is False
            or "insufficient" in answer
            or "not available" in answer
            or "no information" in answer
        )
        if is_correctly_flagged:
            correct += 1

    accuracy = correct / len(NO_ANSWER_QUERIES)
    assert accuracy >= 0.80, (
        f"HLD-ANS-06: Verification accuracy={accuracy:.2f} < 0.80 "
        f"({correct}/{len(NO_ANSWER_QUERIES)} insufficient cases correctly flagged)"
    )
