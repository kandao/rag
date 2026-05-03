from pydantic import BaseModel


class RerankCandidate(BaseModel):
    chunk_id: str
    content: str


class RerankRequest(BaseModel):
    request_id: str
    query: str
    candidates: list[RerankCandidate]


class RankedItem(BaseModel):
    chunk_id: str
    rerank_score: float


class RerankResponse(BaseModel):
    request_id: str
    ranked: list[RankedItem]
    partial: bool = False
    unscored_chunk_ids: list[str] = []
