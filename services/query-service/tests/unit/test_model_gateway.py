import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx

from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from internal.modelgateway.client import generate, ModelUnavailableError


def _candidate(sensitivity: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id="c1", doc_id="d1", content="some text",
        citation_hint=CitationHint(path="doc.pdf", page_number=1, section="S1"),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=sensitivity,
        retrieval_score=0.9, source_index="public_index",
    )


def _mock_openai_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": 50},
    }
    return resp


@pytest.mark.asyncio
async def test_mg_03_l3_endpoint_unavailable_raises():
    """MG-03: L3 sensitivity chunk → restricted endpoint unreachable → ERR_MODEL_UNAVAILABLE."""
    http = AsyncMock()
    http.post = AsyncMock(side_effect=ConnectionError("llm-restricted unreachable"))

    with pytest.raises(ModelUnavailableError) as exc:
        await generate(
            query="What is the classified protocol?",
            candidates=[_candidate(3)],
            http_client=http,
        )
    assert exc.value.code == "ERR_MODEL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mg_05_model_timeout_raises():
    """MG-05: Model HTTP call times out → ModelUnavailableError raised; no partial answer."""
    http = AsyncMock()
    http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(ModelUnavailableError) as exc:
        await generate(
            query="What is the revenue for 2024?",
            candidates=[_candidate(0)],
            http_client=http,
        )
    assert exc.value.code == "ERR_MODEL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mg_06_insufficient_answer_returns_flag():
    """MG-06: Model returns 'insufficient data' → answer_sufficient=False."""
    http = AsyncMock()
    http.post = AsyncMock(return_value=_mock_openai_response("insufficient data"))

    result = await generate(
        query="What are the 2024 device regulations?",
        candidates=[_candidate(0)],
        http_client=http,
    )
    assert result.answer_sufficient is False
    assert result.answer.strip().lower() == "insufficient data"


@pytest.mark.asyncio
async def test_openai_request_uses_max_completion_tokens():
    http = AsyncMock()
    http.post = AsyncMock(return_value=_mock_openai_response("answer"))

    await generate(
        query="What are the 2024 device regulations?",
        candidates=[_candidate(0)],
        http_client=http,
    )

    payload = http.post.call_args.kwargs["json"]
    assert payload["max_completion_tokens"] == 1024
    assert "max_tokens" not in payload
