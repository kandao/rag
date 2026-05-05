import pytest
from unittest.mock import patch


def _long_text(token_count: int) -> str:
    return ("word " * token_count).strip()


@pytest.mark.asyncio
async def test_chunker_produces_chunks(parsed_job):
    from workers.chunker_worker import ChunkerWorker
    worker = ChunkerWorker()
    result = await worker.process(parsed_job)
    assert len(result.chunks) > 0
    assert result.stage == "chunker"


@pytest.mark.asyncio
async def test_chunker_1000_token_section():
    import uuid
    from datetime import datetime, timezone
    from schemas import IngestionJob, ParsedSection

    text = _long_text(1000)
    job = IngestionJob(
        job_id=str(uuid.uuid4()),
        source_type="markdown",
        source_uri="s3://docs/test.md",
        source_metadata={},
        raw_content=text,
        parsed_sections=[ParsedSection(content=text, page_number=1, section="main")],
        sensitivity_level=0,
        stage="risk_scanner",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    from workers.chunker_worker import ChunkerWorker
    worker = ChunkerWorker()
    result = await worker.process(job)

    assert len(result.chunks) >= 3, f"Expected ≥3 chunks, got {len(result.chunks)}"


def test_split_chunk_size_respected():
    from workers.chunker_worker import split_into_chunks
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = " ".join(["word"] * 500)
    chunks = split_into_chunks(text, chunk_size=400, overlap=75)

    for chunk in chunks:
        token_len = len(enc.encode(chunk.content))
        assert token_len <= 400, f"Chunk has {token_len} tokens, expected ≤400"


def test_split_adjacent_overlap():
    from workers.chunker_worker import split_into_chunks
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = " ".join([f"word{i}" for i in range(500)])
    chunks = split_into_chunks(text, chunk_size=400, overlap=75)

    if len(chunks) >= 2:
        tokens_0 = enc.encode(chunks[0].content)
        tokens_1 = enc.encode(chunks[1].content)
        overlap_count = sum(1 for t in tokens_0[-100:] if t in set(tokens_1[:100]))
        assert overlap_count > 0, "Expected adjacent chunks to share tokens"


def test_split_chinese_uses_cjk_segments(monkeypatch):
    from pipeline import chunk as chunk_module

    units = ["公司", "年度", "收入", "增长", "主要", "来自", "企业", "客户"]
    monkeypatch.setattr(
        chunk_module,
        "segment_cjk_text",
        lambda text, language="auto": units,
    )
    monkeypatch.setattr(chunk_module, "_token_len", lambda text: len(text))

    chunks = chunk_module.split_into_chunks(
        "公司年度收入增长主要来自企业客户",
        chunk_size=8,
        overlap=2,
    )

    assert len(chunks) > 1
    assert chunks[0].content == "公司年度收入增长"
    assert chunks[1].content.startswith("增长")


def test_split_japanese_uses_cjk_segments(monkeypatch):
    from pipeline import chunk as chunk_module

    units = ["検索", "サービス", "は", "日本語", "文書", "を", "安全", "に", "処理", "する"]
    seen = {}

    def fake_segment(text, language="auto"):
        seen["language"] = language
        return units

    monkeypatch.setattr(
        chunk_module,
        "segment_cjk_text",
        fake_segment,
    )
    monkeypatch.setattr(chunk_module, "_token_len", lambda text: len(text))

    chunks = chunk_module.split_into_chunks(
        "検索サービスは日本語文書を安全に処理する",
        chunk_size=7,
        overlap=2,
        language="ja",
    )

    assert seen["language"] == "ja"
    assert len(chunks) > 1
    assert chunks[0].content == "検索サービスは"
    assert chunks[1].content.startswith("は")


def test_chunk_job_uses_language_metadata_for_kanji_text(monkeypatch, parsed_job):
    from pipeline import chunk as chunk_module

    seen = {}

    def fake_segment(text, language="auto"):
        seen["language"] = language
        return ["安全", "運用", "基準"]

    monkeypatch.setattr(chunk_module, "has_cjk", lambda text: True)
    monkeypatch.setattr(
        chunk_module,
        "segment_cjk_text",
        fake_segment,
    )
    monkeypatch.setattr(chunk_module, "_token_len", lambda text: len(text))

    job = parsed_job.model_copy(
        update={
            "source_metadata": {"language": "ja"},
            "parsed_sections": [
                parsed_job.parsed_sections[0].model_copy(update={"content": "安全運用基準"})
            ],
        }
    )

    result = chunk_module.chunk_job(job, chunk_size=4, overlap=1)

    assert seen["language"] == "ja"
    assert result.chunks
