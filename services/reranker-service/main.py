from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from reranker import rerank_with_partial
from schemas import RerankRequest, RerankResponse

app = FastAPI(title="reranker-service", version="1.0.0")


@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank_endpoint(request: RerankRequest) -> RerankResponse:
    result = rerank_with_partial(request.query, request.candidates)
    return RerankResponse(
        request_id=request.request_id,
        ranked=result.ranked,
        partial=result.partial,
        unscored_chunk_ids=result.unscored_chunk_ids,
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return "# reranker-service metrics\n"
