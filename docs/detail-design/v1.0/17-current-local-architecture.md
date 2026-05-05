# DDD v1.0 17: Current Local Architecture

## 1. Scope

This document captures the current implemented architecture for the `local` real-provider
profile as observed on May 5, 2026. It is intentionally narrower than
`15-architecture-overview.md`; the goal is to describe what is actually deployed and
used for local E2E work today, then compare it with the original planned architecture.

Sources checked:

- `deploy/charts/rag/values.yaml`
- `deploy/charts/rag/values-local.yaml`
- `deploy/charts/rag/templates/*.yaml`
- `services/gateway-stub`
- `services/query-service`
- live local Kubernetes resources from the `rag-system` Helm release

## 2. Current Local Deployment

Live Helm release:

```text
release: rag-system
namespace: default
chart: rag-1.0.0
profile: local
```

Currently deployed application workloads:

| Namespace | Workload | Replicas | Purpose |
|---|---:|---:|---|
| `api-gateway` | `gateway-stub` | 1 | Local auth gateway stub; maps bearer test tokens to mock claims and proxies `/v1/*` to query-service. |
| `query` | `query-service` | 1 | Main RAG query pipeline. |
| `retrieval-deps` | `elasticsearch` | 1 | Local single-node Elasticsearch used for retrieval indexes and audit events. |
| `retrieval-deps` | `redis` | 1 | Local Redis used by query-service caches and guard state. |

Currently exposed Kubernetes services:

| Namespace | Service | Type | Port | Local access |
|---|---|---|---:|---|
| `api-gateway` | `gateway-stub` | `ClusterIP` | 8080 | Use `kubectl port-forward svc/gateway-stub 8080:8080`. |
| `query` | `query-service` | `ClusterIP` | 8080 | Internal cluster access from gateway. |
| `retrieval-deps` | `elasticsearch` | `ClusterIP` | 9200 | Use `kubectl port-forward svc/elasticsearch 9200:9200` for local checks/tests. |
| `retrieval-deps` | `redis` | `ClusterIP` | 6379 | Use `kubectl port-forward svc/redis 6379:6379` for cache tests. |

Namespaces such as `ingestion`, `reranker`, `kafka`, `monitoring`, and `cert-manager`
may exist in the local cluster, but they do not currently contain active RAG application
workloads for the `local` profile.

## 3. Current Runtime Component Map

```text
Local developer terminal
  |
  | curl / pytest against 127.0.0.1:8080
  | requires kubectl port-forward
  v
api-gateway/gateway-stub
  |
  | validates local bearer token against mock-users.yaml
  | strips client-supplied trusted-claims headers
  | signs X-Trusted-Claims + X-Claims-Sig
  v
query/query-service
  |
  +--> Redis at redis.retrieval-deps:6379
  |    - auth cache
  |    - guard rate/history state
  |    - retrieval result cache
  |    - embedding cache
  |
  +--> Elasticsearch at elasticsearch.retrieval-deps:9200
  |    - hybrid retrieval indexes
  |    - audit-events-current alias/index
  |
  +--> OpenAI API
       - chat completions for L0/L1, L2, and L3 model paths
       - embeddings for L0/L1 and L2/L3 query embeddings
```

Disabled local services:

| Component | Local state | Current replacement or behavior |
|---|---|---|
| Kong API Gateway | Not deployed. | `gateway-stub` provides local token-to-claims behavior and HMAC signed claims. |
| SSO / IdP / JWKS | Not deployed. | Mock users are loaded from chart fixture config. |
| Reranker service | Disabled. | Query-service falls back to retrieval order with `rerank_score=None`. |
| Embedding service | Disabled. | Query-service calls OpenAI embeddings directly. |
| LLM stub | Disabled. | Query-service calls OpenAI chat completions directly. |
| Ingestion worker | Disabled. | E2E depends on pre-existing or separately seeded Elasticsearch data. |
| Kafka ingestion topics | Not used by current local query path. | Ingestion pipeline is out of scope for current local profile. |
| Separate audit Elasticsearch | Not deployed. | Audit writes target the same local Elasticsearch instance. |
| Ingress / LoadBalancer | Not configured. | Local host access uses `kubectl port-forward`. |

## 4. Current Query Flow

The current local query path is:

```text
1. Client sends POST /v1/query to gateway-stub.
2. gateway-stub validates the bearer token against mock users.
3. gateway-stub signs normalized mock claims and proxies to query-service.
4. query-service validates input length.
5. query-service verifies and normalizes X-Trusted-Claims / X-Claims-Sig.
6. query-service checks Redis auth cache or derives UserContext.
7. query-service runs guard checks for rate limit, injection, and enumeration.
8. query-service parses query intent and decomposes comparison-style queries.
9. query-service routes to target Elasticsearch indexes based on user context.
10. SecureQueryBuilder builds BM25 + optional kNN queries with ACL filters.
11. Retrieval orchestrator fans out to Elasticsearch, normalizes, deduplicates,
    caps, and caches results.
12. Reranker client returns retrieval-order fallback because reranker is disabled.
13. Model gateway minimizes retrieved context and calls OpenAI.
14. Audit emitter writes a query audit event to local Elasticsearch.
15. query-service returns answer, citations, retrieved chunk IDs, model path, and latency.
```

Important local behavior:

