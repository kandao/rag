import re
from functools import lru_cache
from typing import Literal, Protocol

ChunkLanguage = Literal["auto", "zh", "ja"]

_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")


class _JapaneseTagger(Protocol):
    def parse(self, text: str) -> str:
        ...


def has_cjk(text: str) -> bool:
    return bool(_HAN_RE.search(text) or _KANA_RE.search(text))


def has_japanese(text: str) -> bool:
    return bool(_KANA_RE.search(text))


@lru_cache(maxsize=1)
def _get_japanese_tagger() -> _JapaneseTagger:
    try:
        from fugashi import Tagger
    except ImportError as exc:
        raise RuntimeError(
            "Japanese chunking requires fugashi and unidic-lite. "
            "Install the ingestion worker dependencies first."
        ) from exc

    return Tagger("-Owakati")


def _segment_japanese(text: str) -> list[str]:
    parsed = _get_japanese_tagger().parse(text)
    return [token for token in parsed.split() if token]


def _segment_chinese(text: str) -> list[str]:
    try:
        import jieba
    except ImportError as exc:
        raise RuntimeError(
            "Chinese chunking requires jieba. Install the ingestion worker dependencies first."
        ) from exc

    return [token for token in jieba.lcut(text, cut_all=False) if token]


def segment_cjk_text(text: str, language: ChunkLanguage = "auto") -> list[str]:
    if not has_cjk(text):
        return []
    if language == "ja":
        return _segment_japanese(text)
    if language == "zh":
        return _segment_chinese(text)
    if has_japanese(text):
        return _segment_japanese(text)
    return _segment_chinese(text)
