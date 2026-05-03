# Plan: Test Plan Audit + Unit Test Quality Review

## Context

The user wants to (1) confirm whether any unit test cases from `test-plan.md` are missing, and (2) review
the quality of existing unit tests against three criteria: realistic inputs, meaningful output assertions,
and correct external-API mocking.

---

## Part 1 — Missing Unit Test Cases

**~33 test IDs have no explicit unit test.** (ACL-NORM-08/09 confirmed covered in `test_acl_adapter.py`; AUD-07 is integration-only.)

### ACL Normalizer / Claims (Step 3.1)
Files: `test_auth_cache.py` (cache behaviors), `test_acl_adapter.py` (compression behaviors)

| Missing ID | Description | Target File |
|---|---|---|
| ACL-NORM-05 | Same claims twice → cache hit on 2nd call | `test_auth_cache.py` |
| ACL-NORM-06 | TOKEN_SCHEMA_VERSION bump → old cache entries unreachable; re-derived | `test_auth_cache.py` |
| ACL-NORM-07 | 100 groups, hierarchy compresses to 28 → accepted | `test_acl_adapter.py` |
| ACL-NORM-10 | Redis unavailable → derivation runs without cache; warning logged | `test_auth_cache.py` |

> Note: ACL-NORM-08 (`test_token_count_exceeds_limit_raises`) and ACL-NORM-09 (`test_acl_norm_09_deterministic_acl_key`) are already covered in `test_acl_adapter.py`.

### Redis Cache (Steps 4.2, 4.3)

| Missing ID | Description | Target File |
|---|---|---|
| REDIS-08 | DB 2 (result cache) unavailable → ES always queried; no 500 | `tests/integration/test_result_cache.py` |
| REDIS-10 | Same text on L2/L3 path → cache miss (different model_id key `bge-m3`) | new `test_embedding_cache.py` |

### Query Understanding (Step 4.1)

| Missing ID | Description | Target File |
|---|---|---|
| QU-05 | LLM parser timeout → falls back to rules-based parser; no error | `test_expander.py` or `test_parser_rules.py` |
| QU-06 | L2 user, QUERY_EXPANSION_ENABLED=true → rule-based variants only; LLM skipped | `test_expander.py` |

### Secure Query Builder (Step 4.2)

| Missing ID | Description | Target File |
|---|---|---|
| SQB-04 | topic=finance in QueryContext → term filter for topic included | `test_hybrid_query.py` |
| SQB-06 | Embedding API timeout → fall back to BM25-only for that query | `test_hybrid_query.py` or new `test_sqb_fallback.py` |
| SQB-08 | L1 query across L0+L1 → kNN allowed (same 1536d dims) | `test_hybrid_query.py` |
| SQB-09 | L2 query across L0+L1+L2 → kNN disabled (cross-tier); BM25-only | `test_hybrid_query.py` |

### Retrieval Orchestrator (Step 4.3)

| Missing ID | Description | Target File |
|---|---|---|
| ORC-01 | Single index, 50 hits → 50 RetrievalCandidates returned | `test_merger.py` or new `test_orchestrator.py` |
| ORC-06 | One index unreachable, L0 user → partial results; warning logged | new `test_orchestrator.py` |
| ORC-07 | One index unreachable, L2 user → ERR_RETRIEVAL_FAILED (fail-closed) | new `test_orchestrator.py` |
| ORC-08 | Zero hits across all indexes → empty candidate set; no error | `test_merger.py` |
| ORC-09 | `allowed_groups` not present in returned candidates (field inspection) | `test_merger.py` |

### Model Gateway (Step 5.1)

| Missing ID | Description | Target File |
|---|---|---|
| MG-03 | L3 query, L2 model config missing → 503 ERR_MODEL_UNAVAILABLE | `test_path_selector.py` or new `test_model_gateway.py` |
| MG-05 | Model times out → ERR_MODEL_UNAVAILABLE; no partial answer | new `test_model_gateway.py` |
| MG-06 | Answer verification = insufficient → "Insufficient data" returned | new `test_model_gateway.py` |
| MG-07 | ACL metadata in model response → not possible (unit confirms prompt construction) | `test_context_builder.py` |

