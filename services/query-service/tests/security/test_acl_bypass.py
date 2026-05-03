"""Security tests: prove that no ES query can be emitted without ACL filters.

These tests directly construct query DSLs through normal builder paths and confirm
assert_acl_present() would catch any bypass. No mock bypasses the validator call.
"""
import pytest

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext
from internal.querybuilder.hybrid_query import build_hybrid_query
from internal.querybuilder.bm25_only_query import build_bm25_only_query
from internal.querybuilder.query_validator import assert_acl_present


def _ctx(tokens=None) -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=1,
        acl_tokens=tokens if tokens is not None else ["group:eng", "level:1"], acl_key="k",
        token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


def _qctx() -> QueryContext:
    return QueryContext(
        request_id="r1", raw_query="test", keywords=[], topic=None,
        doc_type=None, time_range=None, intent="factual_lookup",
        risk_signal="none", expanded_queries=[],
    )


def test_hybrid_query_always_has_acl():
    q = build_hybrid_query(_ctx(), _qctx(), [0.1] * 1536)
    assert_acl_present(q)  # must not raise


def test_bm25_query_always_has_acl():
    q = build_bm25_only_query(_ctx(), _qctx())
    assert_acl_present(q)  # must not raise


def test_empty_tokens_still_has_filter():
    ctx = _ctx(tokens=[])
    q = build_bm25_only_query(ctx, _qctx())
    assert_acl_present(q)
    terms_filter = next(f for f in q["query"]["bool"]["filter"] if "terms" in f)
    assert terms_filter["terms"]["acl_tokens"] == []


def test_mutated_query_without_acl_fails_validation():
    q = build_bm25_only_query(_ctx(), _qctx())
    q["query"]["bool"]["filter"] = []  # simulate bypass attempt
    with pytest.raises(AssertionError):
        assert_acl_present(q)
