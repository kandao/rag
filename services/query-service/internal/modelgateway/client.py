import logging
import os
from dataclasses import dataclass

import httpx

from rag_common.models.retrieval import RetrievalCandidate

from .context_builder import MinimizedChunk, build_system_prompt, minimize_context
from .path_selector import ModelConfig, select_model_path

logger = logging.getLogger(__name__)


@dataclass
class ModelGatewayResponse:
    answer: str
    citations: list[dict]
    answer_sufficient: bool
    model_path: str
    tokens_used: int


class ModelUnavailableError(Exception):
    code = "ERR_MODEL_UNAVAILABLE"


async def _call_openai(
    system_prompt: str,
    user_query: str,
    config: ModelConfig,
    http_client: httpx.AsyncClient,
    max_tokens: int | None = None,
) -> dict:
    api_key = os.environ.get(config.api_key_env or "", "") if config.api_key_env else ""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = await http_client.post(
        config.endpoint,
        json={
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            "max_completion_tokens": max_tokens or config.max_tokens,
            "temperature": 0.0,
        },
        headers=headers,
        timeout=config.timeout_ms / 1000,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "answer_text": data["choices"][0]["message"]["content"],
        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
    }


async def _call_anthropic(
    system_prompt: str,
    user_query: str,
    config: ModelConfig,
    http_client: httpx.AsyncClient,
    max_tokens: int | None = None,
) -> dict:
    api_key = os.environ.get(config.api_key_env or "", "") if config.api_key_env else ""
    resp = await http_client.post(
        config.endpoint,
        json={
            "model": config.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_query}],
            "max_tokens": max_tokens or config.max_tokens,
        },
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        timeout=config.timeout_ms / 1000,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return {
        "answer_text": data["content"][0]["text"],
        "tokens_used": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
    }


async def generate(
    query: str,
    candidates: list[RetrievalCandidate],
    http_client: httpx.AsyncClient,
) -> ModelGatewayResponse:
    """Generate an answer using the model path selected by highest retrieved sensitivity level."""
    max_sensitivity = max((c.sensitivity_level for c in candidates), default=0)
    config = select_model_path(max_sensitivity)

    chunks: list[MinimizedChunk] = minimize_context(candidates, max_sensitivity)
    system_prompt = build_system_prompt(chunks)

    try:
        if config.provider == "anthropic":
            result = await _call_anthropic(system_prompt, query, config, http_client)
        else:
            result = await _call_openai(system_prompt, query, config, http_client)
    except Exception as exc:
        logger.error("Model call failed", extra={"path": config.path_label, "error": str(exc)})
        raise ModelUnavailableError(f"Model unavailable: {exc}") from exc

    answer_text: str = result["answer_text"]
    answer_sufficient = answer_text.strip().lower() != "insufficient data"

    citations = [
        {
            "chunk_id": c.chunk_id,
            "path": c.citation_path,
            "page_number": c.page_number,
            "section": c.section,
        }
        for c in chunks
    ]

    return ModelGatewayResponse(
        answer=answer_text,
        citations=citations,
        answer_sufficient=answer_sufficient,
        model_path=config.path_label,
        tokens_used=result.get("tokens_used", 0),
    )
