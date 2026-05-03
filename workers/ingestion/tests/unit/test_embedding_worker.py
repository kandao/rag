import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_http_response(vectors: list[list[float]], is_cloud: bool = True):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if is_cloud:
        resp.json.return_value = {"data": [{"embedding": v} for v in vectors]}
    else:
        resp.json.return_value = {"vectors": vectors}
    return resp


@pytest.mark.asyncio
async def test_embed_l0_uses_cloud(enriched_job):
    from workers.embedding_worker import EmbeddingWorker

    job = enriched_job.model_copy(update={"sensitivity_level": 0})
    fake_vectors = [[0.1] * 1536 for _ in job.chunks]

    http = AsyncMock()
    http.post = AsyncMock(return_value=_mock_http_response(fake_vectors, is_cloud=True))

    worker = EmbeddingWorker()
    worker._http = http
    result = await worker.process(job)

    assert all(len(c.vector) == 1536 for c in result.chunks)
    assert result.stage == "embedding"
    http.post.assert_called()
    call_url = http.post.call_args[0][0]
    assert call_url == "https://api-gateway.company.internal/v1/embeddings"


@pytest.mark.asyncio
async def test_embed_l2_uses_private(enriched_job):
    from workers.embedding_worker import EmbeddingWorker

    job = enriched_job.model_copy(update={"sensitivity_level": 2})
    fake_vectors = [[0.2] * 1024 for _ in job.chunks]

    http = AsyncMock()
    http.post = AsyncMock(return_value=_mock_http_response(fake_vectors, is_cloud=False))

    worker = EmbeddingWorker()
    worker._http = http
    result = await worker.process(job)

    assert all(len(c.vector) == 1024 for c in result.chunks)
    call_url = http.post.call_args[0][0]
    assert call_url == "http://embedding-service.retrieval-deps:8080/v1/embed"
