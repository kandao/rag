import os
import pytest
from unittest.mock import AsyncMock
os.environ.setdefault("SYNONYM_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "../../../../deploy/config/synonym-config.yaml"))

import internal.understanding.expander as _mod
_mod._LOADED = False

from internal.understanding.expander import decompose_query, expand
from rag_common.models.user_context import UserContext


def _user(clearance: int) -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=clearance,
        acl_tokens=[f"level:{clearance}"], acl_key="k",
        token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


def test_decompose_comparison():
    subs = decompose_query("Compare the old and new finance reporting procedures", "comparison")
    assert len(subs) == 2
    assert any("old" in s for s in subs)
    assert any("new" in s for s in subs)


def test_decompose_non_comparison():
    subs = decompose_query("What is the revenue for 2024?", "factual_lookup")
    assert subs == ["What is the revenue for 2024?"]


def test_expand_policy_lookup():
    context = {"intent": "policy_lookup", "keywords": ["medical", "device"], "doc_type": "regulation"}
    variants = expand("What are medical device regulations?", context, clearance_level=0)
    assert any("regulations about" in v.lower() for v in variants)


@pytest.mark.asyncio
async def test_qu_05_llm_timeout_falls_back_to_rules():
    """QU-05: LLM parser timeout → parse_llm returns None → rules-based parser used; no error."""
    import internal.understanding.understanding as und

    llm_client = AsyncMock()
    llm_client.complete = AsyncMock(side_effect=TimeoutError("LLM timed out"))

    orig = und.LLM_PARSER_ENABLED
    und.LLM_PARSER_ENABLED = True
    try:
        result = await und.parse_query(
            raw_query="What are the 2024 medical device regulation updates?",
            user_context=_user(1),
            request_id="r1",
            llm_client=llm_client,
        )
        assert result.intent == "policy_lookup"
        assert result.raw_query == "What are the 2024 medical device regulation updates?"
    finally:
        und.LLM_PARSER_ENABLED = orig


@pytest.mark.asyncio
async def test_qu_06_l2_user_skips_llm_uses_rules():
    """QU-06: L2 user + LLM_PARSER_ENABLED=true → skips LLM; rules-based parser used."""
    import internal.understanding.understanding as und

    llm_client = AsyncMock()
    llm_client.complete = AsyncMock()

    orig_llm = und.LLM_PARSER_ENABLED
    orig_exp = und.QUERY_EXPANSION_ENABLED
    und.LLM_PARSER_ENABLED = True
    und.QUERY_EXPANSION_ENABLED = True
    try:
        result = await und.parse_query(
            raw_query="What are medical device regulations?",
            user_context=_user(2),
            request_id="r2",
            llm_client=llm_client,
        )
        llm_client.complete.assert_not_called()
        assert result.intent is not None
    finally:
        und.LLM_PARSER_ENABLED = orig_llm
        und.QUERY_EXPANSION_ENABLED = orig_exp
