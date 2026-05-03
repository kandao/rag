import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from config import settings

logger = logging.getLogger(__name__)

_model: "SentenceTransformer | None" = None


def load_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading model %s", settings.model_name)
        _model = SentenceTransformer(settings.model_name)
    return _model


def encode(texts: list[str]) -> list[list[float]]:
    for text in texts:
        token_ids = load_model().tokenizer.encode(text)
        if len(token_ids) > settings.max_seq_len:
            raise ValueError(
                f"Text exceeds max sequence length {settings.max_seq_len}: got {len(token_ids)} tokens"
            )
    model = load_model()
    vectors = model.encode(
        texts,
        batch_size=settings.batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]
