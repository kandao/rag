# QA Automation Runbook

Run these commands after manual QA passes or is clearly blocked.

## 1. Confirm Port-Forwards Are Running

Gateway must be reachable:

```bash
curl -sS http://127.0.0.1:8080/healthz
```

Redis must be reachable if cache tests are run:

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
```

If Redis CLI is not installed, run the pytest command anyway. The cache test will skip or fail with a clear error.

## 2. Run Focused Automated QA

Start with cache and security:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_cache.py \
             services/query-service/tests/e2e/test_security_gaps.py -q
```

Record the final pytest line, for example:

```text
6 passed
```

or:

```text
2 failed, 4 passed
```

## 3. Run Data-Dependent Automated QA

Run this only if Elasticsearch data readiness passed:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_acl_boundary.py \
             services/query-service/tests/e2e/test_retrieval_quality.py \
             services/query-service/tests/e2e/test_answer_quality.py -q
```

If expected chunks are missing, mark these tests as blocked by data readiness.

## 4. Run Full E2E

Run full E2E only after focused failures are understood:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e -q
```

## 5. Reranker Automation

Do not run reranker-required tests for the current `local` profile.

Only run this when reranker is intentionally enabled and the pod is running:

```bash
RERANKER_REQUIRED=true \
GATEWAY_URL=http://127.0.0.1:8080 \
RERANKER_URL=http://127.0.0.1:8002 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_reranker_quality.py -q
```

## 6. Record Result

Copy this into the QA result:

```text
Focused automated QA:
Data-dependent automated QA:
Full E2E:
Reranker QA:
Skipped tests:
Failures:
```
