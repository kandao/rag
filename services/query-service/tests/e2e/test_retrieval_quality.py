"""
HLD-RET-01 – HLD-RET-07: Retrieval Quality Gate (pre-launch E2E)

Requires: real Elasticsearch + embedding service + seeded ground-truth chunks.
Run with: pytest -m e2e tests/e2e/test_retrieval_quality.py
"""
import pytest

from .conftest import GROUND_TRUTH, query_via_gateway, get_chunk_ids, TOKENS

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recall_at_k(results: list[str], expected: str, k: int) -> int:
    """Return 1 if expected chunk_id is in the top-k results, else 0."""
    return 1 if expected in results[:k] else 0


def _reciprocal_rank(results: list[str], expected: str) -> float:
    try:
        rank = results.index(expected) + 1
        return 1.0 / rank
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# HLD-RET-01: Recall@5 ≥ 0.70
# ---------------------------------------------------------------------------

def test_hld_ret_01_recall_at_5(http):
    hits = 0
    for gt in GROUND_TRUTH:
        resp = query_via_gateway(http, "l1", gt["query"])
        assert resp.status_code == 200
        chunk_ids = get_chunk_ids(resp.json())
        hits += _recall_at_k(chunk_ids, gt["chunk_id"], k=5)

    recall = hits / len(GROUND_TRUTH)
    assert recall >= 0.70, f"HLD-RET-01 Recall@5={recall:.2f} < 0.70"


# ---------------------------------------------------------------------------
# HLD-RET-02: Recall@10 ≥ 0.80
# ---------------------------------------------------------------------------

def test_hld_ret_02_recall_at_10(http):
    hits = 0
    for gt in GROUND_TRUTH:
        resp = query_via_gateway(http, "l1", gt["query"])
        assert resp.status_code == 200
        chunk_ids = get_chunk_ids(resp.json())
        hits += _recall_at_k(chunk_ids, gt["chunk_id"], k=10)

    recall = hits / len(GROUND_TRUTH)
    assert recall >= 0.80, f"HLD-RET-02 Recall@10={recall:.2f} < 0.80"


# ---------------------------------------------------------------------------
# HLD-RET-03: MRR ≥ 0.60
# ---------------------------------------------------------------------------

def test_hld_ret_03_mrr(http):
    rr_sum = 0.0
    for gt in GROUND_TRUTH:
        resp = query_via_gateway(http, "l1", gt["query"])
        assert resp.status_code == 200
        chunk_ids = get_chunk_ids(resp.json())
        rr_sum += _reciprocal_rank(chunk_ids, gt["chunk_id"])

    mrr = rr_sum / len(GROUND_TRUTH)
    assert mrr >= 0.60, f"HLD-RET-03 MRR={mrr:.2f} < 0.60"


# ---------------------------------------------------------------------------
# HLD-RET-04: BM25 exact term match — queries with proper nouns, numbers, dates
# ---------------------------------------------------------------------------

BM25_QUERIES = [
    ("engineering guidelines 2024", "eng-guide-2024-001"),
    ("hr policy 2024", "hr-policy-2024-001"),
    ("product overview Q1", "product-overview-001"),
]


@pytest.mark.parametrize("query,expected_chunk_id", BM25_QUERIES)
def test_hld_ret_04_bm25_exact_term_match(http, query, expected_chunk_id):
    resp = query_via_gateway(http, "l1", query)
    assert resp.status_code == 200
    chunk_ids = get_chunk_ids(resp.json())
    assert expected_chunk_id in chunk_ids[:10], (
        f"HLD-RET-04: expected chunk '{expected_chunk_id}' not in Top 10 for query '{query}'"
    )


# ---------------------------------------------------------------------------
# HLD-RET-05: Semantic match without keyword hit — queries expressed as synonyms
# ---------------------------------------------------------------------------

SEMANTIC_QUERIES = [
    ("technical development standards for staff", "eng-guide-2024-001"),
    ("rules for joining the company", "hr-policy-2024-001"),
    ("what does our product do", "product-overview-001"),
]


@pytest.mark.parametrize("query,expected_chunk_id", SEMANTIC_QUERIES)
def test_hld_ret_05_semantic_match(http, query, expected_chunk_id):
    resp = query_via_gateway(http, "l1", query)
    assert resp.status_code == 200
    chunk_ids = get_chunk_ids(resp.json())
    assert expected_chunk_id in chunk_ids[:10], (
        f"HLD-RET-05: expected chunk '{expected_chunk_id}' not in Top 10 for semantic query '{query}'"
    )


# ---------------------------------------------------------------------------
# HLD-RET-06: Multi-index query across tier merge — L1 user sees L0 + L1 results
# ---------------------------------------------------------------------------

def test_hld_ret_06_multi_index_merge(http):
    resp = query_via_gateway(http, "l1", "engineering guidelines and product overview")
    assert resp.status_code == 200
    citations = resp.json().get("citations", [])

    indexes_seen = {c.get("source_index") for c in citations if "source_index" in c}
    # L1 user should see results from both public (L0) and internal (L1) indexes
    assert "public_index" in indexes_seen or "internal_index" in indexes_seen, (
        "HLD-RET-06: Expected results from multiple indexes, got: " + str(indexes_seen)
    )
    assert len(indexes_seen) >= 2, (
        f"HLD-RET-06: Expected results from ≥2 indexes, only got: {indexes_seen}"
    )


# ---------------------------------------------------------------------------
# HLD-RET-07: ACL filter narrows results — L1 user must not see L2 chunks
# ---------------------------------------------------------------------------

def test_hld_ret_07_acl_filter_narrows_results(http):
    # Query for content that exists at L2 sensitivity (confidential)
    resp = query_via_gateway(http, "l1", "legal contracts confidential information")
    assert resp.status_code == 200
    citations = resp.json().get("citations", [])

    for citation in citations:
        sensitivity = citation.get("sensitivity_level", 0)
        assert sensitivity <= 1, (
            f"HLD-RET-07: L1 user received chunk with sensitivity_level={sensitivity} "
            f"(chunk_id={citation.get('chunk_id')})"
        )
