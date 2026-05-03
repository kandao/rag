import pytest
from unittest.mock import AsyncMock

from internal.guard.enumeration_detector import detect_enumeration


def _make_redis(history: list[str]):
    client = AsyncMock()
    client.lrange = AsyncMock(return_value=[h.encode() for h in history])
    client.lpush = AsyncMock()
    client.ltrim = AsyncMock()
    client.expire = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_guard_08_sequential_enumeration():
    history = ["doc_1", "doc_2", "doc_3", "doc_4", "doc_5", "doc_6", "doc_7", "doc_8", "doc_9"]
    redis = _make_redis(history)
    detected = await detect_enumeration(redis, "u1", "doc_10")
    assert detected is True


@pytest.mark.asyncio
async def test_normal_queries_not_flagged():
    history = ["finance report 2024", "HR policy", "engineering guidelines"]
    redis = _make_redis(history)
    detected = await detect_enumeration(redis, "u1", "board meeting schedule")
    assert detected is False


@pytest.mark.asyncio
async def test_high_similarity_flagged():
    base = "what is the contract for vendor"
    history = [f"{base} {i}" for i in range(9)]
    redis = _make_redis(history)
    detected = await detect_enumeration(redis, "u1", f"{base} 9")
    assert detected is True
