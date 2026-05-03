import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_ingest_pdf_file(tmp_path):
    from workers.connector_worker import ConnectorWorker
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    worker = ConnectorWorker()
    job = await worker.ingest_file(str(pdf_path), "pdf", {"title": "Test PDF"})

    assert job.source_type == "pdf"
    assert job.raw_content_bytes == b"%PDF-1.4 fake content"
    assert job.raw_content is None
    assert job.stage == "connector"


@pytest.mark.asyncio
async def test_ingest_markdown_file(tmp_path):
    from workers.connector_worker import ConnectorWorker
    md_path = tmp_path / "test.md"
    md_path.write_text("# Title\n\nBody text.")

    worker = ConnectorWorker()
    job = await worker.ingest_file(str(md_path), "markdown", {"title": "Test MD"})

    assert job.source_type == "markdown"
    assert job.raw_content == "# Title\n\nBody text."
    assert job.raw_content_bytes is None
    assert job.stage == "connector"
