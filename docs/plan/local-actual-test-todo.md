# Local Actual Test Todo

This file tracks what we still need before running the `local` environment with real provider keys and endpoints. `local_test` remains the deterministic E2E profile with stubs.

## Configuration

- [ ] Create ignored secret override:
  `deploy/charts/rag/values-local.secret.yaml`
- [ ] Fill `CLAIMS_SIGNING_KEY` in `values-local.secret.yaml`.
- [ ] Fill real LLM provider keys:
  - `MODEL_API_KEY_L0L1`
  - `MODEL_API_KEY_L2`
  - `MODEL_API_KEY_L3`
- [ ] Fill real embedding provider keys:
  - `EMBEDDING_API_KEY_L0L1`
  - `EMBEDDING_API_KEY_L2L3`
- [ ] Confirm `deploy/charts/rag/values-local.yaml` model provider settings:
  - `MODEL_PROVIDER_L0L1`
  - `MODEL_ENDPOINT_L0L1`
  - `MODEL_NAME_L0L1`
  - `MODEL_PROVIDER_L2`
  - `MODEL_ENDPOINT_L2`
  - `MODEL_NAME_L2`
  - `MODEL_PROVIDER_L3`
  - `MODEL_ENDPOINT_L3`
  - `MODEL_NAME_L3`
- [ ] Confirm embedding settings and dimensions:
  - L0/L1: `text-embedding-3-small`, `1536`
  - L2/L3: `text-embedding-3-small`, `1024`

## Deploy

- [ ] Build current dev images:
  - `rag/query-service:dev`
  - `rag/gateway-stub:dev`
  - `rag/embedding-service:dev`
  - `rag/reranker-service:dev`
  - `rag/llm-stub:dev` only if needed for fallback comparison
- [ ] Deploy the real-provider local profile:
  `helm upgrade --install rag-system deploy/charts/rag -f deploy/charts/rag/values-local.yaml -f deploy/charts/rag/values-local.secret.yaml --set global.createNamespaces=false`
- [ ] Verify rendered runtime config:
  - `query-service-config`
  - `gateway-stub-config`
  - `query-config-files`
  - `query-service-secrets`
  - `gateway-stub-secrets`
- [ ] Confirm no real secret values are committed:
  - `git check-ignore -v deploy/charts/rag/values-local.secret.yaml`
  - search for provider key patterns before commit

## Data

- [ ] Recreate Elasticsearch indexes with vector dimensions matching `local`:
  - `public_index` / `internal_index`: `1536`
  - `confidential_index` / `restricted_index`: `1024`
- [ ] Seed documents with real embeddings from the configured provider.
- [ ] Ensure seeded document ACL tokens use group/role tokens only; do not include `level:*` in document `acl_tokens`.
- [ ] Create or verify `audit-events-current` alias.
- [ ] Clear Redis caches after reseeding.

## Validation

- [ ] Port-forward local services as needed:
  - gateway: `8080`
  - Elasticsearch: `9200`
  - Redis: `6379`
  - embedding-service: `8001` if directly checked
  - reranker-service: `8002` if reranker gates are enabled
- [ ] Smoke test a query through gateway with `test-token-l1`.
- [ ] Check query-service logs for:
  - real LLM provider calls
  - real embedding provider calls
  - no fallback to BM25 unless expected
  - no secret leakage
- [ ] Run focused E2E answer-quality tests against real LLM provider.
- [ ] Run focused retrieval-quality tests against real embeddings.
- [ ] Decide whether reranker is required locally:
  - If no local model is mounted, keep `RERANKER_REQUIRED=false`.
  - If a model is mounted, set `RERANKER_REQUIRED=true` and run reranker quality gates.
- [ ] Run full E2E suite and record result here.

## Latest Result

- Pending. The last completed green E2E result was for `local_test`, not real-provider `local`: `26 passed, 2 skipped`.
