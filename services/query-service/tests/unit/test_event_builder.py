import pytest
from rag_common.models.retrieval import RetrievalCandidate, RankedCandidate, CitationHint
from rag_common.models.user_context import UserContext
from internal.audit.event_builder import build_query_event, should_gate_on_audit


def _ctx(clearance: int) -> UserContext:
    return UserContext(
        user_id="u1",
        effective_groups=[],
        effective_clearance=clearance,
        acl_tokens=["level:" + str(clearance)],
        acl_key="key",
        token_schema_version="v1",
        acl_version="v1",
        claims_hash="hash",
        derived_at="2024-01-01T00:00:00+00:00",
    )


def _candidate(chunk_id: str, sensitivity: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id, doc_id="d1", content="text",
        citation_hint=CitationHint(path="p", page_number=None, section=None),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=sensitivity,
        retrieval_score=0.9, source_index="public_index",
    )


def test_build_event_fields():
    ctx = _ctx(1)
    event = build_query_event(
        request_id="r1", user_context=ctx, target_indexes=["public_index"],
        retrieved=[_candidate("c1", 0)], ranked=[RankedCandidate(chunk_id="c1", rerank_score=0.9)],
        model_path="cloud_l1", authorization_decision="allowed",
        query_risk_signal="none", answer_returned=True, latency_ms=100,
    )
    assert event.user_id == "u1"
    assert event.retrieved_chunk_ids == ["c1"]
    assert event.sensitivity_levels_accessed == [0]
    assert "acl_tokens" not in event.model_dump()


def test_aud_09_l2_user_gate_true():
    assert should_gate_on_audit(_ctx(2)) is True


def test_aud_10_l1_user_gate_false():
    assert should_gate_on_audit(_ctx(1)) is False


def test_aud_06_guard_block_event_abbreviated():
    """AUD-06: Guard block → authorization_decision=denied, no chunk IDs, answer not returned."""
    ctx = _ctx(1)
    event = build_query_event(
        request_id="r1", user_context=ctx, target_indexes=[],
        retrieved=[], ranked=[],
        model_path="none", authorization_decision="denied",
        query_risk_signal="ERR_GUARD_INJECTION_DETECTED", answer_returned=False, latency_ms=5,
    )
    assert event.authorization_decision == "denied"
    assert event.retrieved_chunk_ids == []
    assert event.ranked_chunk_ids == []
    assert event.answer_returned is False


def test_aud_06_truncate_query_fragment():
    """AUD-06: production helper truncates query fragment at 100 chars."""
    from internal.audit.event_builder import (
        QUERY_FRAGMENT_MAX_LEN,
        truncate_query_fragment,
    )

    assert QUERY_FRAGMENT_MAX_LEN == 100
    assert truncate_query_fragment("A" * 150) == "A" * 100
    assert truncate_query_fragment("A" * 100) == "A" * 100
    assert truncate_query_fragment("short query") == "short query"


def test_aud_08_acl_tokens_absent_from_event():
    """AUD-08: acl_tokens must not appear in audit event payload."""
    ctx = _ctx(2)
    event = build_query_event(
        request_id="r2", user_context=ctx, target_indexes=["confidential_index"],
        retrieved=[_candidate("c1", 2)], ranked=[RankedCandidate(chunk_id="c1", rerank_score=0.8)],
        model_path="private_l2", authorization_decision="allowed",
        query_risk_signal="none", answer_returned=True, latency_ms=200,
    )
    assert "acl_tokens" not in event.model_dump()
