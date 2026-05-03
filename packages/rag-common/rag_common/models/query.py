from typing import Literal
from pydantic import BaseModel


class TimeRange(BaseModel):
    year: int | None = None
    from_: int | None = None
    to: int | None = None

    model_config = {"populate_by_name": True}


class QueryContext(BaseModel):
    request_id: str
    raw_query: str
    keywords: list[str]
    topic: str | None
    doc_type: str | None
    time_range: TimeRange | None
    intent: Literal["factual_lookup", "comparison", "policy_lookup", "summary", "unknown"]
    risk_signal: Literal["none", "low", "medium", "high"]
    expanded_queries: list[str]


class QueryRequest(BaseModel):
    query: str
    request_id: str | None = None


class CitationResult(BaseModel):
    chunk_id: str
    path: str
    page_number: int | None = None
    section: str | None = None
    content: str | None = None
    sensitivity_level: int | None = None
    source_index: str | None = None
    retrieval_score: float | None = None


class QueryResponse(BaseModel):
    request_id: str
    answer: str
    citations: list[CitationResult] = []
    answer_sufficient: bool = True
    model_path: str
    retrieved_chunk_ids: list[str] = []
    latency_ms: int = 0
    verified: bool | None = None
