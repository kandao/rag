import hashlib

import pytest


@pytest.mark.asyncio
async def test_enricher_sets_doc_id(chunked_job):
    from workers.enricher_worker import EnricherWorker
    worker = EnricherWorker()
    result = await worker.process(chunked_job)

    expected_doc_id = hashlib.sha256(chunked_job.source_uri.encode()).hexdigest()
    assert all(c.doc_id == expected_doc_id for c in result.chunks)


@pytest.mark.asyncio
async def test_enricher_sets_chunk_id(chunked_job):
    from workers.enricher_worker import EnricherWorker
    worker = EnricherWorker()
    result = await worker.process(chunked_job)

    doc_id = hashlib.sha256(chunked_job.source_uri.encode()).hexdigest()
    for i, chunk in enumerate(result.chunks):
        assert chunk.chunk_id == f"{doc_id}-{i}"


@pytest.mark.asyncio
async def test_enricher_all_chunks_have_required_fields(chunked_job):
    from workers.enricher_worker import EnricherWorker
    worker = EnricherWorker()
    result = await worker.process(chunked_job)

    for chunk in result.chunks:
        assert chunk.doc_id is not None
        assert chunk.chunk_id is not None


@pytest.mark.asyncio
async def test_enricher_stage(chunked_job):
    from workers.enricher_worker import EnricherWorker
    worker = EnricherWorker()
    result = await worker.process(chunked_job)
    assert result.stage == "metadata_enricher"
