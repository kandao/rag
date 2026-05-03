import logging
import os

from elasticsearch import AsyncElasticsearch

from rag_common.models.retrieval import CitationHint, RetrievalCandidate

logger = logging.getLogger(__name__)

ES_REQUEST_TIMEOUT_S = int(os.environ.get("ES_REQUEST_TIMEOUT_MS", "5000")) / 1000


def _map_hit(hit: dict, source_index: str) -> RetrievalCandidate:
    src = hit["_source"]
    return RetrievalCandidate(
        chunk_id=src["chunk_id"],
        doc_id=src["doc_id"],
        content=src["content"],
        citation_hint=CitationHint(
            path=src.get("path", ""),
            page_number=src.get("page_number"),
            section=src.get("section"),
        ),
        topic=src.get("topic", ""),
        doc_type=src.get("doc_type", ""),
        acl_key=src.get("acl_key", ""),
        sensitivity_level=src.get("sensitivity_level", 0),
        retrieval_score=hit.get("_score") or 0.0,
        source_index=source_index,
    )


async def search_index(
    es_client: AsyncElasticsearch,
    index: str,
    query: dict,
) -> list[RetrievalCandidate]:
    """Execute a single ES search and map hits to RetrievalCandidates. Raises on error."""
    response = await es_client.search(
        index=index,
        body=query,
        request_timeout=ES_REQUEST_TIMEOUT_S,
    )
    hits = response.get("hits", {}).get("hits", [])
    return [_map_hit(h, index) for h in hits]
