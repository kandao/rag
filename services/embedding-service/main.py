import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from config import settings
from embedder import load_model
from schemas import EmbedRequest, EmbedResponse

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    logger.info("embedding-service startup complete")
    yield
    logger.info("embedding-service shutdown complete")


app = FastAPI(title="embedding-service", version="1.0.0", lifespan=lifespan)


@app.post("/v1/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    from embedder import encode
    from fastapi import HTTPException

    try:
        vectors = encode(request.texts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EmbedResponse(vectors=vectors)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    from embedder import _model
    if _model is None:
        return PlainTextResponse("model not loaded", status_code=503)
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse("# embedding-service metrics\n", media_type="text/plain")
