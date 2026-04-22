# DDD v1.0 15: Architecture Overview
​
## 1. System Component Map
​
```
╔══════════════════════════════════════════════════════════════════════════════════╗
║  EXTERNAL                                                                        ║
║  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────────────────────┐  ║
║  │ Client Apps  │   │  SSO / IdP      │   │  Source Systems                  │  ║
║  │ (web, cli,   │   │  (OIDC/JWT)     │   │  (Confluence, SharePoint, FS)    │  ║
║  │  service)    │   └────────┬────────┘   └────────────────┬─────────────────┘  ║
║  └──────┬───────┘            │ JWKS                        │ pull / webhook      ║
╚═════════╪════════════════════╪═════════════════════════════╪════════════════════╝
          │ HTTPS              │                             │
          ▼                    ▼                             │
╔══════════════════════════════════════════════════════════════════════════════════╗
║  NAMESPACE: api-gateway                                                          ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐ ║
║  │                        Kong API Gateway                                     │ ║
║  │  • OIDC/JWT validation (verifies against IdP JWKS)                         │ ║
║  │  • Rate limiting (Redis plugin)                                             │ ║
║  │  • Extracts sub → user_id; packages claims JSON                            │ ║
║  │  • Signs X-Trusted-Claims + X-Claims-Sig (HMAC-SHA256)                    │ ║
║  │  • Forwards to Query Service on port 8080                                  │ ║
║  └────────────────────────────────┬────────────────────────────────────────────┘ ║
╚═══════════════════════════════════╪════════════════════════════════════════════════╝
                                    │ X-Trusted-Claims / X-Claims-Sig
                                    ▼
╔══════════════════════════════════════════════════════════════════════════════════╗
║  NAMESPACE: query                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐ ║
║  │                         Query Service                                       │ ║
║  │                                                                             │ ║
║  │  ┌───────────────────────┐     ┌────────────────────────────────────────┐  │ ║
║  │  │  1. Claims/ACL        │     │  2. Query Guard                        │  │ ║
║  │  │     Adapter           │────▶│  • Rate limit (Redis DB1)              │  │ ║
║  │  │  • Verify HMAC sig    │     │  • Injection pattern detection         │  │ ║
║  │  │  • Expand groups      │     │  • Enumeration detection (Jaccard)     │  │ ║
║  │  │  • Compress tokens    │     │  • Fail-closed for HIGH signals        │  │ ║
║  │  │  • Derive acl_key     │     └──────────────────┬─────────────────────┘  │ ║
║  │  │  • Cache (Redis DB0)  │                        │                         │ ║
║  │  └───────────────────────┘                        ▼                         │ ║
║  │                                  ┌────────────────────────────────────────┐  │ ║
║  │                                  │  3. Query Understanding & Routing      │  │ ║
║  │                                  │  • Parse intent, keywords, doc_type    │  │ ║
║  │                                  │  • Rule-based query expansion (all     │  │ ║
║  │                                  │    tiers); LLM expansion (L0/L1 only) │  │ ║
║  │                                  │  • Route to target indexes             │  │ ║
║  │                                  └──────────────────┬─────────────────────┘  │ ║
║  │                                                     │                         │ ║
║  │                                                     ▼                         │ ║
║  │                                  ┌────────────────────────────────────────┐  │ ║
║  │                                  │  4. SecureQueryBuilder                 │  │ ║
║  │                                  │  • Embed query (cache: Redis DB3)      │  │ ║
║  │                                  │  • Build BM25 + kNN hybrid query       │  │ ║
║  │                                  │  • ACL filter in BOTH query.bool.      │  │ ║
║  │                                  │    filter AND knn.filter               │  │ ║
║  │                                  │  • Sole query assembler (no bypasses)  │  │ ║
║  │                                  └──────────────────┬─────────────────────┘  │ ║
║  │                                                     │                         │ ║
║  │                                                     ▼                         │ ║
║  │                                  ┌────────────────────────────────────────┐  │ ║
║  │                                  │  5. Retrieval Orchestrator             │  │ ║
║  │                                  │  • Result cache (Redis DB2)            │  │ ║
║  │                                  │  • Fan-out to ES indexes               │  │ ║
║  │                                  │  • Post-filter ACL re-validation       │  │ ║
║  │                                  │  • Call Reranker Service               │  │ ║
║  │                                  │  • Fail-closed for L2/L3 on ES error   │  │ ║
║  │                                  └──────────────────┬─────────────────────┘  │ ║
║  │                                                     │                         │ ║
║  │                                                     ▼                         │ ║
║  │                                  ┌────────────────────────────────────────┐  │ ║
║  │                                  │  6. Model Gateway                      │  │ ║
║  │                                  │  • Minimize context (top-N chunks)     │  │ ║
║  │                                  │  • Route: Enterprise GW (L0/L1) or     │  │ ║
║  │                                  │    Private deployment (L2/L3)          │  │ ║
║  │                                  │  • Prompt assembly + LLM call          │  │ ║
║  │                                  │  • Answer verification (L1+)           │  │ ║
║  │                                  └──────────────────┬─────────────────────┘  │ ║
║  │                                                     │                         │ ║
║  │                                                     ▼                         │ ║
║  │                                  ┌────────────────────────────────────────┐  │ ║
║  │                                  │  7. Audit Emitter                      │  │ ║
║  │                                  │  • Emit AuditEvent to Audit ES         │  │ ║
║  │                                  │  • L2/L3: gate response until write    │  │ ║
║  │                                  │    confirmed (fail-closed)             │  │ ║
║  │                                  │  • L0/L1: async (non-blocking)         │  │ ║
║  │                                  └────────────────────────────────────────┘  │ ║
║  └─────────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════════╝
        │ Rerank               │ ES kNN+BM25           │ LLM API           │ Audit
        ▼                      ▼                        ▼                   ▼
╔══════════════╗  ╔════════════════════════╗  ╔══════════════════╗  ╔══════════════╗
║ NS: reranker ║  ║ NS: retrieval-deps     ║  ║ Enterprise       ║  ║ Audit ES     ║
║ ┌──────────┐ ║  ║ ┌────────────────────┐ ║  ║ Gateway /        ║  ║ (retrieval-  ║
║ │ Reranker │ ║  ║ │  Elasticsearch     │ ║  ║ Private LLM      ║  ║  deps)       ║
║ │ Service  │ ║  ║ │  (4 indexes)       │ ║  ║ Deployment       ║  ╚══════════════╝
║ │ (GPU)    │ ║  ║ │  public_index      │ ║  ╚══════════════════╝
║ │ms-marco/ │ ║  ║ │  internal_index    │ ║
║ │bge-large │ ║  ║ │  confidential_idx  │ ║
║ └──────────┘ ║  ║ │  restricted_index  │ ║
╚══════════════╝  ║ └────────────────────┘ ║
                  ║ ┌────────────────────┐ ║
                  ║ │  Redis (4 DBs)     │ ║
                  ║ │  DB0: ACL cache    │ ║
                  ║ │  DB1: Guard state  │ ║
                  ║ │  DB2: Result cache │ ║
                  ║ │  DB3: Embed cache  │ ║
                  ║ └────────────────────┘ ║
                  ╚════════════════════════╝
​
╔══════════════════════════════════════════════════════════════════════════════════╗
║  NAMESPACE: ingestion                                                            ║
║                                                                                  ║
║  Source ──▶ Connector ──▶ Parser ──▶ Risk Scanner ──▶ Chunker ──▶ Enricher      ║
║                                            │                                     ║
║                                            ▼ (quarantine)                        ║
║                                       Quarantine Queue                           ║
║                                                                                  ║
║  Enricher ──▶ ACL Binder ──▶ Embedding Worker ──▶ Indexer ──▶ Elasticsearch     ║
║                                                                                  ║
║  (Kafka topics — ingestion.raw → .parsed → .scanned → .chunked                  ║
║                  → .enriched → .acl_bound → .embedded; DLQ: ingestion.dlq)      ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```
​
---
​
## 2. Query Request Flow (Numbered Steps)
​
```
Client
  │
  │ 1. HTTPS POST /v1/query
  │    Authorization: Bearer <jwt>
  ▼
Kong API Gateway
  │ 2. Validate JWT against IdP JWKS
  │ 3. Extract user_id, groups, role, clearance_level
  │ 4. Sign X-Trusted-Claims + X-Claims-Sig
  ▼
Claims/ACL Adapter
  │ 5. Verify HMAC signature
  │ 6. Check Redis DB0 (claims_hash → UserContext)
  │    Cache HIT → skip 7–10; Cache MISS → continue
  │ 7. Expand groups (add parents; add clearance-level tokens)
  │ 8. Compress to ACL tokens (≤30; reject if not compressible)
  │ 9. Compute acl_key = SHA-256(sorted_tokens|schema_version|acl_version)
  │ 10. Cache UserContext in Redis DB0 (TTL 300s)
  ▼
Query Guard
  │ 11. Increment rate limit counter in Redis DB1; reject if exceeded
  │ 12. Match query against injection patterns → BLOCK if HIGH signal
  │ 13. Compute Jaccard similarity against query history → BLOCK if enumeration
  │ 14. Push query to history list (Redis DB1, last 10)
  ▼
Query Understanding & Routing
  │ 15. Parse keywords, intent, doc_type, time_range, risk_signal
  │ 16. Rule-based query expansion (all tiers)
  │     LLM expansion (L0/L1 only, if enabled)
  │ 17. Select target ES indexes by clearance_level + intent
  ▼
SecureQueryBuilder
  │ 18. Check Redis DB3 for cached embedding (emb:{model_id}:{text_hash})
  │     Cache MISS: call embedding API (1536d for L0/L1; 1024d for L2/L3)
  │ 19. Build query:
  │     • BM25 match on content field
  │     • kNN on vector field (same-dimension tiers only)
  │     • ACL filter: terms on acl_tokens IN query.bool.filter AND knn.filter
  ▼
Retrieval Orchestrator
  │ 20. Check Redis DB2 for result cache (result:{query_hash}:{acl_key})
  │     Cache HIT → skip 21–24
  │ 21. Execute ES hybrid query (BM25 + kNN)
  │ 22. Post-filter: verify each candidate's acl_tokens ∩ user's acl_tokens ≠ ∅
  │ 23. Call Reranker Service (candidate chunk_ids → rerank_scores)
  │ 24. Cache results in Redis DB2 (TTL 60s)
  │     On ES error: fail-closed for L2/L3; return empty for L0/L1
  ▼
Model Gateway
  │ 25. Select top-N candidates (pre-sorted by rerank_score)
  │ 26. Route: Enterprise Gateway (L0/L1) or Private LLM endpoint (L2/L3)
  │ 27. Assemble prompt with system instructions + context chunks
  │ 28. Call LLM; receive answer
  │ 29. Verify answer (L1+ when enabled): re-check claims against source chunks
  ▼
Audit Emitter
  │ 30. Emit AuditEvent {user_id, query, retrieved_chunk_ids, answer_hash, ts}
  │     L0/L1: async fire-and-forget; do not block response
  │     L2/L3: await write confirmation → gate response until confirmed
  │             If write fails → withhold response (fail-closed)
  ▼
Client
  │ 31. Return QueryResponse {answer, citations, request_id}
```
​
---
​
## 3. Ingestion Pipeline Flow
​
```
Source System
  │
  │ pull (cron) or push (webhook)
  ▼
Connector Worker                     raw IngestionJob
  │  source_uri, raw_content/bytes  ──────────────────▶ ingestion.raw topic
  ▼
Parser Worker                        parsed IngestionJob
  │  ParsedSection[] from PDF/HTML/  ─────────────────▶ ingestion.parsed topic
  │  Markdown/Wiki/DB export
  │  [Immutable Source: raw_content never modified]
  ▼
Risk Scanner Worker
  │  Sensitivity detection (SENS-001/002/003)
  │  Injection pattern scan (INJ-DOC-001/002)
  │  Format anomaly checks
  ├─ quarantine flag ──────────────────────────────────▶ ingestion.quarantine topic
  └─ continue ─────────────────────────────────────────▶ ingestion.scanned topic
  ▼
Chunker Worker                       chunked IngestionJob
  │  300–500 tokens, 75-token overlap ────────────────▶ ingestion.chunked topic
  │  tokenizer: tiktoken cl100k_base
  ▼
Metadata Enricher Worker             enriched IngestionJob
  │  doc_id (SHA-256 of URI), chunk_id, topic,  ──────▶ ingestion.enriched topic
  │  doc_type, year, source, created_at, updated_at
  ▼
ACL Binder Worker                    acl_bound IngestionJob
  │  Lookup ACLPolicy by source_pattern              ──▶ ingestion.acl_bound topic
  │  compress_groups_to_tokens() + role: tokens
  │  acl_key = SHA-256(sorted_tokens|schema|version)
  │  No ACL → chunk invisible (acl_tokens=[], deterministic empty hash)
  ▼
Embedding Worker                     embedded IngestionJob
  │  sensitivity_level ≤ 1 → Enterprise GW 1536d     ──▶ ingestion.embedded topic
  │  sensitivity_level ≥ 2 → Private endpoint 1024d
  ▼
Indexer Worker
  │  Route chunk to correct index:
  │  L0 → public_index  L1 → internal_index
  │  L2 → confidential_index  L3 → restricted_index
  │  Bulk write; update by doc_id; blue/green rebuild via alias
  ▼
Elasticsearch
```
​
---
​
## 4. Data Store Layout
​
```
Redis (retrieval-deps:6379)
├── DB 0  ACL Cache
│         Key:   acl:{claims_hash}
│         Value: {acl_tokens, acl_key, effective_clearance, ...}
│         TTL:   300s
│         Invalidation: version bump changes hash (natural expiry)
│
├── DB 1  Query Guard State
│         Keys:  guard_rl:{user_id}   → rate limit counter (TTL 60s)
│                guard_hist:{user_id} → List of last 10 queries (TTL 300s)
│
├── DB 2  Result Cache
│         Key:   result:{query_hash}:{acl_key}
│         Value: RetrievalCandidate[] JSON (~200KB max per entry)
│         TTL:   60s
│         Bound: acl_key ensures users cannot share results across ACL boundaries
│
└── DB 3  Embedding Cache
          Key:   emb:{model_id}:{text_hash}
          Value: float[] (1536 floats ≈ 12KB for L0/L1; 1024 floats ≈ 8KB for L2/L3)
          TTL:   3600s
          Note:  model_id required — prevents 1536d vector being served on 1024d path
​
​
Elasticsearch (retrieval-deps:9200)
├── public_index      (alias → public_index_v1)      dims=1536  L0
├── internal_index    (alias → internal_index_v1)    dims=1536  L1
├── confidential_index (alias → confidential_index_v1) dims=1024 L2
└── restricted_index  (alias → restricted_index_v1)  dims=1024  L3
​
Each index stores:
  doc_id, chunk_id, content (BM25), vector (kNN),
  path, page_number, section, topic, doc_type, year, source,
  allowed_groups, acl_tokens, acl_key, acl_version, sensitivity_level,
  created_at, updated_at
​
​
Audit Elasticsearch (retrieval-deps:9200, separate StatefulSet)
└── audit-events-{date}  (ILM: 30d rollover → warm → cold at 90d)
​
Each event stores:
  request_id, user_id, query_hash, query_text, retrieved_chunk_ids,
  answer_hash, effective_clearance, acl_key, target_indexes, ts, status
```
​
---
​
## 5. Security Boundaries and Fail-Closed Rules
​
```
┌─────────────────────────────────────────────────────────────────┐
│  FAIL-CLOSED POINTS                                             │
│                                                                 │
│  1. Claims/ACL Adapter                                          │
│     • Missing or invalid HMAC signature  → 401                 │
│     • ACL token count > 30 after compression  → 403            │
│     • Malformed claims JSON  → 401                              │
│                                                                 │
│  2. Query Guard                                                 │
│     • Rate limit exceeded  → 429                                │
│     • Injection signal HIGH  → 400 (blocked)                   │
│     • Enumeration detected  → 429                               │
│                                                                 │
│  3. Retrieval Orchestrator (L2/L3 ONLY)                        │
│     • ES infrastructure error  → 503 ERR_RETRIEVAL_FAILED      │
│     • Post-filter removes all candidates  → 200 empty          │
│                                                                 │
│  4. Audit Emitter (L2/L3 ONLY)                                 │
│     • Audit write failure  → response withheld  → 503          │
│     • Gate: triggered by user.effective_clearance ≥ 2          │
│       (not by sensitivity of chunks retrieved)                  │
│                                                                 │
│  5. ACL Filter in Elasticsearch                                 │
│     • Enforced in BOTH query.bool.filter AND knn.filter         │
│     • Only SecureQueryBuilder may assemble ES queries           │
│     • Empty acl_tokens → zero results (no bypass)              │
└─────────────────────────────────────────────────────────────────┘
​
┌─────────────────────────────────────────────────────────────────┐
│  SENSITIVITY TIERS                                              │
│                                                                 │
│  L0 (public)       clearance ≥ 0   public_index      1536d     │
│  L1 (internal)     clearance ≥ 1   internal_index    1536d     │
│  L2 (confidential) clearance ≥ 2   confidential_index 1024d   │
│  L3 (restricted)   clearance ≥ 3   restricted_index   1024d   │
│                                                                 │
│  A user with clearance=2 may query L0+L1+L2.                   │
│  kNN: L0+L1 together (same 1536d); L2+L3 together (same 1024d) │
│  Cross-tier (L0/L1 + L2/L3): BM25 only — no shared kNN.       │
│                                                                 │
│  L2/L3 paths:                                                   │
│  • Embedding via private endpoint (bge-m3, 1024d, multilingual)│
│  • LLM via private deployment (no external API calls)          │
│  • Fail-closed on any infrastructure error                      │
│  • Audit response gate active                                   │
└─────────────────────────────────────────────────────────────────┘
```
​
---
​
## 6. Kubernetes Namespace Topology
​
```
Ingress (nginx)
  └── rag-api.company.internal → api-gateway:443
        │
        │ (mTLS via Istio / Cilium between all namespaces)
        │
┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│  api-gateway   │───▶│  query         │───▶│  reranker      │
│  Kong          │    │  Query Service │    │  GPU pods      │
│  (HPA 1–10)   │    │  (HPA 1–10)   │    │  (static v1.0) │
└────────────────┘    └───────┬────────┘    └────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  retrieval-deps      │
                    │  ┌───────────────┐  │
                    │  │ Elasticsearch │  │
                    │  │ (3-node SS)   │  │
                    │  └───────────────┘  │
                    │  ┌───────────────┐  │
                    │  │ Audit ES      │  │
                    │  │ (1-node SS)   │  │
                    │  └───────────────┘  │
                    │  ┌───────────────┐  │
                    │  │ Redis         │  │
                    │  │ (single node) │  │
                    │  └───────────────┘  │
                    └─────────────────────┘
                              ▲
                              │
                    ┌─────────────────────┐
                    │  ingestion           │
                    │  8 worker deployments│
                    │  (Kafka consumers)   │
                    └─────────────────────┘
​
┌────────────────┐    ┌────────────────┐
│  cert-manager  │    │  monitoring    │
│  TLS issuance  │    │  Prometheus    │
│                │    │  Grafana       │
│                │    │  OTel Collector│
└────────────────┘    └────────────────┘
​
Network Policy: all namespaces default-deny; explicit allow rules per DDD §13.
Secrets: Kubernetes Secret objects only (never ConfigMaps/env literals).
RBAC: per-namespace ServiceAccounts; no ClusterRole for application pods.
```
​
---
​
## 7. Cross-Component Contract Summary
​
| Producer | Consumer | Transport | Contract |
|----------|----------|-----------|----------|
| Kong API Gateway | Query Service | HTTP (intra-mesh mTLS) | `X-Trusted-Claims` (base64 JSON) + `X-Claims-Sig` (HMAC-SHA256) |
| Claims/ACL Adapter | Query Guard, Routing, Builder | in-process | `UserContext` struct |
| Query Guard | Query Understanding | in-process | pass/reject + `ParsedQuery` |
| Query Understanding | SecureQueryBuilder | in-process | `ParsedQuery` + target index list |
| SecureQueryBuilder | Retrieval Orchestrator | in-process | ES DSL query object |
| Retrieval Orchestrator | Reranker Service | HTTP/gRPC | `chunk_id[]` → `{chunk_id, rerank_score}[]` |
| Retrieval Orchestrator | Model Gateway | in-process | `RetrievalCandidate[]` (sorted by rerank_score) |
| Model Gateway | Audit Emitter | in-process | `QueryResponse` + event fields |
| Ingestion Workers | Next stage worker | Kafka topic (aiokafka) | `IngestionJob` JSON; key=source_uri |
| Ingestion Indexer | Elasticsearch | Bulk API | `ElasticsearchChunk` documents |
| All services | Redis | Redis protocol | DB0–DB3 key contracts (see DDD §12) |
| Query Service | Audit Elasticsearch | ES bulk API | `AuditEvent` documents (see DDD §09) |
​
---
​
## 8. Open Decisions (v1.0)
​
| # | Area | Decision Needed |
|---|------|----------------|
| 1 | Claims transport | Finalize trusted-claims signing contract: HMAC key rotation, header name, encoding |
| 2 | Group hierarchy | Define canonical group taxonomy before token compression implementation |
| 3 | Model provider | Confirm enterprise gateway vs. direct API routing for L0/L1 LLM calls |
| 4 | Audit retention | Confirm ILM rollover (30d) and freeze (90d) with legal/compliance |
| 5 | Reranker v1.1 | HPA for GPU reranker pods (deferred to v1.1; static replicas in v1.0) |