"""Reranker HTTP client.

RNK-02: stripping — only `chunk_id` and `content` are forwarded; ACL/auth
fields on the candidate (acl_key, sensitivity_level, topic, etc.) are dropped.
RNK-03 / RNK-04: timeout and connection errors fall back to retrieval order
(rerank_score=None) and emit a warning.
"""
import logging

import httpx

from rag_common.models.retrieval import RankedCandidate, RetrievalCandidate

from config import settings

logger = logging.getLogger(__name__)


def _retrieval_order_fallback(candidates: list[RetrievalCandidate]) -> list[RankedCandidate]:
    return [RankedCandidate(chunk_id=c.chunk_id, rerank_score=None) for c in candidates]


def _build_request_payload(
    request_id: str,
    query: str,
    candidates: list[RetrievalCandidate],
) -> dict:
    """Build the reranker request body. Strips every field except chunk_id+content."""
    return {
        "request_id": request_id,
        "query": query,
        "candidates": [
            {"chunk_id": c.chunk_id, "content": c.content}
            for c in candidates
        ],
    }


async def rerank(
    http_client: httpx.AsyncClient,
    request_id: str,
    query: str,
    candidates: list[RetrievalCandidate],
) -> list[RankedCandidate]:
    """Call the reranker service. Falls back to retrieval order on failure."""
    if not candidates:
        return []
    if not settings.reranker_enabled:
        return _retrieval_order_fallback(candidates)

    payload = _build_request_payload(request_id, query, candidates)
    timeout_s = settings.reranker_timeout_ms / 1000.0
    url = f"{settings.reranker_url.rstrip('/')}/v1/rerank"

    try:
        resp = await http_client.post(url, json=payload, timeout=timeout_s)
        if resp.status_code >= 500:
            logger.warning(
                "reranker_unavailable",
                extra={"status": resp.status_code, "request_id": request_id},
            )
            return _retrieval_order_fallback(candidates)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.TimeoutException, httpx.RequestError, ConnectionError) as exc:
        logger.warning(
            "reranker_unavailable",
            extra={"error": str(exc), "request_id": request_id},
        )
        return _retrieval_order_fallback(candidates)

    ranked_items = body.get("ranked", [])
    ranked = [
        RankedCandidate(chunk_id=item["chunk_id"], rerank_score=item.get("rerank_score"))
        for item in ranked_items
    ]

    # Partial response: append unscored candidates in retrieval order
    if body.get("partial"):
        scored_ids = {r.chunk_id for r in ranked}
        for c in candidates:
            if c.chunk_id not in scored_ids:
                ranked.append(RankedCandidate(chunk_id=c.chunk_id, rerank_score=None))

    return ranked
