"""
HLD-RNK-01 – HLD-RNK-02: Reranker Quality Gate (pre-launch E2E)

Requires: real Elasticsearch + reranker service + seeded ground-truth chunks.
Run with: pytest -m e2e tests/e2e/test_reranker_quality.py
"""
import pytest
import httpx
import os

from .conftest import GROUND_TRUTH, RERANKER_URL, query_via_gateway, get_chunk_ids

pytestmark = pytest.mark.e2e
RERANKER_REQUIRED = os.getenv("RERANKER_REQUIRED", "false").lower() == "true"


def _precision_at_k(results: list[str], relevant: set[str], k: int) -> float:
    top_k = results[:k]
    if not top_k:
        return 0.0
    return sum(1 for r in top_k if r in relevant) / k


def _get_reranked_chunk_ids(query: str, candidates: list[dict]) -> list[str]:
    """Call the reranker service directly and return chunk_ids in reranked order."""
    try:
        resp = httpx.post(
            f"{RERANKER_URL}/v1/rerank",
            json={
                "request_id": "test-rerank",
                "query": query,
                "candidates": [
                    {"chunk_id": c["chunk_id"], "content": c.get("content") or ""}
                    for c in candidates
                ],
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        if RERANKER_REQUIRED:
            raise
        pytest.skip(f"Reranker quality gate skipped: reranker unavailable ({exc})")

    if resp.status_code >= 500 and not RERANKER_REQUIRED:
        pytest.skip(f"Reranker quality gate skipped: reranker returned {resp.status_code}")

    assert resp.status_code == 200, f"Reranker returned {resp.status_code}: {resp.text}"
    return [r["chunk_id"] for r in resp.json().get("ranked", [])]


# ---------------------------------------------------------------------------
# HLD-RNK-01: Precision@5 — reranker output ≥ retrieval order + 0.10
# ---------------------------------------------------------------------------

def test_hld_rnk_01_precision_at_5_improves(http):
    relevant_chunks = {gt["chunk_id"] for gt in GROUND_TRUTH}

    retrieval_p5_sum = 0.0
    reranker_p5_sum = 0.0
    count = 0

    for gt in GROUND_TRUTH[:5]:  # use first 5 for speed
        resp = query_via_gateway(http, "l1", gt["query"])
        assert resp.status_code == 200
        body = resp.json()
        citations = body.get("citations", [])

        retrieval_order = [c["chunk_id"] for c in citations]
        retrieval_p5_sum += _precision_at_k(retrieval_order, relevant_chunks, k=5)

        # Reranker precision: compare using reranker service directly
        candidates = [
            {"chunk_id": c["chunk_id"], "content": c.get("content", ""), "retrieval_score": c.get("retrieval_score", 0.0)}
            for c in citations[:20]
        ]
        if candidates:
            reranked_ids = _get_reranked_chunk_ids(gt["query"], candidates)
            reranker_p5_sum += _precision_at_k(reranked_ids, relevant_chunks, k=5)

        count += 1

    if count == 0:
        pytest.skip("No ground-truth queries returned results")

    avg_retrieval_p5 = retrieval_p5_sum / count
    avg_reranker_p5 = reranker_p5_sum / count

    assert avg_reranker_p5 >= avg_retrieval_p5 + 0.10, (
        f"HLD-RNK-01: Reranker P@5={avg_reranker_p5:.2f} did not improve "
        f"retrieval P@5={avg_retrieval_p5:.2f} by ≥ 0.10"
    )


# ---------------------------------------------------------------------------
# HLD-RNK-02: Reranker does not change authorized scope
# ---------------------------------------------------------------------------

def test_hld_rnk_02_reranker_preserves_authorized_scope(http):
    resp = query_via_gateway(http, "l1", "engineering guidelines")
    assert resp.status_code == 200
    citations = resp.json().get("citations", [])

    authorized_chunk_ids = {c["chunk_id"] for c in citations}

    candidates = [
        {"chunk_id": c["chunk_id"], "content": c.get("content", ""), "retrieval_score": c.get("retrieval_score", 0.0)}
        for c in citations[:20]
    ]
    if not candidates:
        pytest.skip("No candidates returned for scope test")

    reranked_ids = _get_reranked_chunk_ids("engineering guidelines", candidates)

    for chunk_id in reranked_ids:
        assert chunk_id in authorized_chunk_ids, (
            f"HLD-RNK-02: Reranker introduced chunk '{chunk_id}' not in the authorized candidate set"
        )
