import os
import uuid
from typing import Literal

from rag_common.models.query import QueryContext, TimeRange
from rag_common.models.user_context import UserContext

from .expander import decompose_query, expand
from .parser_rules import parse

LLM_PARSER_ENABLED = os.environ.get("LLM_PARSER_ENABLED", "false").lower() == "true"
QUERY_EXPANSION_ENABLED = os.environ.get("QUERY_EXPANSION_ENABLED", "false").lower() == "true"


async def parse_query(
    raw_query: str,
    user_context: UserContext,
    request_id: str,
    risk_signal: Literal["none", "low", "medium", "high"] = "none",
    llm_client=None,
) -> QueryContext:
    """Parse raw query into a structured QueryContext.

    Uses rules-based parser for L2/L3 or when LLM parser is disabled.
    Falls back to rules if LLM parsing fails.
    """
    try:
        if user_context.effective_clearance >= 2 or not LLM_PARSER_ENABLED:
            fields = parse(raw_query)
        else:
            from .parser_llm import parse_llm
            llm_result = await parse_llm(raw_query, llm_client) if llm_client else None
            fields = llm_result if llm_result else parse(raw_query)
    except Exception:
        # QU-10: any parser failure → fall through with raw query; ACL untouched
        fields = {}

    expanded: list[str] = []
    if QUERY_EXPANSION_ENABLED:
        expanded = expand(raw_query, fields, user_context.effective_clearance)

    time_range_data = fields.get("time_range")
    time_range = None
    if time_range_data:
        time_range = TimeRange(
            year=time_range_data.get("year"),
            from_=time_range_data.get("from"),
            to=time_range_data.get("to"),
        )

    return QueryContext(
        request_id=request_id,
        raw_query=raw_query,
        keywords=fields.get("keywords", []),
        topic=fields.get("topic"),
        doc_type=fields.get("doc_type"),
        time_range=time_range,
        intent=fields.get("intent", "unknown"),
        risk_signal=risk_signal,
        expanded_queries=expanded,
    )
