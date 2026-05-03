import pytest
from unittest.mock import AsyncMock, MagicMock
from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext
from internal.querybuilder.hybrid_query import build_hybrid_query
from internal.querybuilder.bm25_only_query import build_bm25_only_query
from internal.querybuilder.embedding_client import get_query_embedding


def _ctx() -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=1,
        acl_tokens=["group:eng", "level:1"], acl_key="k",
        token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


def _qctx(topic=None) -> QueryContext:
    return QueryContext(
        request_id="r1", raw_query="test query", keywords=[], topic=topic,
        doc_type=None, time_range=None, intent="factual_lookup",
        risk_signal="none", expanded_queries=[],
    )


def test_sqb_01_hybrid_has_knn_block():
    q = build_hybrid_query(_ctx(), _qctx(), [0.1] * 1536)
    assert "knn" in q
    assert "query" in q


def test_sqb_01_acl_in_both_branches():
    ctx = _ctx()
    q = build_hybrid_query(ctx, _qctx(), [0.1] * 1536)
    bool_filters = q["query"]["bool"]["filter"]
    knn_filters = q["knn"]["filter"]["bool"]["filter"]

    acl_bool = next(f for f in bool_filters if "acl_tokens" in f.get("terms", {}))
    assert acl_bool["terms"]["acl_tokens"] == ctx.acl_tokens

    acl_knn = next(f for f in knn_filters if "acl_tokens" in f.get("terms", {}))
    assert acl_knn["terms"]["acl_tokens"] == ctx.acl_tokens

    assert any("sensitivity_level" in f.get("range", {}) for f in bool_filters)
    assert any("sensitivity_level" in f.get("range", {}) for f in knn_filters)


def test_sqb_02_bm25_no_knn():
    q = build_bm25_only_query(_ctx(), _qctx())
    assert "knn" not in q
    assert "query" in q


def test_sqb_07_no_sensitive_fields_in_source():
    q = build_hybrid_query(_ctx(), _qctx(), [0.1] * 1536)
    src = q["_source"]
    assert "allowed_groups" not in src
    assert "acl_tokens" not in src
    assert "acl_version" not in src


def test_sqb_04_topic_filter_included():
    q = build_hybrid_query(_ctx(), _qctx(topic="finance"), [0.1] * 1536)
    bool_filters = q["query"]["bool"]["filter"]
    topic_filters = [f for f in bool_filters if "term" in f and "topic" in f.get("term", {})]
    assert len(topic_filters) == 1
    assert topic_filters[0]["term"]["topic"] == "finance"


@pytest.mark.asyncio
async def test_sqb_06_embedding_timeout_returns_none():
    """SQB-06: Embedding API timeout → returns None → caller falls back to BM25-only."""
    import httpx
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    http = AsyncMock()
    http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    result = await get_query_embedding(
        query="test query",
        allow_knn=True,
        target_indexes=["public_index"],
        redis_client=redis,
        http_client=http,
    )
    assert result is None


@pytest.mark.asyncio
async def test_sqb_08_l1_cross_tier_uses_l0l1_model():
    """SQB-08: L1 query across public+internal → allow_knn=True, uses L0L1 1536d model."""
    from internal.querybuilder.embedding_client import EMBEDDING_MODEL_L0L1, EMBEDDING_API_URL_L0L1
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"vectors": [[0.1] * 1536]}
    http = AsyncMock()
    http.post = AsyncMock(return_value=mock_resp)
    result = await get_query_embedding(
        query="test query",
        allow_knn=True,
        target_indexes=["public_index", "internal_index"],
        redis_client=redis,
        http_client=http,
    )
    assert result == [0.1] * 1536
    call_kwargs = http.post.call_args
    assert call_kwargs.args[0] == EMBEDDING_API_URL_L0L1
    assert call_kwargs.kwargs["json"]["model"] == EMBEDDING_MODEL_L0L1


@pytest.mark.asyncio
async def test_sqb_09_allow_knn_false_skips_http():
    """SQB-09: allow_knn=False → returns None immediately; no HTTP call made."""
    redis = AsyncMock()
    http = AsyncMock()
    http.post = AsyncMock()
    result = await get_query_embedding(
        query="test query",
        allow_knn=False,
        target_indexes=["public_index"],
        redis_client=redis,
        http_client=http,
    )
    assert result is None
    http.post.assert_not_called()
