import uuid
from datetime import datetime, timezone

import pytest

from schemas import ACLPolicy, Chunk, IngestionJob, ParsedSection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def base_job() -> IngestionJob:
    return IngestionJob(
        job_id=str(uuid.uuid4()),
        source_type="markdown",
        source_uri="s3://docs/engineering_guidelines_2024.md",
        source_metadata={"title": "Engineering Guidelines", "author": "eng-team"},
        raw_content="# Engineering Guidelines\n\nINTERNAL USE ONLY\n\nThis document covers...",
        stage="connector",
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def pdf_job() -> IngestionJob:
    return IngestionJob(
        job_id=str(uuid.uuid4()),
        source_type="pdf",
        source_uri="s3://docs/finance_report_2024.pdf",
        source_metadata={"title": "Finance Report 2024"},
        raw_content_bytes=b"%PDF-1.4 placeholder",
        stage="connector",
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def parsed_job(base_job: IngestionJob) -> IngestionJob:
    sections = [
        ParsedSection(content=f"Section {i} content with some text.", page_number=i, section=f"sec{i}")
        for i in range(1, 4)
    ]
    return base_job.model_copy(update={"parsed_sections": sections, "stage": "parser"})


@pytest.fixture
def chunked_job(parsed_job: IngestionJob) -> IngestionJob:
    chunks = [
        Chunk(content=f"Chunk {i} content.", page_number=1, section="sec1")
        for i in range(5)
    ]
    return parsed_job.model_copy(update={"chunks": chunks, "stage": "chunker", "sensitivity_level": 1})


@pytest.fixture
def enriched_job(chunked_job: IngestionJob) -> IngestionJob:
    import hashlib
    doc_id = hashlib.sha256(chunked_job.source_uri.encode()).hexdigest()
    chunks = [
        c.model_copy(update={
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}-{i}",
        })
        for i, c in enumerate(chunked_job.chunks)
    ]
    return chunked_job.model_copy(update={"chunks": chunks, "stage": "metadata_enricher"})
