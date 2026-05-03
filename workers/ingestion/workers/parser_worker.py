import io
import logging

import fitz  # PyMuPDF

from config import settings
from kafka_worker import KafkaWorker
from schemas import IngestionJob, ParsedSection

logger = logging.getLogger(__name__)


def parse_pdf(raw_bytes: bytes) -> list[ParsedSection]:
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    sections = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        if text.strip():
            sections.append(ParsedSection(
                content=text,
                page_number=page_num + 1,
                section=None,
            ))
    return sections


def parse_markdown(raw_content: str) -> list[ParsedSection]:
    blocks = []
    current_section = None
    current_lines: list[str] = []

    for line in raw_content.splitlines(keepends=True):
        if line.startswith("#"):
            if current_lines:
                text = "".join(current_lines).strip()
                if text:
                    blocks.append(ParsedSection(content=text, page_number=None, section=current_section))
            current_section = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        text = "".join(current_lines).strip()
        if text:
            blocks.append(ParsedSection(content=text, page_number=None, section=current_section))

    return blocks if blocks else [ParsedSection(content=raw_content, page_number=None, section=None)]


def parse_html(raw_content: str) -> list[ParsedSection]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_content, "html.parser")
        text = soup.get_text(separator="\n")
    except ImportError:
        text = raw_content
    return [ParsedSection(content=text.strip(), page_number=None, section=None)]


def parse_wiki(raw_content: str) -> list[ParsedSection]:
    return parse_markdown(raw_content)


def parse_structured(raw_content: str) -> list[ParsedSection]:
    return [ParsedSection(content=raw_content, page_number=None, section=None)]


class ParserWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_raw,
            output_topic=settings.kafka_topic_parsed,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        match job.source_type:
            case "pdf":
                sections = parse_pdf(job.raw_content_bytes)
            case "html":
                sections = parse_html(job.raw_content)
            case "markdown":
                sections = parse_markdown(job.raw_content)
            case "wiki_export":
                sections = parse_wiki(job.raw_content)
            case "db_export":
                sections = parse_structured(job.raw_content)
            case _:
                sections = [ParsedSection(content=job.raw_content or "", page_number=None, section=None)]

        return job.model_copy(update={"parsed_sections": sections, "stage": "parser"})
