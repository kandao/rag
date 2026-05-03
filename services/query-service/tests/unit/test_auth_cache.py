import json
import pytest
from unittest.mock import AsyncMock

from internal.cache.auth_cache import (
    REDIS_AUTH_CACHE_TTL_S,
    get_cached_user_context,
    set_cached_user_context,
)
from rag_common.acl.claims_hash import compute_claims_hash
from rag_common.models.user_context import UserContext


def _make_ctx() -> UserContext:
    return UserContext(
        user_id="u1",
        effective_groups=["group:eng:public"],
        effective_clearance=0,
        acl_tokens=["group:eng:public", "level:0"],
        acl_key="abc",
        token_schema_version="v1",
        acl_version="v1",
        claims_hash="def",
        derived_at="2024-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    result = await get_cached_user_context(redis, "missing-hash")
    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_returns_user_context():
    ctx = _make_ctx()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(ctx.model_dump()).encode())
    result = await get_cached_user_context(redis, ctx.claims_hash)
    assert result is not None
    assert result.user_id == ctx.user_id
    assert result.acl_tokens == ctx.acl_tokens


@pytest.mark.asyncio
async def test_set_writes_to_redis():
    ctx = _make_ctx()
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=None)
    await set_cached_user_context(redis, ctx)
    redis.set.assert_called_once()
    call_args = redis.set.call_args
    assert call_args.args[0] == f"acl:{ctx.claims_hash}"
    assert call_args.kwargs.get("ex") == REDIS_AUTH_CACHE_TTL_S


@pytest.mark.asyncio
async def test_redis_unavailable_does_not_raise():
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    result = await get_cached_user_context(redis, "any-hash")
    assert result is None


@pytest.mark.asyncio
async def test_acl_norm_05_second_call_hits_cache():
    """ACL-NORM-05: Second request with same claims_hash hits Redis; no re-derivation."""
    ctx = _make_ctx()
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=[
        None,                                           # 1st call: cache miss
        json.dumps(ctx.model_dump()).encode(),          # 2nd call: cache hit
    ])
    result1 = await get_cached_user_context(redis, ctx.claims_hash)
    result2 = await get_cached_user_context(redis, ctx.claims_hash)
    assert result1 is None
    assert result2 is not None
    assert result2.acl_key == ctx.acl_key
    assert redis.get.call_count == 2


def test_acl_norm_06_schema_version_bump_invalidates_cache():
    """ACL-NORM-06: Bumping TOKEN_SCHEMA_VERSION produces a new claims_hash → old cache unreachable."""
    groups = ["eng:public@company.com"]
    hash_v1 = compute_claims_hash(groups, None, 1, "v1", "v1")
    hash_v2 = compute_claims_hash(groups, None, 1, "v2", "v1")
    assert hash_v1 != hash_v2


@pytest.mark.asyncio
async def test_acl_norm_10_set_redis_unavailable_does_not_raise():
    """ACL-NORM-10: Redis unavailable on set — error swallowed; no exception raised."""
    ctx = _make_ctx()
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    await set_cached_user_context(redis, ctx)  # must not raise
