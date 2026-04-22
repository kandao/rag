# DDD v1.0 16: Project Structure and File Inventory
​
## 1. Repository Layout
​
```
rag/
├── services/
│   ├── query-service/             # FastAPI — core query path
│   ├── reranker-service/          # FastAPI — GPU reranker
│   ├── embedding-service/         # FastAPI — bge-m3 self-hosted (L2/L3)
│   └── gateway-stub/             # FastAPI — local dev only (replaces Kong)
├── workers/
│   └── ingestion/                 # 8 Kafka consumer workers
├── packages/
│   └── rag-common/                # Shared Pydantic models + ACL utilities
├── deploy/
│   ├── charts/rag/                # Helm chart
│   ├── local/                     # kind/k3d manifests + seed jobs
│   ├── mappings/                  # ES index mapping JSON
│   ├── config/                    # redis.conf, kong.yaml
│   └── kafka/                     # Strimzi KafkaCluster + KafkaTopic CRDs
└── test/
    └── fixtures/                  # mock-users.yaml, acl-policies.yaml, seed docs
```
​
---
​
## 2. Message Queue: Apache Kafka
​
### 2.1 Decision
​
The ingestion pipeline uses **Apache Kafka** for inter-worker messaging, managed by the **Strimzi Kafka Operator** in Kubernetes.
​
| Option | Assessment |
|--------|-----------|
| Redis Streams | Already in stack; but no built-in DLQ; eviction risk; shared fate with caching layer |
| Celery + Redis | Adds Celery overhead; same Redis shared-fate problem |
| RabbitMQ | Good DLQ support; but no message replay; less observable than Kafka |
| **Kafka** ✓ | Native DLQ topics; 7-day replay; consumer lag metrics; strong delivery guarantees; Strimzi simplifies K8s ops |
​
**Verdict**: Kafka. The replay capability alone justifies it — if an indexer bug is found after ingestion, affected documents can be re-processed from the `ingestion.embedded` topic without re-fetching or re-embedding source documents.
​
### 2.2 Kubernetes Deployment (Strimzi)
​
```yaml
# deploy/kafka/kafka-cluster.yaml  (Strimzi KafkaCluster CRD)
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: rag-kafka
  namespace: kafka
spec:
  kafka:
    replicas: 3
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false                 # mTLS handled by Istio sidecar
    storage:
      type: persistent-claim
      size: 100Gi
      class: ssd
  zookeeper:                       # or use KRaft mode (Kafka 3.3+) to eliminate ZooKeeper
    replicas: 3
    storage:
      type: persistent-claim
      size: 10Gi
```
​
### 2.3 Topic Definitions
​
```yaml
# deploy/kafka/topics.yaml  (Strimzi KafkaTopic CRDs)
# Ingestion pipeline topics:
ingestion.raw           connector   → parser           partitions: 3, retention: 7d
ingestion.parsed        parser      → risk_scanner      partitions: 3, retention: 7d
ingestion.scanned       risk_scanner → chunker          partitions: 3, retention: 7d
ingestion.quarantine    risk_scanner → (terminal)       partitions: 3, retention: 30d
ingestion.chunked       chunker     → enricher          partitions: 3, retention: 7d
ingestion.enriched      enricher    → acl_binder        partitions: 3, retention: 7d
ingestion.acl_bound     acl_binder  → embedding_worker  partitions: 3, retention: 7d
ingestion.embedded      embedding   → indexer           partitions: 3, retention: 7d
ingestion.dlq           any worker  → (terminal)        partitions: 3, retention: 30d
```
​
Message key = `source_uri` on all topics — ensures all stages for a given document land on the same partition, preserving per-document ordering.
​
### 2.4 Consumer Pattern (`queue.py`)
​
```python
# workers/ingestion/queue.py
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
​
MAX_RETRIES = 3
​
class KafkaWorker:
    def __init__(self, input_topic: str, output_topic: str):
        self.consumer = AIOKafkaConsumer(
            input_topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=KAFKA_CONSUMER_GROUP,
            enable_auto_commit=False,      # manual commit only after successful produce
            auto_offset_reset="earliest",
        )
        self.producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
​
    async def run(self):
        async with self.consumer, self.producer:
            async for msg in self.consumer:
                job = IngestionJob.model_validate_json(msg.value)
                retry_count = int(dict(msg.headers).get("retry_count", b"0"))
                try:
                    result = await self.process(job)
                    await self.producer.send(
                        self.output_topic,
                        value=result.model_dump_json().encode(),
                        key=job.source_uri.encode(),
                    )
                    await self.consumer.commit()
                except Exception as e:
                    target = KAFKA_TOPIC_DLQ if retry_count >= MAX_RETRIES else msg.topic
                    await self.producer.send(
                        target,
                        value=msg.value,
                        headers=[("retry_count", str(retry_count + 1).encode()),
                                 ("failed_stage", msg.topic.encode()),
                                 ("error", str(e).encode())],
                        key=job.source_uri.encode(),
                    )
                    await self.consumer.commit()
​
    async def process(self, job: IngestionJob) -> IngestionJob:
        raise NotImplementedError  # overridden by each worker
```
​
### 2.5 Observability
​
Kafka provides consumer lag natively — no custom PEL monitoring needed:
​
```yaml
# Prometheus scrape via Kafka Exporter (bundled with Strimzi)
# Key metrics:
kafka_consumergroup_lag          # messages behind per group+topic+partition
kafka_topic_partitions           # partition count
kafka_consumergroup_members      # active consumers per group
```
​
Alert rule: `kafka_consumergroup_lag{group="ingestion-workers"} > 1000` for 5 minutes → PagerDuty.
​
---
​
## 3. Shared Package: `rag-common`
​
Pydantic models and ACL utilities used by both the query service and ingestion workers are in a shared internal package.
​
```
packages/rag-common/
├── pyproject.toml
├── rag_common/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user_context.py        # UserContext
│   │   ├── query.py               # QueryContext, QueryRequest, QueryResponse
│   │   ├── retrieval.py           # RetrievalCandidate, RankedCandidate
│   │   ├── ingestion.py           # IngestionJob, Chunk, ParsedSection, ACLPolicy
│   │   └── audit.py               # AuditEvent
│   └── acl/
│       ├── __init__.py
│       ├── token_compression.py   # compress_groups_to_tokens()
│       ├── acl_key.py             # acl_key = SHA-256(sorted_tokens|versions)
│       └── claims_hash.py         # claims_hash = SHA-256(groups|role|clearance|versions)
```
​
Each service adds `rag-common` as a local path dependency:
```toml
# pyproject.toml
[tool.poetry.dependencies]
rag-common = { path = "../../packages/rag-common", develop = true }
```
​
---
​
## 4. Query Service (`services/query-service/`)
​
**Total: ~56 files**
​
```
query-service/
├── pyproject.toml
├── Dockerfile
├── main.py                        # FastAPI app; mounts /v1/query router
├── config.py                      # pydantic-settings; reads all env vars + K8s secrets
├── dependencies.py                # FastAPI DI: get_redis(), get_es_client(), get_http_client()
├── routers/
│   ├── __init__.py
│   └── query.py                   # POST /v1/query endpoint; calls pipeline in order
├── internal/
│   ├── __init__.py
│   ├── claims/
│   │   ├── __init__.py
│   │   ├── normalizer.py          # verify HMAC sig; parse X-Trusted-Claims header
│   │   └── acl_adapter.py         # expand groups → acl_tokens; compute acl_key
│   ├── cache/
│   │   ├── __init__.py
│   │   └── auth_cache.py          # Redis DB0: read/write UserContext by claims_hash
│   ├── guard/
│   │   ├── __init__.py
│   │   ├── guard.py               # orchestrates the 3 checks below
│   │   ├── injection_detector.py  # regex pattern matching; HIGH/MEDIUM signals
│   │   ├── enumeration_detector.py # Jaccard similarity against query history
│   │   └── rate_limiter.py        # Redis DB1: INCR + EXPIRE sliding window
│   ├── understanding/
│   │   ├── __init__.py
│   │   ├── understanding.py       # orchestrator: parse → expand → decompose → return QueryContext
│   │   ├── parser_rules.py        # keyword extraction, intent, doc_type, time_range
│   │   ├── parser_llm.py          # LLM-based parser (L0/L1 only, optional)
│   │   └── expander.py            # rule-based expansion (all tiers); LLM (L0/L1 only)
│   ├── routing/
│   │   ├── __init__.py
│   │   └── router.py              # QueryContext + UserContext → RoutingDecision
│   ├── querybuilder/
│   │   ├── __init__.py
│   │   ├── secure_query_builder.py # sole ES query assembler; calls modules below
│   │   ├── acl_filter.py          # builds terms filter on acl_tokens + sensitivity_level range
│   │   ├── hybrid_query.py        # BM25 + kNN DSL; injects ACL in both branches
│   │   ├── bm25_only_query.py     # cross-tier fallback (no kNN)
│   │   ├── query_validator.py     # asserts ACL filter present before execution
│   │   └── embedding_client.py    # vectorize query text for kNN; Redis DB3 cache
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator.py        # fan-out to ES; post-filter; call reranker; cache
│   │   ├── es_client.py           # AsyncElasticsearch wrapper
│   │   ├── result_cache.py        # Redis DB2: result:{query_hash}:{acl_key}
│   │   └── merger.py              # dedup + min-max score normalisation across indexes
│   ├── modelgateway/
│   │   ├── __init__.py
│   │   ├── client.py              # httpx async; routes L0/L1 vs L2/L3 endpoints
│   │   ├── context_builder.py     # top-N selection + prompt assembly
│   │   ├── path_selector.py       # returns ModelConfig by highest retrieved sensitivity_level
│   │   └── verifier.py            # answer verification against source chunks
│   └── audit/
│       ├── __init__.py
│       ├── emitter.py             # async emit (L0/L1) or gated emit (L2/L3)
│       ├── event_builder.py       # builds AuditEvent from request + response
│       └── es_writer.py           # per-event index/create write to audit index
└── tests/
    ├── conftest.py                # fixtures: mock Redis, mock ES, sample UserContext
    ├── unit/
    │   ├── test_normalizer.py
    │   ├── test_acl_adapter.py
    │   ├── test_auth_cache.py
    │   ├── test_injection_detector.py
    │   ├── test_enumeration_detector.py
    │   ├── test_rate_limiter.py
    │   ├── test_parser_rules.py
    │   ├── test_expander.py
    │   ├── test_router.py
    │   ├── test_acl_filter.py
    │   ├── test_hybrid_query.py
    │   ├── test_query_validator.py
    │   ├── test_merger.py
    │   ├── test_context_builder.py
    │   ├── test_path_selector.py
    │   └── test_event_builder.py
    ├── integration/
    │   ├── test_query_pipeline.py  # full query path against local cluster
    │   ├── test_result_cache.py
    │   └── test_audit_write.py
    └── security/
        ├── test_acl_bypass.py      # ACL filter removal attempts
        ├── test_injection.py       # injection signal detection
        └── test_enumeration.py     # enumeration detection
```
​
---
​
## 5. Reranker Service (`services/reranker-service/`)
​
**Total: ~9 files**
​
```
reranker-service/
├── pyproject.toml
├── Dockerfile                     # base: python:3.11-slim + CUDA if GPU
├── main.py                        # FastAPI; POST /v1/rerank
├── config.py                      # MODEL_PATH, BATCH_SIZE, MAX_SEQUENCE_LENGTH
├── schemas.py                     # RerankRequest, RerankResponse
├── reranker.py                    # sentence-transformers CrossEncoder; batch scoring
└── tests/
    ├── conftest.py
    └── unit/
        ├── test_reranker.py
        └── test_schemas.py
```
​
---
​
## 6. Embedding Service (`services/embedding-service/`)
​
**Total: ~9 files**
​
```
embedding-service/
├── pyproject.toml
├── Dockerfile                     # base: python:3.11-slim + sentence-transformers + bge-m3
├── main.py                        # FastAPI; POST /v1/embed
├── config.py                      # MODEL_NAME=bge-m3, BATCH_SIZE, MAX_SEQ_LEN
├── schemas.py                     # EmbedRequest (texts[]), EmbedResponse (vectors[])
├── embedder.py                    # bge-m3 model load; batch encode; seq-len assertion
└── tests/
    ├── conftest.py
    └── unit/
        ├── test_embedder.py       # EN/ZH/JA sample texts; assert dims=1024
        └── test_schemas.py
```
​
---
​
## 7. Ingestion Workers (`workers/ingestion/`)
​
**Total: ~25 files**
​
```
workers/ingestion/
├── pyproject.toml
├── Dockerfile
├── config.py                      # all KAFKA_*, REDIS_*, ES_*, EMBEDDING_* env vars
├── queue.py                       # Kafka helpers: KafkaWorker base class, DLQ routing (aiokafka)
├── schemas.py                     # re-exports from rag-common; ingestion-specific types
├── workers/
│   ├── __init__.py
│   ├── base_worker.py             # abstract Worker: connect, consume loop, DLQ logic
│   ├── connector_worker.py        # fetches source; emits to ingestion.raw
│   ├── parser_worker.py           # PDF/HTML/MD/Wiki/DB → ParsedSection[]
│   ├── risk_scanner_worker.py     # sensitivity + injection scan; routes to quarantine
│   ├── chunker_worker.py          # sliding window; tiktoken cl100k_base
│   ├── enricher_worker.py         # doc_id, chunk_id, topic, doc_type, year
│   ├── acl_binder_worker.py       # group + role token compression; acl_key
│   ├── embedding_worker.py        # L0/L1 → enterprise GW; L2/L3 → embedding-service
│   └── indexer_worker.py          # ES bulk write; routes by sensitivity_level
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_connector_worker.py
    │   ├── test_parser_worker.py
    │   ├── test_risk_scanner_worker.py
    │   ├── test_chunker_worker.py
    │   ├── test_enricher_worker.py
    │   ├── test_acl_binder_worker.py
    │   ├── test_embedding_worker.py
    │   └── test_indexer_worker.py
    └── integration/
        └── test_ingestion_pipeline.py  # end-to-end: PDF → ES doc
```
​
---
​
## 8. API Gateway Stub (`services/gateway-stub/`)
​
**Local dev only. Not deployed to production.**
​
**Total: ~7 files**
​
```
gateway-stub/
├── pyproject.toml
├── Dockerfile
├── main.py                        # FastAPI; validates Bearer token against mock-users.yaml
├── config.py                      # MOCK_USERS_FILE, CLAIMS_SIGNING_KEY
├── claims_signer.py               # HMAC-SHA256 sign; produce X-Trusted-Claims + X-Claims-Sig
├── schemas.py                     # MockUser, Claims
└── tests/
    └── unit/
        └── test_claims_signer.py
```
​
---
​
## 9. Shared Package (`packages/rag-common/`)
​
**Total: ~12 files**
​
```
rag-common/
├── pyproject.toml
└── rag_common/
    ├── __init__.py
    ├── models/
    │   ├── __init__.py
    │   ├── user_context.py        # UserContext (Pydantic)
    │   ├── query.py               # QueryContext, QueryRequest, QueryResponse
    │   ├── retrieval.py           # RetrievalCandidate, RankedCandidate
    │   ├── ingestion.py           # IngestionJob, Chunk, ParsedSection, ACLPolicy
    │   └── audit.py               # AuditEvent
    └── acl/
        ├── __init__.py
        ├── token_compression.py   # compress_groups_to_tokens(); shared by query + ingestion
        ├── acl_key.py             # SHA-256(sorted_tokens|schema_ver|acl_ver)
        └── claims_hash.py         # SHA-256(groups|role|clearance|versions)
```
​
---
​
## 10. Infrastructure and Config (`deploy/`, `test/`)
​
**Total: ~27 files**
​
```
deploy/
├── charts/rag/
│   ├── Chart.yaml
│   ├── values.yaml                # production defaults
│   └── values-local.yaml          # local dev overrides
├── local/
│   ├── namespaces.yaml
│   ├── jobs/
│   │   ├── es-init.yaml           # K8s Job: create retrieval indexes
│   │   ├── audit-es-init.yaml     # K8s Job: create audit index (schema from DDD/09 §7)
│   │   └── seed-data.yaml         # K8s Job: load test fixtures
├── mappings/
│   ├── l0l1-mapping.json          # ES index mapping dims=1536
│   └── l2l3-mapping.json          # ES index mapping dims=1024
├── config/
│   ├── redis.conf                 # maxmemory-policy allkeys-lru
│   ├── kong.yaml                  # Kong declarative config (routes, plugins)
│   ├── acl-hierarchy-config.yaml  # ACL group hierarchy for token compression (DDD/02 §4)
│   ├── injection-patterns.yaml    # guard injection regex patterns (DDD/03 §9)
│   ├── topic-vocabulary.yaml      # query understanding topic keywords (DDD/04)
│   ├── topic-routing-config.yaml  # topic → index routing rules (DDD/04)
│   └── synonym-config.yaml        # query expansion synonyms (DDD/04)
└── kafka/
    ├── kafka-cluster.yaml          # Strimzi KafkaCluster CRD (3 brokers + ZooKeeper/KRaft)
    └── topics.yaml                 # Strimzi KafkaTopic CRDs for all 9 ingestion topics
​
test/fixtures/
├── mock-users.yaml                # 6 test users (L0–L3, attacker, no-acl)
├── acl-policies.yaml              # source_pattern → allowed_groups/roles
└── documents/
    ├── public/
    │   ├── finance_report_2024.pdf
    │   └── product_overview.md
    ├── internal/
    │   ├── engineering_guidelines_2024.md
    │   └── hr_policy_2024.md
    ├── confidential/
    │   ├── m_and_a_memo_2024.pdf
    │   └── legal_contracts_q1.md
    └── restricted/
        └── board_minutes_2024.pdf
```
​
---
​
## 11. File Count Summary
​
| Component | Implementation | Tests | Config/Infra | Total |
|-----------|---------------|-------|-------------|-------|
| `rag-common` | 11 | — | 1 (`pyproject.toml`) | **12** |
| Query Service | 32 | 22 | 2 (`Dockerfile`, `pyproject.toml`) | **56** |
| Reranker Service | 4 | 3 | 2 | **9** |
| Embedding Service | 4 | 3 | 2 | **9** |
| Ingestion Workers | 12 | 11 | 2 | **25** |
| Gateway Stub | 4 | 1 | 2 | **7** |
| Deploy / Infra + Kafka | — | — | 18 | **18** |
| Test Fixtures | — | — | 9 | **9** |
| **Total** | **67** | **40** | **38** | **145** |