- If no candidates are retrieved, query-service returns `"Insufficient data to answer the query."`
  with `model_path="none"`.
- If OpenAI embeddings fail, query embedding falls back to BM25-only retrieval.
- If Elasticsearch search fails for L2/L3 user context, retrieval fails closed.
- Audit fail-closed starts at clearance level 2, but local audit writes use the same
  Elasticsearch service as retrieval.

## 5. Current Local Configuration Highlights

`values-local.yaml` changes the base chart in these important ways:

| Area | Base/prod plan | Current local setting |
|---|---|---|
| Environment | `prod` | `local` |
| Image pull | `IfNotPresent` | `Never`, using locally built `:dev` images |
| Gateway | Kong planned; gateway-stub disabled in base | `gateway-stub` enabled |
| Query replicas | 2 in base | 1 |
| Elasticsearch | Disabled in base | Enabled local single-node service |
| Redis | Disabled in base | Enabled local service |
| Reranker | Enabled in base | Disabled |
| Embedding service | Enabled in base | Disabled |
| L0/L1 model | Enterprise gateway endpoint | OpenAI API directly |
| L2/L3 model | Private/restricted LLM endpoints | OpenAI API directly |
| L0/L1 embedding | Enterprise gateway endpoint | OpenAI API directly |
| L2/L3 embedding | Private embedding service | OpenAI API directly |
| Query expansion | Disabled | Disabled |
| LLM parser | Disabled | Disabled |
| Answer verification | Disabled | Disabled |
| Guard rate limit | 20 RPM in base | 1000 RPM for local testing |

## 6. Difference From `15-architecture-overview.md`

| Planned architecture item | Current local reality | Notes |
|---|---|---|
| Kong API Gateway with OIDC/JWT validation, rate limiting, and JWKS integration | Replaced by `gateway-stub` | Good local substitute for signed trusted claims, but not a Kong/OIDC validation test. |
| External SSO / IdP | Not present | Test tokens map to fixture users. |
| Client reaches gateway over HTTPS | Local HTTP via port-forward | Services are `ClusterIP`; no Ingress, NodePort, or LoadBalancer is used. |
| Query service has full internal pipeline | Mostly present | Claims, guard, routing, secure query build, retrieval, model gateway, and audit code paths exist. |
| Reranker service is called after retrieval | Disabled | Reranker client returns fallback order locally. |
| Separate private model path for L2/L3 | Not present locally | L2/L3 also use OpenAI in local profile. This is acceptable for local real-provider testing but differs from the security architecture. |
| Separate private embedding path for L2/L3 | Not present locally | L2/L3 embeddings also use OpenAI with configured dimensions. |
| Separate audit Elasticsearch | Not present locally | Audit events target the same local Elasticsearch service. |
| Kafka-backed ingestion pipeline | Not deployed locally | Current local query tests require data to already exist in Elasticsearch. |
| Source connectors, parser, risk scanner, chunker, enricher, ACL binder, embedding worker, indexer | Not active in local cluster | Implementation artifacts may exist, but no local ingestion workload is running in this profile. |
| Redis DB0-DB3 separation | Partially implemented conceptually | Query-service creates one Redis client with `db=0`; cache key prefixes distinguish concerns in code, while the DDD describes separate Redis DB numbers. |
| Network policies and production-style perimeter controls | Not the focus of current local state | Local profile prioritizes E2E behavior over full production isolation. |

## 7. What Is Good Enough For Current Local Focus

The current local architecture is sufficient for:

- exercising the gateway-stub to query-service request path;
- validating signed trusted claims behavior;
- testing ACL-aware query construction;
- running Redis-backed auth/result/embedding cache scenarios;
- running Elasticsearch retrieval quality checks when data is seeded;
- calling real OpenAI models and embeddings through the query-service pipeline;
- verifying basic audit event emission to Elasticsearch.

It is not sufficient for:

- validating Kong plugins, OIDC/JWT, JWKS, or production gateway behavior;
- validating private L2/L3 model isolation;
- validating reranker quality unless reranker is explicitly deployed and enabled;
- validating end-to-end ingestion from source systems through Kafka;
- validating cloud load balancers, ingress routing, TLS, or public service exposure;
- validating a separate audit Elasticsearch cluster.

## 8. Local Access Notes

Because local services are `ClusterIP`, local host access requires port-forwarding:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
kubectl -n retrieval-deps port-forward svc/elasticsearch 9200:9200
kubectl -n retrieval-deps port-forward svc/redis 6379:6379
```

Keep these commands running while local `curl` commands or E2E tests are using the
corresponding `127.0.0.1` ports.

## 9. Recommended Next Alignment Work

For the current local focus:

1. Keep the gateway, Elasticsearch, and Redis services as `ClusterIP`; use port-forwarding
   for local-only testing.
2. Document which Elasticsearch aliases/indexes must be seeded before retrieval and answer
   quality gates run.
3. Decide whether local L2/L3 real-provider tests are allowed to call OpenAI, or whether
   L2/L3 should be skipped until a private local/provider path exists.
4. If reranker quality becomes a local gate, enable `services.rerankerService.enabled=true`
   and set `RERANKER_ENABLED=true` in query-service.
5. If ingestion becomes part of local E2E, add a separate local ingestion profile that deploys
   the ingestion worker and its queue dependencies intentionally.
