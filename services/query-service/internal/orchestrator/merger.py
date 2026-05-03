from rag_common.models.retrieval import RetrievalCandidate


def normalize_scores(candidates_by_index: dict[str, list[RetrievalCandidate]]) -> list[RetrievalCandidate]:
    """Apply per-index min-max score normalization, then return a flat list."""
    result: list[RetrievalCandidate] = []
    for _, candidates in candidates_by_index.items():
        if not candidates:
            continue
        scores = [c.retrieval_score for c in candidates]
        min_s, max_s = min(scores), max(scores)
        for c in candidates:
            if max_s == min_s:
                c.retrieval_score = 1.0
            else:
                c.retrieval_score = (c.retrieval_score - min_s) / (max_s - min_s)
        result.extend(candidates)
    return result


def dedup_and_cap(candidates: list[RetrievalCandidate], max_total: int) -> list[RetrievalCandidate]:
    """Deduplicate by chunk_id (keep highest score), sort descending, cap at max_total."""
    seen: dict[str, RetrievalCandidate] = {}
    for c in candidates:
        if c.chunk_id not in seen or c.retrieval_score > seen[c.chunk_id].retrieval_score:
            seen[c.chunk_id] = c
    return sorted(seen.values(), key=lambda x: -x.retrieval_score)[:max_total]
