import pytest
from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from internal.orchestrator.merger import dedup_and_cap, normalize_scores


def _c(chunk_id: str, score: float, index: str = "public_index") -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id, doc_id="d1", content="text",
        citation_hint=CitationHint(path="p", page_number=None, section=None),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=0,
        retrieval_score=score, source_index=index,
    )


def test_orc_02_dedup_shared_chunks():
    c1 = _c("shared", 0.9, "public_index")
    c2 = _c("shared", 0.7, "internal_index")
    c3 = _c("unique", 0.5, "public_index")
    result = dedup_and_cap([c1, c2, c3], max_total=200)
    chunk_ids = [r.chunk_id for r in result]
    assert chunk_ids.count("shared") == 1
    assert "unique" in chunk_ids
    assert result[0].chunk_id == "shared"  # highest score wins


def test_orc_05_cap_at_max():
    candidates = [_c(f"c{i}", float(i)) for i in range(300)]
    result = dedup_and_cap(candidates, max_total=200)
    assert len(result) == 200


def test_normalize_single_index():
    candidates = {
        "public_index": [_c("c1", 10.0), _c("c2", 5.0), _c("c3", 0.0)]
    }
    result = normalize_scores(candidates)
    scores = {c.chunk_id: c.retrieval_score for c in result}
    assert scores["c1"] == 1.0
    assert scores["c3"] == 0.0
    assert scores["c2"] == pytest.approx(0.5)


def test_orc_01_single_index_50_hits():
    """ORC-01: Single index, 50 unique hits → 50 RetrievalCandidates returned."""
    candidates = [_c(f"c{i}", float(i)) for i in range(50)]
    result = dedup_and_cap(candidates, max_total=200)
    assert len(result) == 50


def test_orc_08_zero_hits_returns_empty():
    """ORC-08: Zero hits across all indexes → empty candidate set; no error."""
    result = dedup_and_cap([], max_total=200)
    assert result == []


def test_orc_09_no_allowed_groups_in_candidates():
    """ORC-09: allowed_groups not a field on RetrievalCandidate (document-level ACL not exposed)."""
    c = _c("c1", 0.9)
    assert "allowed_groups" not in c.model_dump()
