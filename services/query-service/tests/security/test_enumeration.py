"""
Security tests for enumeration detection in the query guard.
These run against the guard module directly (no network required).
"""
import pytest
from unittest.mock import AsyncMock


def _similar_queries() -> list[str]:
    return [
        "doc_1",
        "doc_2",
        "doc_3",
        "doc_4",
        "doc_5",
    ]


@pytest.mark.asyncio
async def test_enumeration_detected_with_sequential_queries():
    from internal.guard.enumeration_detector import detect_enumeration

    queries = _similar_queries()
    redis_mock = AsyncMock()
    redis_mock.lrange = AsyncMock(return_value=[q.encode() for q in queries[:-1]])
    redis_mock.lpush = AsyncMock(return_value=len(queries))
    redis_mock.ltrim = AsyncMock(return_value=True)
    redis_mock.expire = AsyncMock(return_value=True)

    result = await detect_enumeration(redis_mock, "user_enum", queries[-1])
    assert result is True


@pytest.mark.asyncio
async def test_no_enumeration_for_diverse_queries():
    from internal.guard.enumeration_detector import detect_enumeration

    diverse = [
        "What were Q4 revenue results?",
        "How does the Kubernetes deployment work?",
        "What is our HR leave policy?",
    ]
    redis_mock = AsyncMock()
    redis_mock.lrange = AsyncMock(return_value=[q.encode() for q in diverse])
    redis_mock.lpush = AsyncMock(return_value=1)
    redis_mock.ltrim = AsyncMock(return_value=True)
    redis_mock.expire = AsyncMock(return_value=True)

    result = await detect_enumeration(redis_mock, "user_normal", "What is the engineering roadmap?")
    assert result is False


@pytest.mark.asyncio
async def test_enumeration_guard_raises():
    from internal.guard.guard import check, GuardError

    sequential = ["doc_1", "doc_2", "doc_3", "doc_4", "doc_5", "doc_6", "doc_7", "doc_8", "doc_9"]

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.lrange = AsyncMock(return_value=[q.encode() for q in sequential])
    redis_mock.lpush = AsyncMock(return_value=len(sequential) + 1)
    redis_mock.ltrim = AsyncMock(return_value=True)

    try:
        await check(redis_mock, "user_enum", "doc_10")
    except GuardError as exc:
        assert exc.http_status in (400, 429)
