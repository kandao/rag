"""REDIS-10: Same query text on L2/L3 path uses model bge-m3 → cache key differs from L0/L1."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from internal.querybuilder.embedding_client import (
    EMBEDDING_MODEL_L0L1,
    EMBEDDING_MODEL_L2L3,
    _cache_key,
    get_query_embedding,
)


def test_redis_10_l2l3_cache_key_differs_from_l0l1():
    """REDIS-10: Same text but different model_id → different cache key → cross-tier cache miss."""
    query = "What are the confidential finance protocols?"
    key_l0l1 = _cache_key(EMBEDDING_MODEL_L0L1, query)
    key_l2l3 = _cache_key(EMBEDDING_MODEL_L2L3, query)
    assert key_l0l1 != key_l2l3
    assert EMBEDDING_MODEL_L0L1 in key_l0l1
    assert EMBEDDING_MODEL_L2L3 in key_l2l3


@pytest.mark.asyncio
async def test_redis_10_l2l3_path_does_not_return_l0l1_cached_result():
    """REDIS-10: L2/L3 embedding request cannot hit L0/L1 cache entry (different key)."""
    query = "What are the confidential protocols?"
    l0l1_key = _cache_key(EMBEDDING_MODEL_L0L1, query)

    store = {l0l1_key: b"[0.5, 0.5]"}
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda k: store.get(k))
    redis.set = AsyncMock()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"vectors": [[0.1] * 100]}
    http = AsyncMock()
    http.post = AsyncMock(return_value=mock_resp)

    result = await get_query_embedding(
        query=query,
        allow_knn=True,
        target_indexes=["confidential_index"],
        redis_client=redis,
        http_client=http,
    )

    assert result == [0.1] * 100
    http.post.assert_called_once()
