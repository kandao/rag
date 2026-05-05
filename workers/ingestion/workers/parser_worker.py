import io
import logging

import fitz  # PyMuPDF

from config import settings
from kafka_worker import KafkaWorker
from pipeline.parse import (
    parse_html,
    parse_job,
    parse_markdown,
    parse_pdf,
    parse_structured,
    parse_wiki,
)
from schemas import IngestionJob

logger = logging.getLogger(__name__)


def parse_pdf(raw_bytes: bytes):
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    sections = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        if text.strip():
            from schemas import ParsedSection

            sections.append(
                ParsedSection(
                    content=text,
                    page_number=page_num + 1,
                    section=None,
                )
            )
    return sections


class ParserWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_raw,
            output_topic=settings.kafka_topic_parsed,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        return parse_job(job)
