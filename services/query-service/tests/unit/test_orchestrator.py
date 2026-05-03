import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from rag_common.models.user_context import UserContext
from internal.orchestrator.orchestrator import execute, RetrievalError


def _hit(chunk_id: str, score: float, index: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id, doc_id="d1", content="text",
        citation_hint=CitationHint(path="p", page_number=None, section=None),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=0,
        retrieval_score=score, source_index=index,
    )


def _user(clearance: int) -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=clearance,
        acl_tokens=[f"level:{clearance}"], acl_key="key",
        token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_orc_06_one_index_unreachable_l0_returns_partial():
    """ORC-06: One index unreachable, L0 user → partial results from available index; no exception."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    es = AsyncMock()
    good_candidates = [_hit("c1", 0.9, "public_index"), _hit("c2", 0.7, "public_index")]
    es.search = AsyncMock(side_effect=[
        {"hits": {"hits": [
            {"_source": {"chunk_id": "c1", "doc_id": "d1", "content": "text", "path": "p",
                         "topic": "t", "doc_type": "dt", "acl_key": "k", "sensitivity_level": 0},
             "_score": 0.9},
            {"_source": {"chunk_id": "c2", "doc_id": "d1", "content": "text", "path": "p",
                         "topic": "t", "doc_type": "dt", "acl_key": "k", "sensitivity_level": 0},
             "_score": 0.7},
        ]}},
        ConnectionError("internal_index unreachable"),
    ])

    result = await execute(
        per_index_queries=[("public_index", {}), ("internal_index", {})],
        user_context=_user(0),
        raw_query="test query",
        es_client=es,
        redis_client=redis,
    )
    assert len(result) == 2
    assert all(c.source_index == "public_index" for c in result)


@pytest.mark.asyncio
async def test_orc_07_one_index_unreachable_l2_raises():
    """ORC-07: One index unreachable, L2 user → ERR_RETRIEVAL_FAILED raised (fail-closed)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    es = AsyncMock()
    es.search = AsyncMock(side_effect=[
        {"hits": {"hits": []}},
        ConnectionError("confidential_index unreachable"),
    ])

    with pytest.raises(RetrievalError) as exc:
        await execute(
            per_index_queries=[("public_index", {}), ("confidential_index", {})],
            user_context=_user(2),
            raw_query="test query",
            es_client=es,
            redis_client=redis,
        )
    assert exc.value.code == "ERR_RETRIEVAL_FAILED"


@pytest.mark.asyncio
async def test_orc_03_cache_hit_skips_es():
    """ORC-03: cache hit returns cached candidates AND es.search is never called."""
    cached = [_hit("c1", 0.9, "public_index"), _hit("c2", 0.7, "public_index")]

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps([c.model_dump() for c in cached]).encode())
    redis.set = AsyncMock()

    es = AsyncMock()
    es.search = AsyncMock()

    result = await execute(
        per_index_queries=[("public_index", {})],
        user_context=_user(1),
        raw_query="cached query",
        es_client=es,
        redis_client=redis,
    )

    assert [c.chunk_id for c in result] == ["c1", "c2"]
    es.search.assert_not_called()
