import hashlib
import json
import logging
import os

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDER_L0L1 = os.environ.get("EMBEDDING_PROVIDER_L0L1", "private")
EMBEDDING_PROVIDER_L2L3 = os.environ.get("EMBEDDING_PROVIDER_L2L3", "private")
EMBEDDING_API_URL_L0L1 = os.environ.get("EMBEDDING_API_URL_L0L1", "https://api-gateway.company.internal/v1/embeddings")
EMBEDDING_API_URL_L2L3 = os.environ.get("EMBEDDING_API_URL_L2L3", "http://embedding-service.retrieval-deps:8080/v1/embed")
EMBEDDING_MODEL_L0L1 = os.environ.get("EMBEDDING_MODEL_L0L1", "text-embedding-3-small")
EMBEDDING_MODEL_L2L3 = os.environ.get("EMBEDDING_MODEL_L2L3", "bge-m3")
EMBEDDING_DIMS_L0L1 = int(os.environ.get("EMBEDDING_DIMS_L0L1", "1536"))
EMBEDDING_DIMS_L2L3 = int(os.environ.get("EMBEDDING_DIMS_L2L3", "1024"))
EMBEDDING_API_KEY_ENV_L0L1 = os.environ.get("EMBEDDING_API_KEY_ENV_L0L1", "EMBEDDING_API_KEY_L0L1")
EMBEDDING_API_KEY_ENV_L2L3 = os.environ.get("EMBEDDING_API_KEY_ENV_L2L3", "EMBEDDING_API_KEY_L2L3")
EMBEDDING_CACHE_TTL_S = int(os.environ.get("EMBEDDING_CACHE_TTL_S", "3600"))
EMBEDDING_TIMEOUT_MS = int(os.environ.get("EMBEDDING_TIMEOUT_MS", "5000"))
REDIS_DB_EMBEDDING = 3


def _cache_key(model_id: str, text: str) -> str:
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    return f"emb:{model_id}:{text_hash}"


async def get_query_embedding(
    query: str,
    allow_knn: bool,
    target_indexes: list[str],
    redis_client: aioredis.Redis,
    http_client: httpx.AsyncClient,
) -> list[float] | None:
    """Return embedding vector for query, or None if kNN is disabled or embedding fails."""
    if not allow_knn:
        return None

    l2l3 = {"confidential_index", "restricted_index"}
    is_l2l3 = any(idx in l2l3 for idx in target_indexes)
    model_id = EMBEDDING_MODEL_L2L3 if is_l2l3 else EMBEDDING_MODEL_L0L1
    api_url = EMBEDDING_API_URL_L2L3 if is_l2l3 else EMBEDDING_API_URL_L0L1
    provider = EMBEDDING_PROVIDER_L2L3 if is_l2l3 else EMBEDDING_PROVIDER_L0L1
    dims = EMBEDDING_DIMS_L2L3 if is_l2l3 else EMBEDDING_DIMS_L0L1
    api_key_env = EMBEDDING_API_KEY_ENV_L2L3 if is_l2l3 else EMBEDDING_API_KEY_ENV_L0L1

    cache_key = _cache_key(model_id, query)
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    try:
        headers = {}
        api_key = os.environ.get(api_key_env, "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": model_id}
        if provider == "openai":
            payload.update({"input": [query], "dimensions": dims})
        else:
            payload.update({"texts": [query]})
        resp = await http_client.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=EMBEDDING_TIMEOUT_MS / 1000,
        )
        resp.raise_for_status()
        data = resp.json()
        if "vectors" in data:
            vector = data["vectors"][0]
        else:
            vector = data["data"][0]["embedding"]
        try:
            await redis_client.set(cache_key, json.dumps(vector), ex=EMBEDDING_CACHE_TTL_S)
        except Exception:
            pass
        return vector
    except Exception as exc:
        logger.warning("Embedding API failed; falling back to BM25-only", extra={"error": str(exc)})
        return None
