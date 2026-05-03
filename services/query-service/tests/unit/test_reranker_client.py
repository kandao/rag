"""RNK-02 / RNK-03 / RNK-04 — reranker HTTP client.

RNK-02: Query Service strips acl_tokens (and all other auth/metadata fields)
        from candidates before sending to the reranker.
RNK-03: Reranker times out → fallback to retrieval order; warning emitted.
RNK-04: Reranker pod unavailable (ConnectionError) → same fallback.
"""
import logging

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from internal.reranker_client import rerank


def _candidate(chunk_id: str, content: str, score: float = 0.9) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        doc_id="d1",
        content=content,
        citation_hint=CitationHint(path="p", page_number=None, section=None),
        topic="finance",
        doc_type="policy",
        acl_key="acl-key-secret",
        sensitivity_level=2,
        retrieval_score=score,
        source_index="confidential_index",
    )


def _mock_ok_response(items):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"request_id": "r1", "ranked": items, "partial": False}
    return resp


@pytest.mark.asyncio
async def test_rnk_02_acl_tokens_stripped_from_request():
    """RNK-02: payload sent to reranker contains only chunk_id+content per candidate."""
    candidates = [
        _candidate("c1", "first content"),
        _candidate("c2", "second content"),
    ]
    # Smuggle in extra ACL fields the way an unsanitized dict might
    object.__setattr__(candidates[0], "acl_tokens", ["group:eng:secret"])
    object.__setattr__(candidates[0], "allowed_groups", ["eng:secret"])

    http = AsyncMock()
    http.post = AsyncMock(return_value=_mock_ok_response([
        {"chunk_id": "c1", "rerank_score": 0.95},
        {"chunk_id": "c2", "rerank_score": 0.6},
    ]))

    await rerank(http_client=http, request_id="r1", query="q", candidates=candidates)

    sent_json = http.post.call_args.kwargs["json"]
    assert set(sent_json.keys()) == {"request_id", "query", "candidates"}
    for sent_candidate in sent_json["candidates"]:
        # Only chunk_id and content — nothing else
        assert set(sent_candidate.keys()) == {"chunk_id", "content"}
        for forbidden in (
            "acl_tokens", "allowed_groups", "acl_key",
            "sensitivity_level", "topic", "doc_type", "source_index",
            "retrieval_score", "doc_id", "citation_hint",
        ):
            assert forbidden not in sent_candidate

    # And as a defensive substring check on the raw payload
    import json as _json
    raw = _json.dumps(sent_json)
    assert "acl_tokens" not in raw
    assert "acl-key-secret" not in raw
    assert "group:eng:secret" not in raw


@pytest.mark.asyncio
async def test_rnk_03_timeout_falls_back_to_retrieval_order(caplog):
    """RNK-03: httpx TimeoutException → retrieval-order fallback + warning logged."""
    candidates = [_candidate(f"c{i}", f"content {i}", score=1.0 - i * 0.1) for i in range(3)]

    http = AsyncMock()
    http.post = AsyncMock(side_effect=httpx.TimeoutException("reranker timed out"))

    with caplog.at_level(logging.WARNING):
        result = await rerank(http_client=http, request_id="r1", query="q", candidates=candidates)

    assert [r.chunk_id for r in result] == ["c0", "c1", "c2"]
    assert all(r.rerank_score is None for r in result)
    assert any("reranker_unavailable" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_rnk_04_connection_error_falls_back(caplog):
    """RNK-04: pod unavailable (ConnectionError) → same fallback as timeout."""
    candidates = [_candidate("a", "x"), _candidate("b", "y")]

    http = AsyncMock()
    http.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with caplog.at_level(logging.WARNING):
        result = await rerank(http_client=http, request_id="r1", query="q", candidates=candidates)

    assert [r.chunk_id for r in result] == ["a", "b"]
    assert all(r.rerank_score is None for r in result)
    assert any("reranker_unavailable" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_empty_candidates_short_circuits():
    http = AsyncMock()
    http.post = AsyncMock()
    result = await rerank(http_client=http, request_id="r1", query="q", candidates=[])
    assert result == []
    http.post.assert_not_called()
