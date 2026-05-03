import logging
import os
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from config import settings
from routers.query import router as query_router

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=0,
        decode_responses=True,
    )
    app.state.es = AsyncElasticsearch(
        hosts=settings.es_hosts.split(","),
        http_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
    )
    app.state.http = httpx.AsyncClient(timeout=30.0)
    logger.info("query-service startup complete")
    yield
    await app.state.redis.aclose()
    await app.state.es.close()
    await app.state.http.aclose()
    logger.info("query-service shutdown complete")


app = FastAPI(title="query-service", version="1.0.0", lifespan=lifespan)
app.include_router(query_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    try:
        await app.state.redis.ping()
        await app.state.es.ping()
    except Exception as exc:
        return PlainTextResponse(f"not ready: {exc}", status_code=503)
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse("# query-service metrics\n", media_type="text/plain")
