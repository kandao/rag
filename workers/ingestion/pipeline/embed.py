import os

import httpx

from config import settings
from schemas import IngestionJob
from .tokenizer import get_encoding

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = get_encoding(settings.chunker_tokenizer)
    return _tokenizer


def auth_headers(api_key_env: str) -> dict[str, str]:
    api_key = os.environ.get(api_key_env, "")
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def embed_openai(
    texts: list[str],
    http_client: httpx.AsyncClient,
    *,
    api_url: str,
    model: str,
    dimensions: int,
    batch_size: int,
    api_key_env: str,
) -> list[list[float]]:
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    vectors = []
    for batch in batches:
        resp = await http_client.post(
            api_url,
            json={"model": model, "input": batch, "dimensions": dimensions},
            headers=auth_headers(api_key_env),
            timeout=settings.embedding_timeout_ms / 1000,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors.extend([item["embedding"] for item in data["data"]])
    return vectors


async def embed_private(
    texts: list[str],
    http_client: httpx.AsyncClient,
    *,
    api_url: str,
    batch_size: int,
) -> list[list[float]]:
    enc = _get_tokenizer()
    for text in texts:
        token_count = len(enc.encode(text))
        assert token_count <= 7000, f"Chunk exceeds safe bge-m3 sequence length: {token_count} tokens"

    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    vectors = []
    for batch in batches:
        resp = await http_client.post(
            api_url,
            json={"texts": batch},
            timeout=settings.embedding_timeout_ms / 1000,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors.extend(data["vectors"])
    return vectors


async def embed_job(
    job: IngestionJob,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> IngestionJob:
    async def _run(client: httpx.AsyncClient) -> IngestionJob:
        sensitivity = job.sensitivity_level or 0

        l0l1_chunks = [(i, c) for i, c in enumerate(job.chunks) if sensitivity <= 1]
        l2l3_chunks = [(i, c) for i, c in enumerate(job.chunks) if sensitivity > 1]

        chunks = list(job.chunks)

        if l0l1_chunks:
            texts = [c.content for _, c in l0l1_chunks]
            if settings.embedding_provider_l0l1 == "openai":
                vectors = await embed_openai(
                    texts,
                    client,
                    api_url=settings.embedding_api_url_l0l1,
                    model=settings.embedding_model_l0l1,
                    dimensions=settings.embedding_dims_l0l1,
                    batch_size=settings.embedding_batch_size_l0l1,
                    api_key_env=settings.embedding_api_key_env_l0l1,
                )
            else:
                vectors = await embed_private(
                    texts,
                    client,
                    api_url=settings.embedding_api_url_l0l1,
                    batch_size=settings.embedding_batch_size_l0l1,
                )
            for (i, _), vec in zip(l0l1_chunks, vectors):
                chunks[i] = chunks[i].model_copy(update={"vector": vec})

        if l2l3_chunks:
            texts = [c.content for _, c in l2l3_chunks]
            if settings.embedding_provider_l2l3 == "openai":
                vectors = await embed_openai(
                    texts,
                    client,
                    api_url=settings.embedding_api_url_l2l3,
                    model=settings.embedding_model_l2l3,
                    dimensions=settings.embedding_dims_l2l3,
                    batch_size=settings.embedding_batch_size_l2l3,
                    api_key_env=settings.embedding_api_key_env_l2l3,
                )
            else:
                vectors = await embed_private(
                    texts,
                    client,
                    api_url=settings.embedding_api_url_l2l3,
                    batch_size=settings.embedding_batch_size_l2l3,
                )
            for (i, _), vec in zip(l2l3_chunks, vectors):
                chunks[i] = chunks[i].model_copy(update={"vector": vec})

        return job.model_copy(update={"chunks": chunks, "stage": "embedding"})

    if http_client is not None:
        return await _run(http_client)

    async with httpx.AsyncClient() as client:
        return await _run(client)
