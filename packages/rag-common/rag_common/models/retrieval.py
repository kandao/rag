from pydantic import BaseModel


class CitationHint(BaseModel):
    path: str
    page_number: int | None
    section: str | None


class RetrievalCandidate(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    citation_hint: CitationHint
    topic: str
    doc_type: str
    acl_key: str
    sensitivity_level: int
    retrieval_score: float
    source_index: str


class RankedCandidate(BaseModel):
    chunk_id: str
    rerank_score: float | None  # 0.0–1.0 cross-encoder relevance; None on reranker failure / fallback