### Audit Emitter (Step 3.4)

| Missing ID | Description | Target File |
|---|---|---|
| AUD-05 | L3 query, audit write takes 6 s (timeout=5 s) → ERR_AUDIT_FAILED_CLOSED | `test_event_builder.py` |
| AUD-06 | Guard block event → abbreviated event; query_fragment truncated at 100 chars | `test_event_builder.py` |
| AUD-08 | Audit event contains acl_tokens in plaintext → not present (document inspection) | `test_event_builder.py` |

> Note: AUD-07 (DELETE audit doc rejected by ES role) is integration-only; not a unit test gap.

### Reranker Service (Step 3.3)

| Missing ID | Description | Target File |
|---|---|---|
| RNK-02 | Request payload contains acl_tokens → Query Service strips before sending | new `test_reranker_client.py` (query-service) |
| RNK-03 | Reranker times out → fallback to retrieval order; alert emitted | new `test_reranker_client.py` (query-service) |
| RNK-04 | Reranker pod unavailable → same as timeout; alert emitted | new `test_reranker_client.py` (query-service) |
| RNK-06 | Partial failure (1 of 50 cannot score) → 49 scores; partial=true; unscored listed | `reranker-service/tests/unit/test_reranker.py` |
| RNK-08 | Same query, different candidates → scores differ (model-based, not cached) | `reranker-service/tests/unit/test_reranker.py` |

### Gateway Stub (Step 9.1)

`test_claims_signer.py` tests only the signing utility, not HTTP gateway behavior.

| Missing ID | Description | Target File |
|---|---|---|
| GW-02 | Expired token → 401 ERR_AUTH_INVALID_TOKEN | new `test_gateway_routes.py` |
| GW-03 | Missing `clearance_level` claim → 401 ERR_AUTH_MISSING_CLAIMS | new `test_gateway_routes.py` |
| GW-04 | Client injects X-Trusted-Claims header → header stripped | new `test_gateway_routes.py` |
| GW-05 | User exceeds 20 req/min → 429 ERR_GUARD_RATE_LIMIT | new `test_gateway_routes.py` |
| GW-06 | JWKS endpoint unavailable → 503 | new `test_gateway_routes.py` |
| GW-07 | User token on `/v1/ingest` → 403 (wrong scope) | new `test_gateway_routes.py` |

---

## Part 2 — Quality Issues in Existing Unit Tests

### High-priority (false-negative risk — bugs could silently pass)

| File | Test | Issue |
|---|---|---|
| `test_hybrid_query.py::test_sqb_01_acl_in_both_branches` | Uses `any("acl_tokens" in f.get("terms", {}))` — checks field NAME is present but not that the VALUE equals the user's `acl_tokens`. A regression that replaces the token list with `[]` would still pass. Should assert the actual token values. |
| `test_embedding_worker.py` | URL assertion is `"api-gateway" in url or "l0l1" in url or "embeddings" in url` — OR-chain is nearly always true; incapable of catching a wrong-endpoint regression. Should assert the exact expected URL per sensitivity level. |
| `test_acl_binder_worker.py::test_acl_binder_no_policy_empty_tokens` | Only asserts `acl_key != ""` — the weakest possible check. Should assert the specific deterministic empty-set hash value to verify the compression is deterministic. |
| `test_reranker.py::test_rnk_07_response_has_no_content` | Uses `not hasattr(results[0], "content")` — can pass spuriously with Pydantic models that strip unknown fields. Should use `results[0].model_dump()` and assert `"content"` key is absent. |

### Medium-priority (missing assertion coverage)

