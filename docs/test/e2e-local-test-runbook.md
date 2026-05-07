# E2E Runbook: `local_test`

Use this runbook first. It tests the local RAG stack without calling OpenAI.

## 1. Start From Repo Root

```bash
cd /path/to/rag
```

## 2. Check Kubernetes Context

```bash
kubectl config current-context
kubectl get nodes
```

Expected:

- Context should point to your local cluster, such as `orbstack`.
- At least one node should be `Ready`.

If this fails, stop and fix the local Kubernetes cluster.

## 3. Build Images

Build the images used by `local_test`:

```bash
docker build -t rag/query-service:dev -f services/query-service/Dockerfile .
docker build -t rag/gateway-stub:dev -f services/gateway-stub/Dockerfile .
docker build -t rag/embedding-service:dev -f services/embedding-service/Dockerfile .
docker build -t rag/reranker-service:dev -f services/reranker-service/Dockerfile .
docker build -t rag/llm-stub:dev -f services/llm-stub/Dockerfile .
```

Confirm images exist:

```bash
docker images | grep 'rag/'
```

## 4. Create Local Test Secret File

Create the ignored secret override only if it does not exist:

```bash
test -f deploy/charts/rag/values-local_test.secret.yaml || \
  cp deploy/charts/rag/values-local_test.secret.example.yaml deploy/charts/rag/values-local_test.secret.yaml
```

Check that git ignores it:

```bash
git check-ignore -v deploy/charts/rag/values-local_test.secret.yaml
```

Expected: a `.gitignore` rule is printed.

## 5. Deploy `local_test`

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local_test.yaml \
  -f deploy/charts/rag/values-local_test.secret.yaml
```

Check Helm:

```bash
helm status rag-system
```

Expected: `STATUS: deployed`.

## 6. Check Pods

```bash
kubectl get pods -n api-gateway
kubectl get pods -n query
kubectl get pods -n retrieval-deps
kubectl get pods -n reranker
```

Expected:

- `gateway-stub` is `Running`.
- `query-service` is `Running`.
- `elasticsearch` is `Running`.
- `redis` is `Running`.
- `llm-stub` is `Running`.

## 7. Port-Forward Gateway

Open a new terminal and run:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Leave this terminal open. This connects your laptop port `8080` to the gateway service inside Kubernetes.

## 8. Health Check

In the original terminal:

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/readyz
```

Expected:

- `/healthz` returns `{"status":"ok"}`.
- `/readyz` says users were loaded.

## 9. Check Data Readiness

Port-forward Elasticsearch:

```bash
kubectl -n retrieval-deps port-forward svc/elasticsearch 9200:9200
```

In another terminal, check indexes:

```bash
curl -sS http://127.0.0.1:9200/_cat/indices?v
curl -sS http://127.0.0.1:9200/_cat/aliases?v
```

Check expected chunks:

```bash
curl -sS 'http://127.0.0.1:9200/*/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"ids":{"values":["eng-guide-2024-001","hr-policy-2024-001","product-overview-001","legal-contract-q1-001","m-and-a-memo-2024-001"]}}}'
```

If chunks are missing, record the run as blocked by data readiness.

## 10. Manual Query

```bash
curl -sS http://127.0.0.1:8080/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-token-l1' \
  -d '{"query":"What are the engineering guidelines for 2024?"}'
```

Expected:

- HTTP 200.
- A JSON response with `answer`.
- If data is seeded, `citations` should not be empty.
- If data is not seeded, the answer should say insufficient data.

## 11. Run Focused E2E Tests

Run ACL and security first:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  ${PYTHON:-python} \
  -m pytest services/query-service/tests/e2e/test_acl_boundary.py \
             services/query-service/tests/e2e/test_security_gaps.py -q
```

Run retrieval quality:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  ${PYTHON:-python} \
  -m pytest services/query-service/tests/e2e/test_retrieval_quality.py -q
```

Run full E2E:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  ${PYTHON:-python} \
  -m pytest services/query-service/tests/e2e -q
```

## 12. Save Result

Record:

```text
Profile: local_test
Helm revision:
Data readiness:
Focused tests:
Full E2E:
Notes:
```
