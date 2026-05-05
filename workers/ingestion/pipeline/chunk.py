from config import settings
from schemas import Chunk, IngestionJob
from .cjk_segmenter import ChunkLanguage, has_cjk, segment_cjk_text
from .tokenizer import get_encoding

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = get_encoding(settings.chunker_tokenizer)
    return _tokenizer


def split_into_chunks(
    text: str,
    chunk_size: int = 400,
    overlap: int = 75,
    page_number: int | None = None,
    section: str | None = None,
    language: ChunkLanguage = "auto",
) -> list[Chunk]:
    if has_cjk(text):
        return split_cjk_into_chunks(
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
            page_number=page_number,
            section=section,
            language=language,
        )

    enc = _get_tokenizer()
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)
        chunks.append(
            Chunk(
                content=chunk_text,
                page_number=page_number,
                section=section,
            )
        )
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


def _token_len(text: str) -> int:
    return len(_get_tokenizer().encode(text))


def _split_oversized_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    page_number: int | None,
    section: str | None,
) -> list[Chunk]:
    enc = _get_tokenizer()
    tokens = enc.encode(text)
    chunks = []
    start = 0
    step = max(chunk_size - min(overlap, chunk_size - 1), 1)
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(
            Chunk(
                content=enc.decode(tokens[start:end]),
                page_number=page_number,
                section=section,
            )
        )
        if end == len(tokens):
            break
        start += step
    return chunks


def _overlap_unit_count(units: list[str], overlap: int) -> int:
    if overlap <= 0:
        return 0

    selected = 0
    for i in range(len(units) - 1, -1, -1):
        candidate = "".join(units[i:])
        if _token_len(candidate) > overlap:
            break
        selected = len(units) - i
    return selected


def split_cjk_into_chunks(
    text: str,
    chunk_size: int = 400,
    overlap: int = 75,
    page_number: int | None = None,
    section: str | None = None,
    language: ChunkLanguage = "auto",
) -> list[Chunk]:
    units = segment_cjk_text(text, language=language)
    if not units:
        return []

    chunks = []
    start = 0
    effective_overlap = min(overlap, chunk_size - 1)

    while start < len(units):
        end = start
        current: list[str] = []

        while end < len(units):
            candidate = "".join(current + [units[end]])
            if current and _token_len(candidate) > chunk_size:
                break
            if not current and _token_len(candidate) > chunk_size:
                chunks.extend(
                    _split_oversized_text(
                        units[end],
                        chunk_size=chunk_size,
                        overlap=effective_overlap,
                        page_number=page_number,
                        section=section,
                    )
                )
                end += 1
                break
            current.append(units[end])
            end += 1

        if current:
            chunks.append(
                Chunk(
                    content="".join(current),
                    page_number=page_number,
                    section=section,
                )
            )

        if end >= len(units):
            break

        overlap_units = _overlap_unit_count(current, effective_overlap)
        start = max(end - overlap_units, start + 1)

    return chunks


def chunk_job(
    job: IngestionJob,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
    language: ChunkLanguage | None = None,
) -> IngestionJob:
    all_chunks: list[Chunk] = []
    chunk_language = language or job.source_metadata.get("language", "auto")
    for section in job.parsed_sections:
        chunks = split_into_chunks(
            text=section.content,
            chunk_size=chunk_size or settings.chunk_size_tokens,
            overlap=overlap if overlap is not None else settings.chunk_overlap_tokens,
            page_number=section.page_number,
            section=section.section,
            language=chunk_language,
        )
        all_chunks.extend(chunks)

    return job.model_copy(update={"chunks": all_chunks, "stage": "chunker"})
