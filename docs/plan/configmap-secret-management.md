# ConfigMap and Secret Management

Helm is the source of truth for runtime configuration.

## Environments

| Environment | Values file | Secret handling | Purpose |
|---|---|---|---|
| `local_test` | `deploy/charts/rag/values-local_test.yaml` | ignored `values-local_test.secret.yaml` | Deterministic E2E stack with `llm-stub` and mock users |
| `local` | `deploy/charts/rag/values-local.yaml` | ignored `values-local.secret.yaml` | Developer stack using real provider endpoints and keys |
| `test` | `deploy/charts/rag/values-test.yaml` | externally managed K8s Secrets | Shared pre-prod validation |
| `prod` | `deploy/charts/rag/values-prod.yaml` | externally managed K8s Secrets | Production |

## Local usage

```bash
cp deploy/charts/rag/values-local_test.secret.example.yaml deploy/charts/rag/values-local_test.secret.yaml

helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local_test.yaml \
  -f deploy/charts/rag/values-local_test.secret.yaml
```

For real local provider calls:

```bash
cp deploy/charts/rag/values-local.secret.example.yaml deploy/charts/rag/values-local.secret.yaml

helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local.yaml \
  -f deploy/charts/rag/values-local.secret.yaml
```

The real `*.secret.yaml` files are ignored by Git. Commit only `*.example.yaml`.

## Secret boundaries

ConfigMaps contain non-sensitive runtime settings: hosts, URLs, model names, provider names, TTLs, guard thresholds, topic names, and mounted YAML config files.

Secrets contain credentials and keys: claims signing keys, model provider API keys, embedding provider API keys, Elasticsearch credentials, and audit Elasticsearch credentials.
