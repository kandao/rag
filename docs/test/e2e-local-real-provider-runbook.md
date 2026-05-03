# E2E Runbook: `local`

Use this runbook when you want the local stack to call OpenAI for LLM and embeddings.

## 1. Cost And Secret Warning

The `local` profile calls real OpenAI APIs. Every query can spend tokens.

Never paste real keys into committed files or logs. The real key file is:

```text
deploy/charts/rag/values-local.secret.yaml
```

It must stay ignored by git.

## 2. Check Repo And Cluster

```bash
cd /Users/chengtaowu/Desktop/AiWorkSpace/rag
kubectl config current-context
kubectl get nodes
```

Expected:

- Local context, such as `orbstack`.
- Node status is `Ready`.

## 3. Build Images

For the current OpenAI-backed `local` profile, build:

```bash
docker build -t rag/query-service:dev -f services/query-service/Dockerfile .
docker build -t rag/gateway-stub:dev -f services/gateway-stub/Dockerfile .
```

Optional support images:

```bash
docker build -t rag/embedding-service:dev -f services/embedding-service/Dockerfile .
docker build -t rag/reranker-service:dev -f services/reranker-service/Dockerfile .
docker build -t rag/llm-stub:dev -f services/llm-stub/Dockerfile .
```

The current `local` profile disables embedding-service and reranker-service because OpenAI handles embeddings and `RERANKER_ENABLED=false`.

## 4. Prepare Secret Override

Create the ignored file if needed:

```bash
test -f deploy/charts/rag/values-local.secret.yaml || \
  cp deploy/charts/rag/values-local.secret.example.yaml deploy/charts/rag/values-local.secret.yaml
```

Open the file and fill OpenAI keys for:

```yaml
MODEL_API_KEY_L0L1: replace-with-openai-api-key
MODEL_API_KEY_L2: replace-with-openai-api-key
MODEL_API_KEY_L3: replace-with-openai-api-key
EMBEDDING_API_KEY_L0L1: replace-with-openai-api-key
EMBEDDING_API_KEY_L2L3: replace-with-openai-api-key
```

Keep local ES credentials blank:

```yaml
ES_USERNAME: ""
ES_PASSWORD: ""
AUDIT_ES_USERNAME: ""
AUDIT_ES_PASSWORD: ""
```

Check ignore status:

```bash
git check-ignore -v deploy/charts/rag/values-local.secret.yaml
```

Expected: a `.gitignore` rule is printed.

## 5. Deploy `local`

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local.yaml \
  -f deploy/charts/rag/values-local.secret.yaml \
  --set global.createNamespaces=false
```

Check release:

```bash
helm status rag-system
```

Expected: `STATUS: deployed`.

## 6. Check Runtime Config

```bash
kubectl get configmap query-service-config -n query \
  -o jsonpath='{.data.MODEL_PROVIDER_L0L1} {.data.MODEL_NAME_L0L1} {.data.EMBEDDING_PROVIDER_L0L1} {.data.EMBEDDING_MODEL_L0L1} {.data.RERANKER_ENABLED}'
```

Expected:

```text
openai gpt-5.4-mini openai text-embedding-3-small false
```

Check pods:

```bash
kubectl get pods -n api-gateway
kubectl get pods -n query
kubectl get pods -n retrieval-deps
kubectl get pods -n reranker
```

Expected:

- Gateway is running.
- Query service is running.
- Elasticsearch is running.
- Redis is running.
- Reranker namespace can be empty for this profile.

## 7. Port-Forward Services

Gateway:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Elasticsearch:

```bash
kubectl -n retrieval-deps port-forward svc/elasticsearch 9200:9200
```

Redis, only when cache tests are needed:

```bash
kubectl -n retrieval-deps port-forward svc/redis 6379:6379
```

Keep these terminals open while running tests.

## 8. Health Check

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/readyz
```

Expected:

- Gateway health is ok.
- Gateway readiness says users are loaded.

## 9. Data Readiness Check

Check aliases:

```bash
curl -sS http://127.0.0.1:9200/_cat/aliases?v
```

Check expected chunks:

```bash
curl -sS 'http://127.0.0.1:9200/*/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"ids":{"values":["eng-guide-2024-001","hr-policy-2024-001","product-overview-001","legal-contract-q1-001","m-and-a-memo-2024-001"]}}}'
```

Expected:

- Search result `hits.total.value` should be greater than zero.
- For full quality gates, all expected chunks should exist.

If data is missing, do not run quality gates yet. Record the run as blocked by data readiness.

## 10. Manual Real-Provider Query

```bash
curl -sS http://127.0.0.1:8080/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-token-l1' \
  -d '{"query":"What are the engineering guidelines for 2024?"}'
```

Expected:

- HTTP 200.
- `model_path` should be `cloud_l1` for L0/L1 retrieved content.
- If data exists, citations should be present.
- If data is missing, answer should say insufficient data.

## 11. Run Focused Tests

Run these first:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_cache.py \
             services/query-service/tests/e2e/test_security_gaps.py -q
```

Run retrieval quality only after data readiness passes:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_retrieval_quality.py -q
```

Run answer quality only after data readiness passes:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e/test_answer_quality.py -q
```

Run full E2E only after the focused tests are understood:

```bash
GATEWAY_URL=http://127.0.0.1:8080 \
REDIS_URL=redis://127.0.0.1:6379 \
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e -q
```

## 12. What Not To Run By Default

Do not run reranker quality with `RERANKER_REQUIRED=true` unless you intentionally deploy reranker:

```bash
RERANKER_REQUIRED=true ...
```

The current `local` profile has reranker disabled.

## 13. Save Result

```text
Profile: local
OpenAI model: gpt-5.4-mini
Embedding model: text-embedding-3-small
Helm revision:
Data readiness:
Manual query result:
Focused tests:
Full E2E:
Notes:
```
