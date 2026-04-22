# RAG v1.0 — Implementation Plan
​
## How to Use This Document
​
Each step is a **discrete agent task**. The agent reads **only the listed DDD sections**, produces the listed output files, then stops. Do not read unlisted files — the sections listed are sufficient.
​
- **Parallel steps** at the same phase number can run concurrently.
- **`DDD/XX §Y`** means read only section Y of that file.
- When a section is not specified, read the entire file (it is short).
​
---
​
## Dependency Graph
​
```
Phase 0 (scaffold)
  └─► Phase 1 (rag-common models + ACL utils)
        └─► Phase 3 (core service modules — all parallel)
        │     └─► Phase 4 (query pipeline — sequential within)
        │           └─► Phase 5 (model gateway)
        │                 └─► Phase 6 (query service assembly)
        └─► Phase 7 (ingestion workers — sequential within phase)
Phase 2 (infra — parallel with Phases 1–7, no code dependency)
Phase 8 (embedding service — parallel with Phase 7, after Phase 0)
Phase 9 (gateway stub — parallel with Phases 3–8, after Step 2.5)
Phase 10 (integration tests — after Phases 6 + 7 + 9)
```
​
---
​
## Phase 0 — Repository Scaffold
​
### Step 0.1 — Create repo directory structure
​
**DDD files to read**: `DDD/16 §1` (repo layout tree only)
​
**What to build**: Empty directory tree with placeholder `__init__.py` files and skeleton `pyproject.toml` for each package/service. No implementation code yet.
​
**Output files**:
```
rag/
├── packages/rag-common/pyproject.toml
├── packages/rag-common/rag_common/__init__.py
├── services/query-service/pyproject.toml
├── services/query-service/main.py              (skeleton only)
├── services/reranker-service/pyproject.toml
├── services/reranker-service/main.py           (skeleton only)
├── services/embedding-service/pyproject.toml
├── services/embedding-service/main.py          (skeleton only)
├── services/gateway-stub/pyproject.toml
├── services/gateway-stub/main.py               (skeleton only)
└── workers/ingestion/pyproject.toml
```
​
**Validation**: `find rag/ -name pyproject.toml` shows 6 results (rag-common, query-service, reranker-service, embedding-service, gateway-stub, ingestion workers).
​
---
​
## Phase 1 — Shared Package: `rag-common`
​
> Dependency: Phase 0 complete. **These two steps are sequential** (1.2 imports from 1.1).
​
### Step 1.1 — Pydantic models
​
**DDD files to read**:
- `DDD/00 §3` (all 7 data type interfaces: UserContext, QueryContext, RetrievalCandidate, RankedCandidate, AuditEvent, IngestionJob/Chunk/ParsedSection/ACLPolicy, ElasticsearchChunk)
- `DDD/00 §4` (sensitivity tier table — for model constants)
- `DDD/16 §3` (rag-common file tree — for exact filenames)
​
**What to build**: All Pydantic v2 `BaseModel` classes. Each `interface` in DDD/00 §3 maps 1-to-1 to a `BaseModel`. Use `model_validator` for cross-field invariants. Use `IngestionStage` as a `Literal` or `str` enum.
​
**Output files**:
```
packages/rag-common/rag_common/models/__init__.py
packages/rag-common/rag_common/models/user_context.py   # UserContext
packages/rag-common/rag_common/models/query.py          # QueryContext, QueryRequest, QueryResponse
packages/rag-common/rag_common/models/retrieval.py      # RetrievalCandidate, RankedCandidate
packages/rag-common/rag_common/models/ingestion.py      # IngestionJob, Chunk, ParsedSection, ACLPolicy
packages/rag-common/rag_common/models/audit.py          # AuditEvent
```
​
**Validation**: `from rag_common.models.ingestion import IngestionJob` imports without error.
​
---
​
### Step 1.2 — ACL utilities
​
**DDD files to read**:
- `DDD/00 §5` (token namespace convention: group:/role:/level: prefixes)
- `DDD/02 §4` (full token compression algorithm, acl_key hash formula, claims_hash formula)
- `DDD/16 §3` (rag-common/acl/ file tree)
​
**What to build**: Three pure utility modules. No FastAPI, no Redis, no network calls — pure functions only.
​
**Output files**:
```
packages/rag-common/rag_common/acl/__init__.py
packages/rag-common/rag_common/acl/token_compression.py  # compress_groups_to_tokens()
packages/rag-common/rag_common/acl/acl_key.py            # acl_key = SHA-256(sorted_tokens|schema_ver|acl_ver)
packages/rag-common/rag_common/acl/claims_hash.py        # claims_hash = SHA-256(groups|role|clearance|versions)
```
​
**Validation**: Unit test: `compress_groups_to_tokens(["eng:infra@company.com"])` → `["group:eng:infra"]` (domain suffix stripped; colon-separated path preserved as single token).
​
---
​
## Phase 2 — Infrastructure (parallel with Phases 1–7)
​
> No code dependency. All Phase 2 steps are parallel with each other and with all other phases.
​
### Step 2.1 — Elasticsearch index mappings and init Job
​
**DDD files to read**: `DDD/11` (entire file)
​
**What to build**: JSON mapping files for the 4 retrieval indexes. Kubernetes Job manifest that applies them at cluster bootstrap. The audit index schema is defined in `DDD/09 §7` and is created by Step 3.4.
​
**Output files**:
```
deploy/mappings/l0l1-mapping.json          # dims=1536, knn_vector field
deploy/mappings/l2l3-mapping.json          # dims=1024, knn_vector field
deploy/local/jobs/es-init.yaml             # K8s Job: curl -X PUT to create retrieval indexes + aliases
```
​
**Validation**: `curl localhost:9200/_cat/aliases` shows `public_index`, `internal_index`, `confidential_index`, `restricted_index` pointing to `*_v1` physical indexes.
​
---
​
### Step 2.2 — Redis configuration
​
**DDD files to read**:
- `DDD/12 §1` (DB layout summary table: DB0 auth cache, DB1 guard, DB2 result cache, DB3 embedding cache)
- `DDD/12 §2.1` (redis.conf settings: maxmemory, eviction policy, persistence)
​
**What to build**: Redis config file and document the 4-DB key schema.
​
**Output files**:
```
deploy/config/redis.conf          # maxmemory-policy allkeys-lru, persistence settings
```
​
**Validation**: `redis-cli CONFIG GET maxmemory-policy` returns `allkeys-lru`.
​
---
​
### Step 2.3 — Kafka cluster and topic CRDs
​
**DDD files to read**:
- `DDD/16 §2.2` (Strimzi KafkaCluster CRD YAML)
- `DDD/16 §2.3` (KafkaTopic CRD YAML with all 9 topics)
- `DDD/10 §3.2` (partition count, retention.ms values per topic)
​
**What to build**: Two Strimzi CRD YAML files.
​
**Output files**:
```
deploy/kafka/kafka-cluster.yaml    # KafkaCluster CRD: 3 brokers, 3 ZooKeeper
deploy/kafka/topics.yaml           # KafkaTopic CRDs: 9 topics (raw/parsed/scanned/quarantine/chunked/enriched/acl_bound/embedded/dlq)
```
​
**Validation**: `kubectl get kafkatopics -n kafka` shows all 9 topics.
​
---
​
### Step 2.4 — Kubernetes namespaces, RBAC, network policies
​
**DDD files to read**: `DDD/13` (entire file)
​
**What to build**: Namespace manifests, ServiceAccount + Role + RoleBinding YAML, NetworkPolicy YAML for each namespace boundary, and Helm chart skeleton. RBAC and NetworkPolicy manifests live in the Helm chart templates.
​
**Output files**:
```
deploy/local/namespaces.yaml
deploy/charts/rag/Chart.yaml
deploy/charts/rag/values.yaml
deploy/charts/rag/values-local.yaml
deploy/charts/rag/templates/rbac.yaml           # ServiceAccount, Role, RoleBinding per namespace
deploy/charts/rag/templates/network-policy.yaml # NetworkPolicy per namespace boundary
```
​
**Validation**: `kubectl get namespaces` shows `api-gateway`, `query`, `ingestion`, `reranker`, `retrieval-deps`, `kafka`.
​
---
​
### Step 2.5 — Local dev environment + test fixtures
​
**DDD files to read**: `DDD/14` (entire file)
​
**What to build**: kind/k3d setup script, mock user fixtures, ACL policy fixtures, seed documents.
​
**Output files**:
```
deploy/local/jobs/seed-data.yaml
test/fixtures/mock-users.yaml           # 6 test users (L0–L3, attacker, no-acl)
test/fixtures/acl-policies.yaml
test/fixtures/documents/public/finance_report_2024.pdf     (placeholder)
test/fixtures/documents/public/product_overview.md
test/fixtures/documents/internal/engineering_guidelines_2024.md
test/fixtures/documents/internal/hr_policy_2024.md
test/fixtures/documents/confidential/m_and_a_memo_2024.pdf (placeholder)
test/fixtures/documents/confidential/legal_contracts_q1.md
test/fixtures/documents/restricted/board_minutes_2024.pdf   (placeholder)
```
​
**Validation**: `python -m pytest test/ -k "fixture"` passes.
​
---
​
## Phase 3 — Core Service Modules (all parallel, after Phase 1)
​
> Dependency: Phase 1 complete. All steps in Phase 3 are independent of each other.
​
### Step 3.1 — Claims Normalizer + ACL Adapter + Redis auth cache
​
**DDD files to read**:
- `DDD/02` (entire file — all 3 components are in this single doc)
- `DDD/00 §3.1` (UserContext fields to populate)
- `DDD/12 §3` (DB0 key schema: `acl:{claims_hash}`, TTL=300s)
​
**What to build**: 3 internal modules inside `query-service`. The Normalizer verifies HMAC; the Adapter computes `acl_tokens` + `acl_key`; the auth cache reads/writes Redis DB0.
​
**Output files**:
```
services/query-service/internal/claims/__init__.py
services/query-service/internal/claims/normalizer.py    # verify HMAC; parse X-Trusted-Claims
services/query-service/internal/claims/acl_adapter.py  # groups → acl_tokens; compute acl_key
services/query-service/internal/cache/__init__.py
services/query-service/internal/cache/auth_cache.py    # Redis DB0: get/set UserContext by claims_hash
services/query-service/tests/conftest.py               # fixtures: mock Redis, mock ES, sample UserContext
services/query-service/tests/unit/test_normalizer.py
services/query-service/tests/unit/test_acl_adapter.py
services/query-service/tests/unit/test_auth_cache.py
deploy/config/acl-hierarchy-config.yaml               # group hierarchy for token compression (mounted as ConfigMap)
```
​
**Validation**: Test cases from `DDD/02 §8` all pass.
​
---
​
### Step 3.2 — Query Guard
​
**DDD files to read**:
- `DDD/03` (entire file)
- `DDD/00 §2.5` (error codes: ERR_GUARD_INJECTION_DETECTED, ERR_GUARD_ENUMERATION_DETECTED, ERR_GUARD_RATE_LIMIT)
- `DDD/12 §4.1-§4.2` (DB1 key schema: `guard_rl:{user_id}`, `guard_hist:{user_id}`, TTLs)
​
**What to build**: 3 detection modules + 1 orchestrator inside `query-service/internal/guard/`.
​
**Output files**:
```
services/query-service/internal/guard/__init__.py
services/query-service/internal/guard/guard.py                  # orchestrates 3 checks
services/query-service/internal/guard/injection_detector.py     # regex patterns; HIGH/MEDIUM signals
services/query-service/internal/guard/enumeration_detector.py   # Jaccard similarity vs history
services/query-service/internal/guard/rate_limiter.py           # Redis DB1: INCR + EXPIRE sliding window
services/query-service/tests/unit/test_injection_detector.py
services/query-service/tests/unit/test_enumeration_detector.py
services/query-service/tests/unit/test_rate_limiter.py
deploy/config/injection-patterns.yaml                          # regex patterns for injection detection (mounted as ConfigMap)
```
​
**Validation**: Test cases from `DDD/03 §10` all pass (injection, enumeration, rate limit).
​
---
​
### Step 3.3 — Reranker Service
​
**DDD files to read**:
- `DDD/07` (entire file)
- `DDD/00 §1.1` (tech stack: sentence-transformers, FastAPI, Uvicorn)
- `DDD/00 §3.4` (RankedCandidate schema)
- `DDD/16 §5` (reranker-service file tree)
​
**What to build**: Standalone FastAPI service with GPU CrossEncoder inference.
​
**Output files**:
```
services/reranker-service/main.py         # FastAPI app; POST /v1/rerank; GET /healthz /readyz /metrics
services/reranker-service/config.py       # MODEL_PATH, BATCH_SIZE, MAX_SEQUENCE_LENGTH
services/reranker-service/schemas.py      # RerankRequest, RerankResponse
services/reranker-service/reranker.py     # CrossEncoder batch scoring
services/reranker-service/Dockerfile
services/reranker-service/tests/conftest.py
services/reranker-service/tests/unit/test_reranker.py
services/reranker-service/tests/unit/test_schemas.py
```
​
**Validation**: Test cases from `DDD/07 §10` all pass. `/healthz` returns 200.
​
---
​
### Step 3.4 — Audit Emitter
​
**DDD files to read**:
- `DDD/09` (entire file — §7 defines the audit Elasticsearch index schema and init script)
- `DDD/00 §3.5` (AuditEvent schema)
​
**What to build**: 3 internal modules inside `query-service/internal/audit/`. The emitter is async (L0/L1) or fail-closed (L2/L3). The ES writer does per-event `index/create` writes to the audit index (never bulk). Also create the audit ES index init script (separate from the retrieval index init in Step 2.1).
​
**Output files**:
```
services/query-service/internal/audit/__init__.py
services/query-service/internal/audit/emitter.py        # async emit (L0/L1) or gated emit (L2/L3)
services/query-service/internal/audit/event_builder.py  # builds AuditEvent from request + response
services/query-service/internal/audit/es_writer.py      # per-event index/create write to audit index
services/query-service/tests/unit/test_event_builder.py
services/query-service/tests/integration/test_audit_write.py
deploy/local/jobs/audit-es-init.yaml                    # K8s Job: create audit index (DDD/09 §7 schema)
```
​
**Validation**: Test cases from `DDD/09 §10` all pass, including fail-closed behavior on ES write failure.
​
---
​
## Phase 4 — Query Pipeline (sequential within phase, after Phase 3.1)
​
> Dependency: Step 3.1 complete (UserContext available). Steps 4.1, 4.2, 4.3 are sequential.
​
### Step 4.1 — Query Understanding + Routing
​
**DDD files to read**:
- `DDD/04` (entire file)
- `DDD/00 §3.2` (QueryContext schema)
​
**What to build**: Query parser (rules + optional LLM), expander, decomposer, and router inside `query-service`. The orchestrator returns `QueryContext`, not `ParsedQuery`. For `intent=comparison`, `decompose_query()` splits the query into sub-queries before routing.
​
**Output files**:
```
services/query-service/internal/understanding/__init__.py
services/query-service/internal/understanding/understanding.py  # orchestrator: parse → expand → decompose → return QueryContext
services/query-service/internal/understanding/parser_rules.py   # keyword extraction, intent, doc_type, time_range
services/query-service/internal/understanding/parser_llm.py     # LLM parser (L0/L1 only, optional)
services/query-service/internal/understanding/expander.py       # rule-based (all tiers); LLM (L0/L1 only)
services/query-service/internal/routing/__init__.py
services/query-service/internal/routing/router.py               # QueryContext + UserContext → RoutingDecision (target_indexes, allow_knn, routing_reason)
services/query-service/tests/unit/test_parser_rules.py
services/query-service/tests/unit/test_expander.py
services/query-service/tests/unit/test_router.py
deploy/config/topic-vocabulary.yaml                            # topic classification keywords (DDD/04)
deploy/config/topic-routing-config.yaml                        # topic → index routing rules (DDD/04)
deploy/config/synonym-config.yaml                              # query expansion synonyms (DDD/04)
```
​
**Validation**: Test cases from `DDD/04 §6 (Test Cases)` all pass.
​
---
​
### Step 4.2 — SecureQueryBuilder
​
**DDD files to read**:
- `DDD/05` (entire file)
- `DDD/00 §3.1` (UserContext — acl_tokens field used in filter)
- `DDD/00 §3.3` (RetrievalCandidate — understand what ES must return)
- `DDD/00 §4` (tier table — know which indexes use kNN vs BM25-only)
​
**What to build**: The **sole** ES query assembler. ACL filter must appear in BOTH `query.bool.filter` AND `knn.filter`. The `query_validator.py` must assert this before execution.
​
**Output files**:
```
services/query-service/internal/querybuilder/__init__.py
services/query-service/internal/querybuilder/secure_query_builder.py  # orchestrates all modules below
services/query-service/internal/querybuilder/acl_filter.py            # terms filter on acl_tokens + sensitivity_level range
services/query-service/internal/querybuilder/hybrid_query.py          # BM25 + kNN DSL; ACL in both branches
services/query-service/internal/querybuilder/bm25_only_query.py       # cross-tier fallback
services/query-service/internal/querybuilder/query_validator.py       # assert ACL filter present before execution
services/query-service/internal/querybuilder/embedding_client.py      # vectorize query text for kNN; Redis DB3 cache
services/query-service/tests/unit/test_acl_filter.py
services/query-service/tests/unit/test_hybrid_query.py
services/query-service/tests/unit/test_query_validator.py
services/query-service/tests/security/test_acl_bypass.py         # ACL filter removal attempts
```
​
**Validation**: Test cases from `DDD/05 §11` all pass. `test_acl_bypass.py` proves no query can be emitted without ACL filter.
​
---
​
### Step 4.3 — Retrieval Orchestrator + Result Cache
​
**DDD files to read**:
- `DDD/06` (entire file)
- `DDD/12 §5` (DB2 key schema: `result:{query_hash}:{acl_key}`, TTL=60s)
- `DDD/00 §3.3` (RetrievalCandidate for type reference)
​
**What to build**: Fan-out to multiple ES indexes, merge + dedup, call reranker, manage result cache in Redis DB2.
​
**Output files**:
```
services/query-service/internal/orchestrator/__init__.py
services/query-service/internal/orchestrator/orchestrator.py   # fan-out to ES; post-filter; call reranker; cache
services/query-service/internal/orchestrator/es_client.py      # AsyncElasticsearch wrapper
services/query-service/internal/orchestrator/result_cache.py   # Redis DB2: result:{query_hash}:{acl_key}
services/query-service/internal/orchestrator/merger.py         # dedup + min-max score normalisation
services/query-service/tests/unit/test_merger.py
services/query-service/tests/integration/test_result_cache.py
services/query-service/tests/integration/test_query_pipeline.py
```
​
**Validation**: Test cases from `DDD/06 §9` all pass, including cache hit/miss. Reranker timeout fallback behavior is specified in `DDD/07 §4.2`.
​
---
​
## Phase 5 — Model Gateway (after Phase 4.3)
​
### Step 5.1 — Model Gateway Client
​
**DDD files to read**:
- `DDD/08` (entire file)
- `DDD/00 §3.2` (QueryContext — expanded_queries field used for context)
- `DDD/00 §3.3` (RetrievalCandidate — content field used in prompt)
- `DDD/00 §4` (tier table — L0/L1 → enterprise gateway; L2/L3 → private endpoint)
​
**What to build**: 4 modules inside `query-service/internal/modelgateway/`. Routes by the **highest `sensitivity_level` among retrieved chunks** (not by `effective_clearance` — the gate is clearance, the routing key is chunk sensitivity). Context minimization (top-N selection). Verifier checks answer against source chunks.
​
**Output files**:
```
services/query-service/internal/modelgateway/__init__.py
services/query-service/internal/modelgateway/client.py          # httpx async; routes L0/L1 vs L2/L3
services/query-service/internal/modelgateway/context_builder.py # top-N selection + prompt assembly
services/query-service/internal/modelgateway/path_selector.py   # returns ModelConfig by highest retrieved sensitivity_level
services/query-service/internal/modelgateway/verifier.py        # answer verification vs source chunks
services/query-service/tests/unit/test_context_builder.py
services/query-service/tests/unit/test_path_selector.py
```
​
**Validation**: Test cases from `DDD/08 §11` all pass.
​
---
​
## Phase 6 — Query Service Assembly (after Phases 3–5 complete)
​
### Step 6.1 — Query Service: main, config, router endpoint
​
**DDD files to read**:
- `DDD/00 §1.1` (tech stack: FastAPI, Uvicorn, all dependency names)
- `DDD/00 §2` (API conventions: request headers, response envelope, HTTP status codes)
- `DDD/00 §2.5` (error code registry)
- `DDD/00 §8` (health check endpoints: /healthz, /readyz, /metrics)
- `DDD/16 §4` (query-service file tree — for exact filenames)
​
**What to build**: FastAPI app entrypoint, dependency injection wiring, and the single `POST /v1/query` endpoint that calls all pipeline modules in order.
​
**Output files**:
```
services/query-service/main.py              # FastAPI app; mount /v1/query router; /healthz /readyz /metrics
services/query-service/config.py            # pydantic-settings; all env vars + K8s secrets
services/query-service/dependencies.py      # FastAPI DI: get_redis(), get_es_client(), get_http_client()
services/query-service/routers/__init__.py
services/query-service/routers/query.py     # POST /v1/query; calls pipeline in order
services/query-service/Dockerfile
```
​
**Pipeline call order in `routers/query.py`**:
1. `normalizer.normalize_claims()` → fail on bad HMAC
2. `auth_cache.get()` → cache hit: skip step 3
3. `acl_adapter.derive()` → compute acl_tokens; write to cache
4. `guard.check()` → fail on injection/enumeration/rate limit
5. `understanding.parse()` → produce QueryContext
5a. `understanding.decompose_query()` → split if `intent=comparison`; each sub-query continues from step 6 independently (DDD/04 §5)
6. `router.route()` → `RoutingDecision` (target_indexes, allow_knn, routing_reason)
7. `secure_query_builder.build()` → ES query DSL
8. `query_validator.assert_acl_present()` → hard fail if missing
9. `orchestrator.execute()` → candidates (merged across sub-queries if decomposed)
10. `model_gateway.generate()` → answer
11. `audit_emitter.emit()` → async (L0/L1) or gated (L2/L3)
​
**Validation**: `POST /v1/query` with valid claims returns answer; `POST /v1/query` without claims returns 401.
​
---
​
## Phase 7 — Ingestion Workers (parallel with Phases 3–6, after Phase 1)
​
> Steps 7.1–7.9 are **sequential** within this phase. Each worker imports the previous stage's output type.
​
### Step 7.1 — Kafka base worker
​
**DDD files to read**:
- `DDD/16 §2.4` (KafkaWorker base class code)
- `DDD/10 §3` (topic env vars, consumer pattern, DLQ routing, manual commit)
​
**What to build**: The base `KafkaWorker` class and the `queue.py` helpers. All other workers extend this.
​
**Output files**:
```
workers/ingestion/queue.py                         # KafkaWorker base class; DLQ routing (aiokafka)
workers/ingestion/workers/__init__.py
workers/ingestion/workers/base_worker.py           # abstract Worker: connect, consume loop, DLQ logic
workers/ingestion/config.py                        # all KAFKA_*, REDIS_*, ES_*, EMBEDDING_* env vars
workers/ingestion/schemas.py                       # re-exports from rag-common; ingestion-specific types
workers/ingestion/Dockerfile
workers/ingestion/tests/conftest.py
```
​
**Validation**: `KafkaWorker` starts, consumes a message, produces to output topic, commits offset — verified with a test that mocks `AIOKafkaConsumer`/`AIOKafkaProducer`.
​
---
​
### Step 7.2 — Connector Worker
​
**DDD files to read**: `DDD/10 §4` (supported source types, connector output schema, trigger modes)
​
**What to build**: Connector worker that fetches source documents (PDF, HTML, MD, Wiki, DB) and emits `IngestionJob` to `ingestion.raw`.
​
**Output files**:
```
workers/ingestion/workers/connector_worker.py
workers/ingestion/tests/unit/test_connector_worker.py
```
​
**Validation**: PDF file → `IngestionJob` with `raw_content_bytes` populated; MD file → `IngestionJob` with `raw_content` populated.
​
---
​
### Step 7.3 — Parser Worker
​
**DDD files to read**: `DDD/10 §5` (parse function pseudocode, PDF parser Python code, Immutable Source Principle)
​
**What to build**: Parser that converts `raw_content` / `raw_content_bytes` into `parsed_sections[]`. Must never modify `raw_content`.
​
**Output files**:
```
workers/ingestion/workers/parser_worker.py
workers/ingestion/tests/unit/test_parser_worker.py
```
​
**Validation**: 10-page PDF → 10+ `ParsedSection` objects with `page_number` set and `raw_content` unchanged (Immutable Source Principle). ING-01 is an end-to-end test that spans the full pipeline; it is validated in Step 10.2.
​
---
​
### Step 7.4 — Risk Scanner Worker
​
**DDD files to read**: `DDD/10 §6` (sensitivity rules SENS-001–003, injection rules INJ-DOC-001–002, format anomalies, quarantine routing)
​
**What to build**: Scanner that assigns `sensitivity_level` and either sanitizes parsed content (INJ-DOC-001) or routes to `ingestion.quarantine` (INJ-DOC-002). Operates on `parsed_sections` before chunking — chunks do not exist at this stage.
​
**Output files**:
```
workers/ingestion/workers/risk_scanner_worker.py
workers/ingestion/tests/unit/test_risk_scanner_worker.py
```
​
**Validation**: Tests ING-02, ING-03, ING-04 from `DDD/10 §14` all pass.
​
---
​
### Step 7.5 — Chunker Worker
​
**DDD files to read**: `DDD/10 §7` (split algorithm Python code, CHUNK_SIZE_TOKENS=400, CHUNK_OVERLAP_TOKENS=75, cl100k_base tokenizer)
​
**What to build**: Sliding-window token chunker. Replace `parsed_sections` with `chunks[]` in the IngestionJob.
​
**Output files**:
```
workers/ingestion/workers/chunker_worker.py
workers/ingestion/tests/unit/test_chunker_worker.py
```
​
**Validation**: 1000-token section → ≥3 chunks; each chunk ≤400 tokens; adjacent chunks overlap by ~75 tokens.
​
---
​
### Step 7.6 — Metadata Enricher Worker
​
**DDD files to read**: `DDD/10 §8` (enrich pseudocode, doc_id = SHA-256 of source_uri, chunk_id formula, topic/doc_type/year classification)
​
**What to build**: Enricher that stamps `doc_id`, `chunk_id`, `topic`, `doc_type`, `year`, `source`, `created_at`, `updated_at` on every chunk.
​
**Output files**:
```
workers/ingestion/workers/enricher_worker.py
workers/ingestion/tests/unit/test_enricher_worker.py
```
​
**Validation**: All chunks have non-null `doc_id`, `chunk_id`, `topic`; `chunk_id = doc_id + "-" + index`.
​
---
​
### Step 7.7 — ACL Binder Worker
​
**DDD files to read**:
- `DDD/10 §9` (bind_acl pseudocode, empty ACL handling, acl_key formula)
- `DDD/02 §4.3` (token compression rules — must use same logic as query-side adapter)
​
**Important**: Import `compress_groups_to_tokens` from `rag-common` — do not re-implement. This guarantees doc-side and query-side tokens match.
​
**Output files**:
```
workers/ingestion/workers/acl_binder_worker.py
workers/ingestion/tests/unit/test_acl_binder_worker.py
```
​
**Validation**: Test ING-05 (no ACL → invisible) and ING-10 (doc-side tokens == query-side tokens for same groups) from `DDD/10 §14`.
​
---
​
### Step 7.8 — Embedding Worker
​
**DDD files to read**: `DDD/10 §10` (embed pseudocode, L0/L1 vs L2/L3 routing, batch sizes, bge-m3 sequence length assertion, CJK note)
​
**What to build**: Embedding worker that routes by `sensitivity_level`. L0/L1 → enterprise gateway (`text-embedding-3-small`, 1536d, batch=200). L2/L3 → embedding-service (`bge-m3`, 1024d, batch=32). Assert `token_count(chunk) ≤ 7000` before L2/L3 embedding.
​
**Output files**:
```
workers/ingestion/workers/embedding_worker.py
workers/ingestion/tests/unit/test_embedding_worker.py
```
​
**Validation**: Tests ING-06 (L0 → 1536d), ING-07 (L2 → 1024d) from `DDD/10 §14`.
​
---
​
### Step 7.9 — Indexer Worker
​
**DDD files to read**:
- `DDD/10 §11` (index function pseudocode, update strategy: create/update/delete/rebuild)
- `DDD/11 §3` (index mapping — to know target index names per sensitivity_level)
- `DDD/00 §3.7` (ElasticsearchChunk schema — fields to write)
​
**What to build**: Indexer that writes chunks via ES bulk API. Routes to correct index by `sensitivity_level` (0→public, 1→internal, 2→confidential, 3→restricted).
​
**Output files**:
```
workers/ingestion/workers/indexer_worker.py
workers/ingestion/tests/unit/test_indexer_worker.py
workers/ingestion/tests/integration/test_ingestion_pipeline.py  # end-to-end: PDF → ES doc
```
​
**Validation**: Test ING-08 (blue/green rebuild alias cutover) and ING-09 (concurrent workers, no duplicate chunks) from `DDD/10 §14`.
​
---
​
## Phase 8 — Embedding Service (parallel with Phase 7, after Phase 0)
​
> Note: Step 7.8 (Embedding Worker) calls this service for L2/L3 documents. Development of Steps 7.8 and 8.1 may proceed in parallel using a mock endpoint, but **Step 7.8's end-to-end validation requires Step 8.1 to be deployed**.
​
### Step 8.1 — Self-hosted BGE-M3 embedding service
​
**DDD files to read**:
- `DDD/16 §6` (embedding-service file tree)
- `DDD/10 §10` (bge-m3 model config: EMBEDDING_MODEL_L2L3, EMBEDDING_DIMS_L2L3=1024, EMBEDDING_BATCH_SIZE_L2L3=32, sequence length 8192)
- `DDD/00 §1.1` (sentence-transformers library for bge-m3)
​
**What to build**: Standalone FastAPI service. Accepts `texts[]`, returns `vectors[]` (1024d per text). Validates sequence length before encoding.
​
**Output files**:
```
services/embedding-service/main.py         # FastAPI; POST /v1/embed; /healthz /readyz /metrics
services/embedding-service/config.py       # MODEL_NAME=bge-m3, BATCH_SIZE, MAX_SEQ_LEN
services/embedding-service/schemas.py      # EmbedRequest(texts[]), EmbedResponse(vectors[])
services/embedding-service/embedder.py     # bge-m3 load; batch encode; seq-len assertion
services/embedding-service/Dockerfile
services/embedding-service/tests/conftest.py
services/embedding-service/tests/unit/test_embedder.py    # EN/ZH/JA texts; assert dims=1024
services/embedding-service/tests/unit/test_schemas.py
```
​
**Validation**: `POST /v1/embed` with Chinese text → 1024d vector; with Japanese text → 1024d vector; with text >8192 tokens → 400 error.
​
---
​
## Phase 9 — API Gateway Stub (parallel with Phases 3–8, after Step 2.5)
​
### Step 9.1 — Gateway stub (local dev only)
​
**DDD files to read**:
- `DDD/01` (API gateway responsibilities: token validation, claims forwarding, rate limiting)
- `DDD/14 §4` (Mock Claims Injector behavior, mock-users.yaml format)
- `DDD/16 §8` (gateway-stub file tree)
- `DDD/00 §2.2` (X-Trusted-Claims + X-Claims-Sig header format)
​
**What to build**: FastAPI service that validates Bearer token against `mock-users.yaml`, signs claims with HMAC-SHA256, and forwards to query service. **Not deployed to production.**
​
**Output files**:
```
services/gateway-stub/main.py              # FastAPI; validates Bearer token against mock-users.yaml
services/gateway-stub/config.py            # MOCK_USERS_FILE, CLAIMS_SIGNING_KEY
services/gateway-stub/claims_signer.py     # HMAC-SHA256 sign; produce X-Trusted-Claims + X-Claims-Sig
services/gateway-stub/schemas.py           # MockUser, Claims
services/gateway-stub/Dockerfile
services/gateway-stub/tests/unit/test_claims_signer.py
deploy/config/kong.yaml                    # Kong declarative config (production routes, plugins)
```
​
**Validation**: Valid Bearer token → `X-Trusted-Claims` and `X-Claims-Sig` headers forwarded. Invalid token → 401.
​
---
​
## Phase 10 — Integration and Security Testing (after Phases 6, 7, 9)
​
### Step 10.1 — Query pipeline integration test
​
**DDD files to read**:
- `DDD/14 §3` (local cluster setup: kind config, port-forwarding, seed data)
- `DDD/00 §2` (API conventions: request format, expected response envelope)
- `DDD/00 §2.5` (all error codes to test)
​
**What to build**: End-to-end tests against a running local cluster. Cover the full query path from gateway stub through to answer generation.
​
**Output files**:
```
services/query-service/tests/integration/test_query_pipeline.py
services/query-service/tests/security/test_injection.py
services/query-service/tests/security/test_enumeration.py
```
​
**Validation**: L0 user query returns answer. Query retrieving L2/L3 chunks routes to private model endpoint (model path is determined by highest retrieved `sensitivity_level`, not user clearance). User with no ACL match for a document gets empty results (not 403).
​
---
​
### Step 10.2 — Ingestion pipeline end-to-end test
​
**DDD files to read**:
- `DDD/10 §14` (all 10 test cases ING-01 to ING-10)
- `DDD/14 §3` (local cluster setup)
​
**What to build**: Full pipeline test: drop a PDF into the connector, wait for all workers, verify the document appears in Elasticsearch with correct `acl_tokens`, `sensitivity_level`, and `vector` dimensions.
​
**Output files**:
```
workers/ingestion/tests/integration/test_ingestion_pipeline.py
```
​
**Validation**: All 10 test cases ING-01 through ING-10 pass.
​
---
​
## Summary Table
​
| Phase | Step | Description | Parallel With | Depends On |
|-------|------|-------------|---------------|------------|
| 0 | 0.1 | Repo scaffold | — | — |
| 1 | 1.1 | rag-common models | Phase 2 | 0.1 |
| 1 | 1.2 | ACL utilities | Phase 2 | 1.1 |
| 2 | 2.1–2.5 | Infrastructure | Phases 1, 3–9 | 0.1 |
| 3 | 3.1 | Claims/ACL Adapter | 3.2, 3.3, 3.4 | 1.2 |
| 3 | 3.2 | Query Guard | 3.1, 3.3, 3.4 | 1.1 |
| 3 | 3.3 | Reranker Service | 3.1, 3.2, 3.4 | 1.1 |
| 3 | 3.4 | Audit Emitter | 3.1, 3.2, 3.3 | 1.1 |
| 4 | 4.1 | Query Understanding + Routing | Phase 7, 8, 9 | 3.1 |
| 4 | 4.2 | SecureQueryBuilder | Phase 7, 8, 9 | 4.1 |
| 4 | 4.3 | Retrieval Orchestrator | Phase 7, 8, 9 | 4.2 |
| 5 | 5.1 | Model Gateway | Phase 7, 8, 9 | 4.3 |
| 6 | 6.1 | Query Service assembly | Phase 7, 8, 9 | 3.1–3.4, 4.1–4.3, 5.1 |
| 7 | 7.1 | Kafka base worker | Phase 6 | 1.1 |
| 7 | 7.2–7.9 | Ingestion workers (8 workers) | Phase 6 | 7.1 (sequential) |
| 8 | 8.1 | Embedding service | Phases 3–6 | 0.1 |
| 9 | 9.1 | Gateway stub | Phases 3–8 | 2.5 |
| 10 | 10.1 | Query integration tests | 10.2 | 6.1, 9.1, 2.5 |
| 10 | 10.2 | Ingestion e2e tests | 10.1 | 7.9, 8.1, 2.1–2.3 |
​
---
​
## Critical Rules for Every Step
​
1. **Read only listed DDD sections** — other sections contain unrelated context that wastes tokens.
2. **Import from `rag-common`** for all shared types — never re-implement `UserContext`, `IngestionJob`, `compress_groups_to_tokens`, or `acl_key`.
3. **ACL filter is non-negotiable** — every ES query must pass through `query_validator.assert_acl_present()`.
4. **No auto-commit in Kafka** — always `enable_auto_commit=False`; commit only after successful downstream produce.
5. **Fail-closed for L2/L3** — any infrastructure error on the L2/L3 path must return 503, not a degraded answer.
6. **Structured JSON logs only** — never log `acl_tokens`, `allowed_groups`, chunk content, or raw claims (DDD/00 §7).
7. **Track progress with tasks** — Use the task tool to create and update discrete steps as you work; mark each step complete immediately when done, not in batches.