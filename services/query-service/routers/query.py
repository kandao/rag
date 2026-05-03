import logging
import time
import uuid
from typing import Annotated

import httpx
import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from config import settings
from dependencies import get_es_client, get_http_client, get_redis
from internal.audit.emitter import AuditFailClosedError, emit
from internal.audit.event_builder import build_query_event, should_gate_on_audit
from internal.cache.auth_cache import get_cached_user_context, set_cached_user_context
from internal.claims.acl_adapter import derive_user_context
from internal.claims.normalizer import ClaimsNormalizationError, normalize_claims
from internal.guard.guard import GuardError, check as guard_check
from internal.input_validator import InputValidationError, validate_query_length
from internal.modelgateway.client import ModelUnavailableError, generate
from internal.reranker_client import rerank as reranker_rerank
from internal.orchestrator.orchestrator import RetrievalError, execute as retrieval_execute
from internal.querybuilder.secure_query_builder import build as qb_build
from internal.routing.router import route
from internal.understanding.expander import decompose_query
from internal.understanding.understanding import parse_query
from rag_common.models.query import QueryRequest, QueryResponse
from rag_common.models.retrieval import RankedCandidate, RetrievalCandidate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["query"])


def _http_error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": detail})


@router.post("/query", response_model=QueryResponse)
async def query(
    request_body: QueryRequest,
    x_trusted_claims: Annotated[str, Header(alias="X-Trusted-Claims")] = "",
    x_claims_sig: Annotated[str, Header(alias="X-Claims-Sig")] = "",
    redis_client: aioredis.Redis = Depends(get_redis),
    es_client: AsyncElasticsearch = Depends(get_es_client),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> QueryResponse:
    start_ms = time.monotonic_ns() // 1_000_000
    request_id = request_body.request_id or str(uuid.uuid4())

    # [0] Input validation (length / parse) — runs before Guard
    try:
        validate_query_length(request_body.query)
    except InputValidationError as exc:
        raise _http_error(exc.http_status, exc.code, str(exc))

    # [1] Normalize and verify claims
    try:
        normalized = normalize_claims(x_trusted_claims, x_claims_sig)
    except ClaimsNormalizationError as exc:
        raise _http_error(401, exc.code, str(exc))

    # [2] Auth cache lookup
    from rag_common.acl.claims_hash import compute_claims_hash
    ch = compute_claims_hash(
        groups=normalized.groups,
        role=normalized.role,
        clearance_level=normalized.clearance_level,
        token_schema_version=settings.token_schema_version,
        acl_version=settings.acl_version,
    )
    cached_ctx = await get_cached_user_context(redis_client, ch)

    # [3] Derive UserContext (or use cache)
    if cached_ctx is not None:
        user_context = cached_ctx
    else:
        try:
            user_context = derive_user_context(normalized)
        except ClaimsNormalizationError as exc:
            raise _http_error(403, exc.code, str(exc))
        await set_cached_user_context(redis_client, user_context)

    # [4] Guard checks
    try:
        guard_result = await guard_check(redis_client, user_context.user_id, request_body.query)
    except GuardError as exc:
        raise _http_error(exc.http_status, exc.code, str(exc))

    # [5] Query understanding
    query_ctx = await parse_query(
        raw_query=request_body.query,
        user_context=user_context,
        request_id=request_id,
        risk_signal=guard_result.risk_signal,
    )

    # [6] Decompose comparison queries
    sub_queries: list[str] = decompose_query(request_body.query, query_ctx.intent)

    # [7] Route to target indexes
    routing = route(query_ctx, user_context)

    all_candidates: list[RetrievalCandidate] = []
    for sub_query in sub_queries:
        # Update raw_query for sub-query embedding
        sub_ctx = query_ctx.model_copy(update={"raw_query": sub_query})

        # [8] Build secure ES queries (includes [9] assert_acl_present internally)
        try:
            per_index_queries = await qb_build(
                user_context=user_context,
                query_ctx=sub_ctx,
                routing=routing,
                redis_client=redis_client,
                http_client=http_client,
            )
        except AssertionError as exc:
            logger.error("ACL invariant violated", extra={"request_id": request_id})
            raise _http_error(500, "ERR_INTERNAL", "ACL filter invariant violated")

        # [10] Execute retrieval
        try:
            candidates = await retrieval_execute(
                per_index_queries=per_index_queries,
                user_context=user_context,
                raw_query=sub_query,
                es_client=es_client,
                redis_client=redis_client,
            )
        except RetrievalError as exc:
            raise _http_error(503, exc.code, str(exc))

        all_candidates.extend(candidates)

    # Rerank — calls reranker_service; falls back to retrieval order on failure
    ranked: list[RankedCandidate] = await reranker_rerank(
        http_client=http_client,
        request_id=request_id,
        query=request_body.query,
        candidates=all_candidates,
    )

    if not all_candidates:
        latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        _emit_audit_no_results(
            es_client, request_id, user_context, routing, all_candidates, ranked,
            latency_ms, query_ctx.risk_signal,
        )
        return QueryResponse(
            request_id=request_id,
            answer="Insufficient data to answer the query.",
            citations=[],
            answer_sufficient=False,
            model_path="none",
        )

    # [11] Model gateway — generate answer
    try:
        mg_response = await generate(
            query=request_body.query,
            candidates=all_candidates,
            http_client=http_client,
        )
    except ModelUnavailableError as exc:
        raise _http_error(503, exc.code, str(exc))

    latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms

    # [12] Emit audit event
    audit_event = build_query_event(
        request_id=request_id,
        user_context=user_context,
        target_indexes=routing.target_indexes,
        retrieved=all_candidates,
        ranked=ranked,
        model_path=mg_response.model_path,
        authorization_decision="allowed",
        query_risk_signal=str(guard_result.risk_signal),
        answer_returned=mg_response.answer_sufficient,
        latency_ms=latency_ms,
    )
    fail_closed = should_gate_on_audit(user_context)
    try:
        await emit(es_client, audit_event, fail_closed=fail_closed)
    except AuditFailClosedError as exc:
        raise _http_error(503, exc.code, str(exc))

    # Enrich citations with retrieval metadata (source_index, sensitivity_level, score)
    candidates_by_id = {c.chunk_id: c for c in all_candidates}
    enriched_citations = []
    for cit in mg_response.citations:
        cand = candidates_by_id.get(cit.get("chunk_id", ""))
        enriched_citations.append({
            **cit,
            "content": cand.content if cand else cit.get("content"),
            "source_index": cand.source_index if cand else None,
            "sensitivity_level": cand.sensitivity_level if cand else None,
            "retrieval_score": cand.retrieval_score if cand else None,
        })

    return QueryResponse(
        request_id=request_id,
        answer=mg_response.answer,
        citations=enriched_citations,
        answer_sufficient=mg_response.answer_sufficient,
        model_path=mg_response.model_path,
        retrieved_chunk_ids=[c.chunk_id for c in all_candidates],
        latency_ms=latency_ms,
    )


def _emit_audit_no_results(
    es_client, request_id, user_context, routing, retrieved, ranked,
    latency_ms, risk_signal,
):
    import asyncio
    event = build_query_event(
        request_id=request_id,
        user_context=user_context,
        target_indexes=routing.target_indexes,
        retrieved=retrieved,
        ranked=ranked,
        model_path="none",
        authorization_decision="allowed",
        query_risk_signal=str(risk_signal),
        answer_returned=False,
        latency_ms=latency_ms,
    )
    asyncio.ensure_future(emit(es_client, event, fail_closed=False))
