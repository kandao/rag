# E2E Troubleshooting

Use this when an E2E run fails.

## Kubernetes Is Unreachable

Symptom:

```text
The connection to the server 127.0.0.1:26443 was refused
```

Check:

```bash
kubectl config current-context
kubectl get nodes
```

If using OrbStack:

```bash
orbctl status
orbctl start
```

Then retry:

```bash
kubectl get nodes
```

## Docker Build Uses Wrong Context

Symptom:

```text
"/services/query-service": not found
```

Cause: the Dockerfile expects the repository root as build context.

Use:

```bash
docker build -t rag/query-service:dev -f services/query-service/Dockerfile .
```

Do not use:

```bash
docker build -t rag/query-service:dev services/query-service
```

## Pod Is Not Running

List pods:

```bash
kubectl get pods -A
```

Describe the failed pod:

```bash
kubectl describe pod POD_NAME -n NAMESPACE
```

Read logs:

```bash
kubectl logs POD_NAME -n NAMESPACE
```

For query-service:

```bash
kubectl logs deploy/query-service -n query
```

## Reranker Pod Is Pending

The reranker image is large and requests significant memory. For the OpenAI-backed `local` profile, reranker is not required.

Expected for current `local`:

```bash
kubectl get pods -n reranker
```

Output can be:

```text
No resources found in reranker namespace.
```

If you intentionally enable reranker, make sure the local cluster has enough CPU and memory.

## Gateway Health Fails

Port-forward:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Check:

```bash
curl -sS http://127.0.0.1:8080/healthz
curl -sS http://127.0.0.1:8080/readyz
```

If readiness says no users loaded, check:

```bash
kubectl get configmap mock-users-config -n api-gateway -o yaml
kubectl logs deploy/gateway-stub -n api-gateway
```

## Query Returns 401

Use one of the configured mock tokens:

- `test-token-l0`
- `test-token-l1`
- `test-token-l1-b`
- `test-token-l2`
- `test-token-l3`
- `test-token-attacker`
- `test-token-no-acl`

Example:

```bash
curl -sS http://127.0.0.1:8080/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-token-l1' \
  -d '{"query":"What are the engineering guidelines for 2024?"}'
```

## Query Returns Insufficient Data

This usually means retrieval found no authorized chunks.

Check indexes:

```bash
kubectl -n retrieval-deps port-forward svc/elasticsearch 9200:9200
curl -sS http://127.0.0.1:9200/_cat/indices?v
curl -sS http://127.0.0.1:9200/_cat/aliases?v
```

Check expected chunks:

```bash
curl -sS 'http://127.0.0.1:9200/*/_search?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"ids":{"values":["eng-guide-2024-001","hr-policy-2024-001","product-overview-001"]}}}'
```

If no chunks are found, the runtime is up but data is not ready.

## OpenAI Calls Fail

Check query-service config:

```bash
kubectl get configmap query-service-config -n query \
  -o jsonpath='{.data.MODEL_PROVIDER_L0L1} {.data.MODEL_ENDPOINT_L0L1} {.data.MODEL_NAME_L0L1}'
```

Expected:

```text
openai https://api.openai.com/v1/chat/completions gpt-5.4-mini
```

Check that the Kubernetes secret has keys without printing them:

```bash
kubectl get secret query-service-secrets -n query
```

Check query-service logs:

```bash
kubectl logs deploy/query-service -n query --tail=100
```

Do not paste real API keys into chat, docs, or git.

## Redis Cache Test Fails

Port-forward Redis:

```bash
kubectl -n retrieval-deps port-forward svc/redis 6379:6379
```

Check Redis responds:

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
```

Expected:

```text
PONG
```

If Redis is unavailable, skip cache tests and fix Redis first.

## Cleanup

Stop port-forward terminals with `Ctrl-C`.

To remove the Helm release:

```bash
helm uninstall rag-system
```

To inspect ignored secrets:

```bash
git status --ignored --short deploy/charts/rag/values-local.secret.yaml
git status --ignored --short deploy/charts/rag/values-local_test.secret.yaml
```
