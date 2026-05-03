import pytest
from unittest.mock import AsyncMock, MagicMock

from schemas import ACLPolicy


def _embedded_job(enriched_job, sensitivity: int = 0):
    from schemas import Chunk
    chunks = [
        c.model_copy(update={"vector": [0.1] * (1536 if sensitivity <= 1 else 1024)})
        for c in enriched_job.chunks
    ]
    policy = ACLPolicy(
        allowed_groups=["eng:infra@company.com"],
        allowed_roles=[],
        acl_tokens=["group:eng:infra"],
        acl_key="abc123",
        acl_version="v1",
    )
    return enriched_job.model_copy(update={
        "chunks": chunks,
        "sensitivity_level": sensitivity,
        "acl_policy": policy,
        "stage": "embedding",
    })


@pytest.mark.asyncio
async def test_indexer_routes_to_public(enriched_job):
    from workers.indexer_worker import IndexerWorker
    job = _embedded_job(enriched_job, sensitivity=0)

    mock_es = AsyncMock()
    mock_es.bulk = AsyncMock(return_value={"errors": False, "items": []})

    worker = IndexerWorker()
    worker._es = mock_es
    result = await worker.process(job)

    assert result is not None
    call_ops = mock_es.bulk.call_args[1]["operations"]
    index_ops = [op for op in call_ops if "index" in op]
    assert all(op["index"]["_index"] == "public_index" for op in index_ops)


@pytest.mark.asyncio
async def test_indexer_routes_to_confidential(enriched_job):
    from workers.indexer_worker import IndexerWorker
    job = _embedded_job(enriched_job, sensitivity=2)

    mock_es = AsyncMock()
    mock_es.bulk = AsyncMock(return_value={"errors": False, "items": []})

    worker = IndexerWorker()
    worker._es = mock_es
    await worker.process(job)

    call_ops = mock_es.bulk.call_args[1]["operations"]
    index_ops = [op for op in call_ops if "index" in op]
    assert all(op["index"]["_index"] == "confidential_index" for op in index_ops)


@pytest.mark.asyncio
async def test_indexer_raises_on_bulk_error(enriched_job):
    from workers.indexer_worker import IndexerWorker
    job = _embedded_job(enriched_job, sensitivity=0)

    mock_es = AsyncMock()
    mock_es.bulk = AsyncMock(return_value={
        "errors": True,
        "items": [{"index": {"_id": "x", "error": {"reason": "shard full"}}}],
    })

    worker = IndexerWorker()
    worker._es = mock_es

    with pytest.raises(RuntimeError, match="Bulk indexing errors"):
        await worker.process(job)
