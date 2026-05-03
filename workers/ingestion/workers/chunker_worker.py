import logging

import tiktoken

from config import settings
from kafka_worker import KafkaWorker
from schemas import Chunk, IngestionJob

logger = logging.getLogger(__name__)

_tokenizer: tiktoken.Encoding | None = None


def _get_tokenizer() -> tiktoken.Encoding:
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding(settings.chunker_tokenizer)
    return _tokenizer


def split_into_chunks(
    text: str,
    chunk_size: int = 400,
    overlap: int = 75,
    page_number: int | None = None,
    section: str | None = None,
) -> list[Chunk]:
    enc = _get_tokenizer()
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)
        chunks.append(Chunk(
            content=chunk_text,
            page_number=page_number,
            section=section,
        ))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


class ChunkerWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_scanned,
            output_topic=settings.kafka_topic_chunked,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        all_chunks: list[Chunk] = []
        for section in job.parsed_sections:
            chunks = split_into_chunks(
                text=section.content,
                chunk_size=settings.chunk_size_tokens,
                overlap=settings.chunk_overlap_tokens,
                page_number=section.page_number,
                section=section.section,
            )
            all_chunks.extend(chunks)

        return job.model_copy(update={"chunks": all_chunks, "stage": "chunker"})
