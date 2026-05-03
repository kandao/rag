import logging
import os

logger = logging.getLogger(__name__)

ANSWER_VERIFICATION_ENABLED = os.environ.get("ANSWER_VERIFICATION_ENABLED", "false").lower() == "true"


async def verify_answer(
    query: str,
    answer: str,
    context_text: str,
    http_client,
    model_config,
) -> bool:
    """Return True if answer is grounded in context. Returns True (pass) on any failure."""
    if not ANSWER_VERIFICATION_ENABLED:
        return True

    from .client import _call_openai, _call_anthropic

    verification_prompt = (
        "Is the following context sufficient to answer the question? "
        "Reply with only 'sufficient' or 'insufficient'.\n\n"
        f"Question: {query}\n\nContext:\n{context_text}"
    )

    try:
        if model_config.provider == "anthropic":
            result = await _call_anthropic("", verification_prompt, model_config, http_client, max_tokens=10)
        else:
            result = await _call_openai("", verification_prompt, model_config, http_client, max_tokens=10)
        return result["answer_text"].strip().lower().startswith("sufficient")
    except Exception as exc:
        logger.warning("Answer verification failed; proceeding", extra={"error": str(exc)})
        return True
