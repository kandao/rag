import pytest
from unittest.mock import AsyncMock, patch

from internal.guard.rate_limiter import RATE_LIMIT_WINDOW_S, check_rate_limit


@pytest.mark.asyncio
async def test_guard_07_rate_limit_exceeded():
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=21)
    redis.expire = AsyncMock()
    result = await check_rate_limit(redis, "u1")
    assert result is False
    redis.expire.assert_not_called()


@pytest.mark.asyncio
async def test_within_limit():
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=5)
    redis.expire = AsyncMock()
    result = await check_rate_limit(redis, "u1")
    assert result is True


@pytest.mark.asyncio
async def test_first_request_sets_ttl_window():
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    result = await check_rate_limit(redis, "u1")
    assert result is True
    redis.expire.assert_called_once_with("guard_rl:u1", RATE_LIMIT_WINDOW_S)


@pytest.mark.asyncio
async def test_redis_down_allows_request():
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=ConnectionError("down"))
    result = await check_rate_limit(redis, "u1")
    assert result is True
