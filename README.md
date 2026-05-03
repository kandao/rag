# RAG Local Development

This repository has two local Helm profiles:

- `local_test`: deterministic E2E stack using stubbed LLM responses.
- `local`: real-provider stack using local Elasticsearch/Redis plus external OpenAI LLM and embedding APIs.

## Prerequisites

- A local Kubernetes cluster, such as OrbStack, with the current `kubectl` context pointing at that cluster.
- Docker available to the same local cluster image store.
- Helm 3.
- Project Python at `/Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python` for the documented test commands.

## Build Local Images

For the OpenAI-backed `local` profile, build the app images that are deployed by that profile:

```bash
docker build -t rag/query-service:dev -f services/query-service/Dockerfile .
docker build -t rag/gateway-stub:dev -f services/gateway-stub/Dockerfile .
```

For `local_test`, also build the stub/support images used by that deterministic profile:

```bash
docker build -t rag/embedding-service:dev -f services/embedding-service/Dockerfile .
docker build -t rag/reranker-service:dev -f services/reranker-service/Dockerfile .
docker build -t rag/llm-stub:dev -f services/llm-stub/Dockerfile .
```

## Run `local_test`

Use `local_test` for repeatable E2E runs that do not call real external model APIs.

Create the ignored local secret file if it does not exist:

```bash
cp deploy/charts/rag/values-local_test.secret.example.yaml deploy/charts/rag/values-local_test.secret.yaml
```

Deploy:

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local_test.yaml \
  -f deploy/charts/rag/values-local_test.secret.yaml
```

Port-forward the gateway:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Run the deterministic E2E suite:

```bash
PYTHONPATH=packages/rag-common:services/query-service \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m pytest services/query-service/tests/e2e -q
```

## Run `local`

Use `local` when you want the deployed stack to call real OpenAI LLM and embedding APIs. Elasticsearch and Redis still run locally in Kubernetes.

Create the ignored local secret file if it does not exist:

```bash
cp deploy/charts/rag/values-local.secret.example.yaml deploy/charts/rag/values-local.secret.yaml
```

Fill these values in `deploy/charts/rag/values-local.secret.yaml`:

```yaml
MODEL_API_KEY_L0L1: replace-with-openai-api-key
MODEL_API_KEY_L2: replace-with-openai-api-key
MODEL_API_KEY_L3: replace-with-openai-api-key
EMBEDDING_API_KEY_L0L1: replace-with-openai-api-key
EMBEDDING_API_KEY_L2L3: replace-with-openai-api-key
```

For the local chart, Elasticsearch auth stays blank because local Elasticsearch runs with security disabled:

```yaml
ES_USERNAME: ""
ES_PASSWORD: ""
AUDIT_ES_USERNAME: ""
AUDIT_ES_PASSWORD: ""
```

Deploy:

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local.yaml \
  -f deploy/charts/rag/values-local.secret.yaml \
  --set global.createNamespaces=false
```

Port-forward the gateway:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Smoke test with the mock L1 user:

```bash
curl -sS http://127.0.0.1:8080/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-token-l1' \
  -d '{"query":"What does the product overview say?","top_k":5}'
```

## Secret Hygiene

The real secret override files are ignored by git:

```bash
git check-ignore -v deploy/charts/rag/values-local.secret.yaml
git check-ignore -v deploy/charts/rag/values-local_test.secret.yaml
```

Commit only `*.secret.example.yaml` files.