| File | Test | Issue |
|---|---|---|
| `test_auth_cache.py::test_set_writes_to_redis` | Only asserts cache key format. Does not verify TTL was set (`ex=` parameter). Impl uses `ex=REDIS_AUTH_CACHE_TTL_S`; a dropped argument would go undetected. |
| `test_auth_cache.py::test_cache_hit_returns_user_context` | Only checks `result.user_id`. Should also verify `result.acl_tokens` round-trips correctly — these are the security-critical fields. |
| `test_rate_limiter.py::test_guard_07_rate_limit_exceeded` | `redis.expire` is set up but never asserted. If TTL is never set the rate limit window never resets; test would miss this. |
| `test_event_builder.py::test_build_event_fields` | Does not verify `acl_tokens` is absent from the event dict (AUD-08 requirement). Add `assert "acl_tokens" not in event.model_dump()`. |
| `test_path_selector.py` | All tests only check `config.path_label`. Does not verify `top_n` or `endpoint` — the fields that actually drive model dispatch. |
| `test_merger.py::test_normalize_single_index` | Asserts `0 < scores["c2"] < 1` but the correct normalized value for a linear 10→5→0 scale is exactly 0.5. Use `pytest.approx(0.5)`. |
| No test covers `build_query_event` on the guard-block path (AUD-06: abbreviated event, query_fragment truncated). |

---

## Recommended Actions

### Action 1 — Add missing unit tests (~33 test IDs)

Extend existing files where possible; create new files only where there's no natural home:
- Extend `test_auth_cache.py`: ACL-NORM-05, ACL-NORM-06, ACL-NORM-10
- Extend `test_acl_adapter.py`: ACL-NORM-07
- Extend `test_hybrid_query.py`: SQB-04, SQB-06, SQB-08, SQB-09
- Extend `test_merger.py`: ORC-01, ORC-08, ORC-09
- Extend `test_event_builder.py`: AUD-05, AUD-06, AUD-08
- Extend `test_reranker.py` (reranker-service): RNK-06, RNK-08
- Extend `test_context_builder.py`: MG-07
- New `test_orchestrator.py`: ORC-06, ORC-07
- New `test_model_gateway.py`: MG-03, MG-05, MG-06
- New `test_reranker_client.py` (query-service): RNK-02, RNK-03, RNK-04
- New `test_gateway_routes.py` (gateway-stub): GW-02–07
- New `test_embedding_cache.py`: REDIS-10
- Integration: `test_result_cache.py`: REDIS-08

### Action 2 — Fix quality issues in existing tests

| File | Fix |
|---|---|
| `test_hybrid_query.py::test_sqb_01_acl_in_both_branches` | Assert that token VALUES equal the user's `acl_tokens`, not just that the field name appears |
| `test_embedding_worker.py` | Replace OR-chain URL assertion with exact expected endpoint per sensitivity tier |
| `test_acl_binder_worker.py::test_acl_binder_no_policy_empty_tokens` | Assert deterministic empty-set hash value, not just `acl_key != ""` |
| `test_reranker.py::test_rnk_07_response_has_no_content` | Use `results[0].model_dump()` and assert `"content" not in` |
| `test_auth_cache.py::test_set_writes_to_redis` | Assert `redis.set` was called with `ex=<expected_ttl>` |
| `test_auth_cache.py::test_cache_hit_returns_user_context` | Assert `result.acl_tokens == ctx.acl_tokens` |
| `test_rate_limiter.py::test_guard_07_rate_limit_exceeded` | Assert `redis.expire` was called with the correct TTL |
| `test_event_builder.py::test_build_event_fields` | Assert `"acl_tokens" not in event.model_dump()` |
| `test_path_selector.py` | Assert `config.top_n` and `config.endpoint` in addition to label |
| `test_merger.py::test_normalize_single_index` | Replace `0 < scores["c2"] < 1.0` with `pytest.approx(0.5)` |

---

## Verification

After implementing:
1. `pytest services/query-service/tests/unit/ -v` — unit test coverage for all applicable DDD unit IDs.
2. `pytest services/reranker-service/tests/unit/ services/gateway-stub/tests/unit/ workers/ingestion/tests/unit/ -v`.
3. Spot-check any test that previously asserted only non-null/empty to confirm it now validates meaningful values.
