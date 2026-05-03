# E2E Test Plan

This plan explains how to test the RAG system end to end. It is written for a new operator who has not run a RAG stack before.

Use these companion runbooks:

- `docs/test/e2e-local-test-runbook.md` for deterministic local tests with stubbed model calls.
- `docs/test/e2e-local-real-provider-runbook.md` for local tests that call OpenAI APIs.
- `docs/test/e2e-troubleshooting.md` for common failures.

## What RAG Means Here

RAG means Retrieval-Augmented Generation.

In this repo, a query follows this path:

1. `gateway-stub` accepts a user token like `test-token-l1`.
2. `gateway-stub` converts that token into signed trusted claims.
3. `query-service` verifies the claims signature.
4. `query-service` derives ACL tokens and clearance level.
5. `query-service` searches Elasticsearch with ACL filters.
6. `query-service` sends retrieved chunks to the model gateway.
7. The model gateway calls either the stub LLM or OpenAI.
8. `query-service` returns an answer and citations.
9. `query-service` writes an audit event to Elasticsearch.

An E2E test is useful only when all layers above are working together.

## Profiles

`local_test`:

- Uses local Elasticsearch and Redis.
- Uses `llm-stub`, not OpenAI.
- Intentionally avoids real external LLM cost.
- Best first test after code changes.

`local`:

- Uses local Elasticsearch and Redis.
- Calls OpenAI for LLM.
- Calls OpenAI for embeddings.
- Requires a real ignored secret file.
- Best for real-provider smoke tests and quality checks.

## Test Suites

Existing E2E tests live under `services/query-service/tests/e2e`.

| File | Purpose | Requires |
|---|---|---|
| `test_acl_boundary.py` | ACL isolation and sensitivity boundaries | Seeded ES |
| `test_cache.py` | Redis auth-cache hit rate | Redis + gateway |
| `test_answer_quality.py` | Answer quality and no-hallucination gates | Seeded ES + LLM |
| `test_retrieval_quality.py` | Retrieval recall/MRR gates | Seeded ES |
| `test_security_gaps.py` | injection/enumeration/token checks | Seeded ES + gateway |
| `test_reranker_quality.py` | Reranker gates | Reranker enabled |

## Recommended Test Order

Run tests in this order:

1. Cluster and pod health.
2. Gateway health.
3. Elasticsearch index and data readiness.
4. One manual gateway query.
5. ACL and security tests.
6. Retrieval quality tests.
7. Answer quality tests.
8. Reranker tests only when reranker is intentionally enabled.
9. Full E2E suite.

Do not start with the full suite. It is harder to debug.

## Pass Criteria

Minimum pass criteria for `local_test`:

- Helm release is deployed.
- Gateway `/healthz` and `/readyz` return ok.
- Query-service pod is running.
- Elasticsearch and Redis pods are running.
- Focused E2E tests pass, or failures are explained by missing seeded data.

Minimum pass criteria for `local`:

- All `local_test` infrastructure checks pass.
- `query-service-config` shows OpenAI LLM and OpenAI embeddings.
- `values-local.secret.yaml` is ignored by git.
- OpenAI keys are present in Kubernetes secrets.
- At least one manual query reaches the gateway.
- Quality tests are run only after Elasticsearch contains the expected chunks.

## Data Readiness

Many tests expect these chunk IDs:

- `eng-guide-2024-001`
- `hr-policy-2024-001`
- `product-overview-001`
- `legal-contract-q1-001`
- `m-and-a-memo-2024-001`

Before quality gates, verify that Elasticsearch contains those IDs. If they are missing, the stack may be healthy but the E2E quality tests are not meaningful.

The current Helm chart deploys the runtime services. Treat fixture seeding as a separate required preparation step. If indexes or chunks are missing, use the troubleshooting guide and record the run as blocked by data readiness, not as a model failure.

## Result Recording

For every run, record:

- Date and time.
- Git commit or working tree description.
- Profile: `local_test` or `local`.
- Helm revision.
- Image tags used.
- Which tests ran.
- Pass/fail/skip counts.
- Known blockers.
- Links or paths to logs.

Use this simple result block:

```text
Date:
Profile:
Helm revision:
Images:
Data readiness:
Command:
Result:
Notes:
```
