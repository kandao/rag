"""QU-10: Query Understanding failure → raw query passed through; ACL not relaxed."""
import pytest

from rag_common.models.user_context import UserContext

import internal.understanding.understanding as und


def _user(clearance: int = 1) -> UserContext:
    return UserContext(
        user_id="u1",
        effective_groups=["group:eng"],
        effective_clearance=clearance,
        acl_tokens=["group:eng", f"level:{clearance}"],
        acl_key="abc",
        token_schema_version="v1",
        acl_version="v1",
        claims_hash="def",
        derived_at="2024-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_qu_10_rules_parser_failure_passes_raw_query(monkeypatch):
    """QU-10: even if rules parser raises, return QueryContext with raw_query intact;
    user_context (and therefore ACL) is never mutated."""
    def boom(_q):
        raise RuntimeError("rules parser exploded")

    monkeypatch.setattr(und, "parse", boom)

    ctx_before = _user(1)
    snapshot_tokens = list(ctx_before.acl_tokens)
    snapshot_clearance = ctx_before.effective_clearance

    raw = "What are the 2024 medical device regulation updates?"
    result = await und.parse_query(
        raw_query=raw,
        user_context=ctx_before,
        request_id="r1",
    )

    assert result.raw_query == raw
    assert result.intent == "unknown"
    assert result.topic is None
    assert result.keywords == []
    assert result.doc_type is None
    assert result.time_range is None

    # ACL invariant: user_context untouched
    assert ctx_before.acl_tokens == snapshot_tokens
    assert ctx_before.effective_clearance == snapshot_clearance
