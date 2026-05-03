import json
import pytest
from unittest.mock import AsyncMock

from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from internal.orchestrator.result_cache import get_cached_results, set_cached_results


def _c(cid: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=cid, doc_id="d1", content="text",
        citation_hint=CitationHint(path="p", page_number=None, section=None),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=0,
        retrieval_score=0.9, source_index="public_index",
    )


@pytest.mark.asyncio
async def test_orc_03_cache_hit():
    candidates = [_c("c1"), _c("c2")]
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps([c.model_dump() for c in candidates]).encode())
    result = await get_cached_results(redis, "query", "acl_key", ["public_index"])
    assert result is not None
    assert len(result) == 2


@pytest.mark.asyncio
async def test_orc_04_different_acl_key_is_miss():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    result = await get_cached_results(redis, "query", "different_acl_key", ["public_index"])
    assert result is None


@pytest.mark.asyncio
async def test_set_then_get_roundtrip():
    store = {}
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=lambda k, v, ex: store.update({k: v}))
    redis.get = AsyncMock(side_effect=lambda k: store.get(k))

    candidates = [_c("c1")]
    await set_cached_results(redis, "query", "acl_key", ["public_index"], candidates)
    result = await get_cached_results(redis, "query", "acl_key", ["public_index"])
    assert result is not None
    assert result[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_redis_08_result_cache_unavailable_returns_none():
    """REDIS-08: DB 2 (result cache) unavailable → cache miss; no exception raised."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("Redis DB2 down"))
    result = await get_cached_results(redis, "query", "acl_key", ["public_index"])
    assert result is None


@pytest.mark.asyncio
async def test_redis_08_result_cache_set_unavailable_does_not_raise():
    """REDIS-08: Result cache write failure swallowed; no exception propagated."""
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=ConnectionError("Redis DB2 down"))
    await set_cached_results(redis, "query", "acl_key", ["public_index"], [_c("c1")])
