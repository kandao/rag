import logging
from dataclasses import dataclass

from config import BATCH_SIZE, MAX_SEQUENCE_LENGTH, MODEL_PATH
from schemas import RankedItem, RerankCandidate

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(MODEL_PATH, max_length=MAX_SEQUENCE_LENGTH)
    return _model


@dataclass
class RerankResult:
    ranked: list[RankedItem]
    partial: bool
    unscored_chunk_ids: list[str]


def rerank(query: str, candidates: list[RerankCandidate]) -> list[RankedItem]:
    """Run batch CrossEncoder inference. Returns items sorted by rerank_score descending."""
    result = rerank_with_partial(query, candidates)
    return result.ranked


def rerank_with_partial(query: str, candidates: list[RerankCandidate]) -> RerankResult:
    """Score candidates, falling back to per-item scoring on batch failure.

    Returns RerankResult with partial=True and unscored_chunk_ids populated if any item fails.
    """
    if not candidates:
        return RerankResult(ranked=[], partial=False, unscored_chunk_ids=[])

    model = _get_model()
    pairs = [(query, c.content) for c in candidates]

    try:
        scores = model.predict(pairs, batch_size=BATCH_SIZE, show_progress_bar=False)
        ranked = [
            RankedItem(chunk_id=c.chunk_id, rerank_score=float(score))
            for c, score in zip(candidates, scores)
        ]
        return RerankResult(
            ranked=sorted(ranked, key=lambda x: -x.rerank_score),
            partial=False,
            unscored_chunk_ids=[],
        )
    except Exception:
        logger.warning("Batch scoring failed; attempting per-item fallback")

    ranked = []
    unscored = []
    for c in candidates:
        try:
            score = model.predict([(query, c.content)], show_progress_bar=False)[0]
            ranked.append(RankedItem(chunk_id=c.chunk_id, rerank_score=float(score)))
        except Exception:
            unscored.append(c.chunk_id)

    return RerankResult(
        ranked=sorted(ranked, key=lambda x: -x.rerank_score),
        partial=len(unscored) > 0,
        unscored_chunk_ids=unscored,
    )
