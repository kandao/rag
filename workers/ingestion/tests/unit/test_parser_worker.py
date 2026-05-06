import pytest
from unittest.mock import MagicMock, patch

from schemas import ParsedSection


def _make_pdf_job():
    import uuid
    from datetime import datetime, timezone
    from schemas import IngestionJob
    return IngestionJob(
        job_id=str(uuid.uuid4()),
        source_type="pdf",
        source_uri="s3://docs/test.pdf",
        source_metadata={},
        raw_content_bytes=b"%PDF-1.4 fake",
        stage="connector",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def test_parse_markdown():
    from workers.parser_worker import parse_markdown
    content = "# Section 1\n\nSome body text.\n\n# Section 2\n\nMore text."
    sections = parse_markdown(content)
    assert len(sections) >= 2
    assert all(isinstance(s, ParsedSection) for s in sections)
    assert any("body text" in s.content for s in sections)


def test_parse_markdown_no_headers():
    from workers.parser_worker import parse_markdown
    content = "Just plain text without headers."
    sections = parse_markdown(content)
    assert len(sections) == 1
    assert sections[0].content == content


def test_parse_sec_markdown_bold_item_headings():
    from workers.parser_worker import parse_markdown

    content = """---
ticker: RKLB
company: "Rocket Lab Corporation"
form: 10-K
---

**PART I**

**Item 1. Business**

Rocket Lab builds launch vehicles and spacecraft.

**Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations**

Revenue increased due to launch services and space systems.
"""

    sections = parse_markdown(content)

    assert [s.section for s in sections] == [
        "Item 1. Business",
        "Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations",
    ]
    assert "Rocket Lab builds" in sections[0].content
    assert "Revenue increased" in sections[1].content


def test_parse_html():
    from workers.parser_worker import parse_html
    html = "<html><body><h1>Title</h1><p>Content here.</p></body></html>"
    sections = parse_html(html)
    assert len(sections) == 1
    assert "Content here" in sections[0].content


@pytest.mark.asyncio
async def test_parser_preserves_raw_content(base_job):
    original_content = base_job.raw_content
    from workers.parser_worker import ParserWorker
    worker = ParserWorker()
    result = await worker.process(base_job)

    assert result.raw_content == original_content  # Immutable Source Principle
    assert len(result.parsed_sections) > 0
    assert result.stage == "parser"


@pytest.mark.asyncio
async def test_parser_pdf_produces_sections():
    pages = [MagicMock() for _ in range(10)]
    for i, p in enumerate(pages):
        p.get_text.return_value = f"Page {i+1} content with some text here."

    mock_doc = MagicMock()
    mock_doc.__len__ = MagicMock(return_value=10)
    mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])

    with patch("workers.parser_worker.fitz.open", return_value=mock_doc):
        from workers.parser_worker import parse_pdf
        sections = parse_pdf(b"%PDF-1.4 fake")

    assert len(sections) == 10
    assert all(s.page_number == i + 1 for i, s in enumerate(sections))
