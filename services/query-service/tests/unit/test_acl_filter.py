from rag_common.models.user_context import UserContext
from internal.querybuilder.acl_filter import build_acl_filters


def _ctx(tokens: list[str], clearance: int) -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=clearance,
        acl_tokens=tokens, acl_key="k", token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


def test_builds_two_filters():
    filters = build_acl_filters(_ctx(["group:eng", "level:1"], 1))
    assert len(filters) == 2
    assert any("terms" in f and "acl_tokens" in f["terms"] for f in filters)
    assert any("range" in f and "sensitivity_level" in f["range"] for f in filters)


def test_sqb_03_empty_tokens_still_builds():
    filters = build_acl_filters(_ctx([], 0))
    terms = next(f for f in filters if "terms" in f)
    assert terms["terms"]["acl_tokens"] == []
