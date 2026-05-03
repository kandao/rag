# Test Work Todo

This file tracks the current test-work status after the E2E/unit test implementation pass described in `docs/plan/unit-test-improvement.md`.

## Current Status

- [x] E2E test files exist under `services/query-service/tests/e2e/`.
- [x] Security test files exist under `services/query-service/tests/security/`.
- [x] Query-service unit test files exist for ACL, guard, query builder, retrieval, model gateway, audit, reranker client, and cache coverage.
- [x] Reranker, gateway-stub, embedding-service, and ingestion worker unit test files exist.
- [x] The planned missing-unit-test IDs are mostly represented in source tests.
- [x] Unit tests pass using `/Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python`.
- [x] Security tests pass.
- [x] Query-service and ingestion integration tests pass.
- [x] E2E tests pass against the running seeded local stack, with reranker quality gates skipped because the local reranker model is not mounted.

## Current Blockers

- The current shell uses Python 3.14.3, while service `pyproject.toml` files target Python `^3.11`.
- The current shell has no installed service dependencies such as `pydantic`, `fastapi`, and `numpy`.
- There is no root `pyproject.toml`, lockfile, `.venv`, `poetry`, or `uv` in this checkout.
- The local reranker pod is ready but not usable for quality gates because `/models/bge-reranker-large` is not mounted as a valid model directory.

## Remaining Work

- [x] Select a test environment with service dependencies.
- [x] Run query-service unit tests.
- [x] Run gateway-stub unit tests.
- [x] Classify `GW-05`, `GW-06`, and `GW-07` as gateway-stub skipped placeholders; these are production-gateway or unimplemented-scope behaviors.
- [x] Run reranker-service unit tests.
- [x] Run embedding-service unit tests.
- [x] Run ingestion worker unit tests.
- [x] Run query-service integration tests.
- [x] Run ingestion integration tests.
- [x] Run query-service security tests.
- [x] Run E2E tests against the local seeded stack.
- [ ] Mount or configure a valid reranker model, then rerun E2E with `RERANKER_REQUIRED=true`.

## Verification Commands

Use these from the repository root. The verified local interpreter was:

```bash
/Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python
```

```bash
PYTHONPATH=packages/rag-common:services/query-service /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/query-service/tests/unit -q
PYTHONPATH=services/reranker-service /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/reranker-service/tests/unit -q
PYTHONPATH=packages/rag-common:services/gateway-stub /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/gateway-stub/tests/unit -q
PYTHONPATH=packages/rag-common:services/embedding-service /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/embedding-service/tests/unit -q
PYTHONPATH=packages/rag-common:workers/ingestion /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest workers/ingestion/tests/unit -q
```

E2E, only with the full seeded stack running:

```bash
PYTHONPATH=packages/rag-common:services/query-service /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/query-service/tests/e2e -q
```

Strict reranker E2E after a valid model is mounted:

```bash
RERANKER_REQUIRED=true PYTHONPATH=packages/rag-common:services/query-service /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python -m pytest services/query-service/tests/e2e/test_reranker_quality.py -q
```

## Latest Verification Results

- Query-service unit: `97 passed`.
- Reranker-service unit: `7 passed`.
- Gateway-stub unit: `9 passed, 3 skipped`.
- Embedding-service unit: `8 passed`.
- Ingestion unit: `29 passed`.
- Query-service security: `12 passed`.
- Query-service integration: `14 passed`.
- Ingestion integration: `10 passed`.
- Query-service E2E: `26 passed, 2 skipped`.

## Done Criteria

- [x] All runnable unit suites pass.
- [x] Any skipped gateway cases are explicitly classified as either implemented, design-deferred, or production-gateway-only.
- [x] E2E tests either pass against the full local stack or remain documented as stack-required.
- [x] `docs/plan/todo.md` reflects the final status after verification.
