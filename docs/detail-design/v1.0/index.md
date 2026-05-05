# DDD v1.0 Index
​
## Purpose
​
This directory contains the **Detail Design Documents** for `v1.0`. Each sub-document corresponds to one independently implementable component or service. The DDD layer bridges the HLD architecture decisions into concrete implementation contracts: API schemas, algorithm pseudocode, configuration parameters, Kubernetes resource specs, and per-component test cases.
​
**Reading order**: read `00-conventions-contracts.md` first to understand shared data types and conventions, then jump to the component your team owns.
​
---
​
## Parallel Development Workstreams
​
The documents are organized to maximize parallel development. The dependency layers below define the order teams must respect — a team in Layer N may start as soon as its Layer N-1 dependencies are interface-stable (contracts agreed, not necessarily implemented).
​
```
Layer 0 — Foundational (no runtime dependencies, start immediately)
  11-elasticsearch-infra.md        ES cluster init, index mapping, alias setup
  12-redis-cache.md                Redis cluster, key schema, TTL policy
  13-platform-kubernetes.md        K8s namespaces, RBAC, network policies, secrets
  14-local-dev-environment.md      kind/k3d setup, mock IdP, stub services
  00-conventions-contracts.md      Shared types, API conventions, error codes
​
Layer 1 — Core Services (depends only on Layer 0 contracts)
  01-api-gateway.md                Auth validation, rate limiting, claims forwarding
  02-claims-acl-adapter.md         Claims Normalizer + Claims-to-ACL Adapter + Redis auth cache
  03-query-guard.md                Injection / enumeration detection
  07-reranker-service.md           Standalone GPU reranker service
  09-audit-emitter.md              Audit Emitter + Audit Elasticsearch
​
Layer 2 — Query Pipeline (depends on ACL contracts from Layer 1)
  04-query-understanding-routing.md  Query parsing, intent, routing
  05-secure-query-builder.md         ES query assembly + ACL filter injection
  06-retrieval-orchestrator.md       Multi-index merge, cache key, result cache
  10-ingestion-pipeline.md           Full ingestion chain (Connector → Indexer)
​
Layer 3 — Completion (depends on retrieval outputs)
  08-model-gateway.md              Model path selection, context minimization, answer generation
​
Reference (no dependencies, read any time)
  15-architecture-overview.md      Full component map, query flow, ingestion flow, security boundaries
  16-project-structure.md          File inventory, message queue decision, repo layout
  17-current-local-architecture.md Current implemented local architecture and delta from the overview
```
​
---
​
## Document List
​
| # | Document | Component(s) | Team |
|---|----------|-------------|------|
| 00 | `00-conventions-contracts.md` | Shared types, error codes, API conventions | All |
| 01 | `01-api-gateway.md` | API Gateway | Platform / Infra |
| 02 | `02-claims-acl-adapter.md` | Claims Normalizer, Claims-to-ACL Adapter | Auth team |
| 03 | `03-query-guard.md` | Query Guard | Security team |
| 04 | `04-query-understanding-routing.md` | Query Understanding, Query Routing | Query team |
| 05 | `05-secure-query-builder.md` | SecureQueryBuilder | Query team |
| 06 | `06-retrieval-orchestrator.md` | Retrieval Orchestrator, Redis result cache | Query team |
| 07 | `07-reranker-service.md` | Reranker Service (GPU) | ML / Infra |
| 08 | `08-model-gateway.md` | Model Gateway Client | LLM team |
| 09 | `09-audit-emitter.md` | Audit Emitter, Audit Elasticsearch | Platform / Security |
| 10 | `10-ingestion-pipeline.md` | Full ingestion pipeline | Ingestion team |
| 11 | `11-elasticsearch-infra.md` | Elasticsearch cluster, index init | Infra / Data |
| 12 | `12-redis-cache.md` | Redis cluster, cache design | Infra / Backend |
| 13 | `13-platform-kubernetes.md` | Kubernetes topology, RBAC, network policies | Platform |
| 14 | `14-local-dev-environment.md` | Local dev setup, mock services | All (DX) |
| 15 | `15-architecture-overview.md` | Full architecture, request flow, data layout | All |
| 16 | `16-project-structure.md` | File inventory, message queue, repo layout | All |
| 17 | `17-current-local-architecture.md` | Current local architecture, deployed profile, gap analysis | All |
​
---
​
## Relationship to HLD
​
| DDD Document | Corresponding HLD Documents |
|-------------|---------------------------|
| `00-conventions-contracts.md` | `00-system-context.md` §5–6, `01-system-architecture.md` §7 |
| `01-api-gateway.md` | `01-system-architecture.md` §3, `09-security-compliance.md` §4 |
| `02-claims-acl-adapter.md` | `02-authorization-bootstrap.md`, `03-acl-scalability.md` |
| `03-query-guard.md` | `04-query-serving.md` §3, `09-security-compliance.md` §4 |
| `04-query-understanding-routing.md` | `04-query-serving.md` §3–4, `05-query-pipeline-patterns.md` §2–4 |
| `05-secure-query-builder.md` | `02-authorization-bootstrap.md` §6–7, `08-elasticsearch-schema.md` §5 |
| `06-retrieval-orchestrator.md` | `04-query-serving.md` §6, `09`, `05-query-pipeline-patterns.md` §7 |
| `07-reranker-service.md` | `06-reranker-architecture.md` |
| `08-model-gateway.md` | `04-query-serving.md` §8–10, `05-query-pipeline-patterns.md` §8–9 |
| `09-audit-emitter.md` | `09-security-compliance.md` §6, `01-system-architecture.md` §3 |
| `10-ingestion-pipeline.md` | `07-ingestion-indexing.md` |
| `11-elasticsearch-infra.md` | `08-elasticsearch-schema.md` |
| `12-redis-cache.md` | `03-acl-scalability.md` §8 |
| `13-platform-kubernetes.md` | `10-platform-operations.md` |
| `14-local-dev-environment.md` | `10-platform-operations.md` §4 |
​
---
​
## Interface Stability Policy
​
An interface is **stable** when its request/response schema and error codes are agreed upon and documented in `00-conventions-contracts.md` or the relevant DDD document. Teams consuming an upstream interface may begin implementation against a stub/mock as soon as the upstream interface is stable. Schema changes after stability declaration require a RFC with all downstream teams.
​
## v1.1 Reserved Points
​
All DDD documents mark extension points for `v1.1` (canonical principal, group sync, token registry, revocation fence) with a `[v1.1]` tag. These sections describe the intended future shape without implementing it.
