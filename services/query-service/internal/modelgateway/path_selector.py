import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider: str          # "openai" | "anthropic"
    endpoint: str
    model: str
    api_key_env: str | None
    timeout_ms: int
    max_tokens: int
    path_label: str        # "cloud_l1" | "private_l2" | "private_l3"


_MODEL_CONFIGS = {
    "l0l1": ModelConfig(
        provider=os.environ.get("MODEL_PROVIDER_L0L1", "openai"),
        endpoint=os.environ.get("MODEL_ENDPOINT_L0L1", "https://api-gateway.company.internal/v1/llm/chat/completions"),
        model=os.environ.get("MODEL_NAME_L0L1", "gpt-4o"),
        api_key_env=os.environ.get("MODEL_API_KEY_ENV_L0L1", "MODEL_API_KEY_L0L1"),
        timeout_ms=int(os.environ.get("MODEL_TIMEOUT_MS_L0L1", "30000")),
        max_tokens=int(os.environ.get("MODEL_MAX_TOKENS_L0L1", "1024")),
        path_label="cloud_l1",
    ),
    "l2": ModelConfig(
        provider=os.environ.get("MODEL_PROVIDER_L2", "openai"),
        endpoint=os.environ.get("MODEL_ENDPOINT_L2", "http://llm-private.retrieval-deps:8080/v1/chat/completions"),
        model=os.environ.get("MODEL_NAME_L2", "llama-3-70b-instruct"),
        api_key_env=os.environ.get("MODEL_API_KEY_ENV_L2", ""),
        timeout_ms=int(os.environ.get("MODEL_TIMEOUT_MS_L2", "45000")),
        max_tokens=int(os.environ.get("MODEL_MAX_TOKENS_L2", "1024")),
        path_label="private_l2",
    ),
    "l3": ModelConfig(
        provider=os.environ.get("MODEL_PROVIDER_L3", "openai"),
        endpoint=os.environ.get("MODEL_ENDPOINT_L3", "http://llm-restricted.retrieval-deps:8080/v1/chat/completions"),
        model=os.environ.get("MODEL_NAME_L3", "llama-3-70b-instruct"),
        api_key_env=os.environ.get("MODEL_API_KEY_ENV_L3", ""),
        timeout_ms=int(os.environ.get("MODEL_TIMEOUT_MS_L3", "45000")),
        max_tokens=int(os.environ.get("MODEL_MAX_TOKENS_L3", "1024")),
        path_label="private_l3",
    ),
}


def select_model_path(max_sensitivity_level: int) -> ModelConfig:
    """Return model config based on highest sensitivity_level among retrieved chunks.

    Routing key is the chunk sensitivity, not the user clearance level.
    """
    if max_sensitivity_level <= 1:
        return _MODEL_CONFIGS["l0l1"]
    elif max_sensitivity_level == 2:
        return _MODEL_CONFIGS["l2"]
    else:
        return _MODEL_CONFIGS["l3"]
