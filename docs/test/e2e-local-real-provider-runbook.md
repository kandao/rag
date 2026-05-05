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

Check Elasticsearch persistence:

```bash
kubectl get pvc -n retrieval-deps elasticsearch-data
```

Expected:

- The PVC exists.
- `STATUS` is `Bound`.

The local profile stores Elasticsearch data on this PVC at
`/usr/share/elasticsearch/data`. Ingested documents should survive pod restarts and
normal Helm upgrades. They will not survive deleting the namespace, deleting the PVC, or
resetting the local Kubernetes storage backend.

If this is the first deploy after adding persistence, existing data from the old
non-persistent Elasticsearch pod is not copied into the PVC. Re-run local ingestion once
after the upgrade to seed the persistent volume.

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

The services in this profile are Kubernetes `ClusterIP` services. They are reachable
inside the cluster, but they are not automatically exposed on your laptop's
`127.0.0.1` interface.

Start the port-forward commands below before running local `curl` commands or E2E
tests. Keep each port-forward terminal open for as long as you need local access.
If the port-forward is not running, `curl http://127.0.0.1:8080/...` will fail with:

```text
curl: (7) Failed to connect to 127.0.0.1 port 8080
```

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

Quick checks from another terminal:

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/readyz
```

## 8. Health Check

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/readyz
```

Expected:

- Gateway health is ok.
- Gateway readiness says users are loaded.

## 9. Initialize Elasticsearch Indexes

Keep the Elasticsearch port-forward from section 7 running, then create the local
indexes and aliases:

```bash
PYTHONPATH=packages/rag-common:workers/ingestion \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m ingestion_local init-indexes \
  --es-url http://127.0.0.1:9200 \
  --mapping-dir deploy/charts/rag/files/mappings
```

Expected:

- The command prints alias/index statuses.
- Re-running the command is safe; existing aliases report `alias-exists`.

Verify aliases:

```bash
curl -sS http://127.0.0.1:9200/_cat/aliases?v
```

Expected aliases:

- `public_index`
- `internal_index`
- `confidential_index`
- `restricted_index`
- `audit-events-current`

## 10. Run Local Ingestion

First run a dry-run. This parses, scans, chunks, enriches, and binds ACL metadata without
calling OpenAI or Elasticsearch:

```bash
PYTHONPATH=packages/rag-common:workers/ingestion \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m ingestion_local ingest \
  --input deploy/charts/rag/files/fixtures/documents \
  --acl-policy deploy/charts/rag/files/fixtures/acl-policies.yaml \
  --embedding-provider openai \
  --language auto \
  --dry-run
```

Expected:

- The command prints one result per markdown fixture.
- `indexed` is `false`.
- `sensitivity_level` matches the fixture ACL policy.
- `chunk_count` is greater than zero.

For the real ingestion run, the CLI reads OpenAI embedding keys from your shell
environment. Do not paste these values into committed files or logs:

```bash
export EMBEDDING_API_KEY_L0L1=replace-with-openai-api-key
export EMBEDDING_API_KEY_L2L3=replace-with-openai-api-key
```

Run ingestion:

```bash
PYTHONPATH=packages/rag-common:workers/ingestion \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m ingestion_local ingest \
  --input deploy/charts/rag/files/fixtures/documents \
  --acl-policy deploy/charts/rag/files/fixtures/acl-policies.yaml \
  --es-url http://127.0.0.1:9200 \
  --embedding-provider openai \
  --language auto \
  --force-reindex
```

Expected:

- The command calls OpenAI embeddings.
- The command writes chunks to Elasticsearch.
- Each result has `indexed: true`.

For Chinese documents, use:

```bash
--language zh
```

For Japanese documents, especially documents with lots of kanji and little kana, use:

```bash
--language ja
```

## 11. Data Readiness Check

Check aliases:

```bash
curl -sS http://127.0.0.1:9200/_cat/aliases?v
```

Check indexed chunk count:

```bash
curl -sS 'http://127.0.0.1:9200/public_index,internal_index,confidential_index,restricted_index/_count?pretty'
```

Inspect sample chunks:

```bash
curl -sS 'http://127.0.0.1:9200/public_index,internal_index,confidential_index,restricted_index/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"size":5,"query":{"match_all":{}},"_source":["chunk_id","path","sensitivity_level","acl_tokens","acl_key"]}'
```

Expected:

- Search result `hits.total.value` should be greater than zero.
- Sample chunks should include `path`, `acl_tokens`, `acl_key`, and `sensitivity_level`.

If data is missing, do not run quality gates yet. Record the run as blocked by data readiness.

## 12. Manual Real-Provider Query

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

## 13. Run Focused Tests

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

## 14. What Not To Run By Default

Do not run reranker quality with `RERANKER_REQUIRED=true` unless you intentionally deploy reranker:

```bash
RERANKER_REQUIRED=true ...
```

The current `local` profile has reranker disabled.

## 15. Save Result

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
