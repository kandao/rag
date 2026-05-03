# Source Code Workflow Review

This document summarizes the code in this repository, how the main components work together, and how users or operators interact with the system.

## Repository Shape

The project is an enterprise RAG system split into services, workers, shared models, deploy manifests, tests, and design docs.

| Area | Purpose |
| --- | --- |
| `services/query-service` | Main FastAPI query pipeline. Validates a request, checks identity and ACLs, guards the query, retrieves chunks, calls the model gateway, and emits audit events. |
| `services/gateway-stub` | Local development replacement for Kong. Accepts mock bearer tokens, signs trusted claims, and proxies requests to query-service. |
| `services/embedding-service` | FastAPI embedding service for private/self-hosted embeddings. Loads a SentenceTransformer model and exposes `/v1/embed`. |
| `services/reranker-service` | FastAPI reranker service. Uses a CrossEncoder to score retrieved candidates. |
| `services/llm-stub` | Local test LLM that mimics an OpenAI chat completions endpoint with deterministic responses. |
| `workers/ingestion` | Kafka worker pipeline for fetching, parsing, scanning, chunking, enriching, ACL-binding, embedding, and indexing documents. |
| `packages/rag-common` | Shared Pydantic models and ACL helper functions used by services and workers. |
| `deploy` | Kubernetes, Helm, Kafka, Redis, Elasticsearch, and local development manifests. |
| `test/fixtures` | Mock users, ACL policies, and sample documents. |
| `docs/detail-design/v1.0` | Detailed design documents that describe the intended architecture and contracts. |

## Query Workflow

The primary user-facing workflow is `POST /v1/query`.

```text
Client
  -> gateway-stub or Kong
  -> query-service
  -> Redis, Elasticsearch, embedding service, reranker service, model endpoint, audit index
  -> response with answer and citations
```

### 1. Gateway Stub

Source: `services/gateway-stub/main.py`, `services/gateway-stub/claims_signer.py`

The gateway stub is for local development. It loads mock users from `MOCK_USERS_FILE`, expects an `Authorization: Bearer <token>` header, and maps the token to user claims.

It then:

1. Encodes the claims as base64 JSON.
2. Signs the raw claims JSON with HMAC-SHA256 using `CLAIMS_SIGNING_KEY`.
3. Removes any client-supplied `X-Trusted-Claims`, `X-Claims-Sig`, and `Authorization` headers.
4. Adds trusted claim headers.
5. Proxies the request to `QUERY_SERVICE_URL`.

This simulates the production API gateway contract where only the gateway is allowed to mint trusted identity headers.

Mock tokens are defined in `test/fixtures/mock-users.yaml` and duplicated in `deploy/local/services.yaml`, for example:

```text
test-token-l0
test-token-l1
test-token-l2
test-token-l3
test-token-attacker
test-token-no-acl
```

### 2. Query Service Entry Point

Source: `services/query-service/main.py`, `services/query-service/routers/query.py`

The FastAPI app opens shared clients during startup:

| Client | Used for |
| --- | --- |
| Redis | ACL cache, guard state, result cache, embedding cache |
| AsyncElasticsearch | Retrieval and audit writes |
| httpx.AsyncClient | Embedding, reranker, and model endpoint calls |

The public endpoints are:

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Process liveness check |
| `GET /readyz` | Checks Redis and Elasticsearch connectivity |
| `GET /metrics` | Placeholder Prometheus text endpoint |
| `POST /v1/query` | Main RAG query endpoint |

### 3. Input Validation

Source: `services/query-service/internal/input_validator.py`

Before identity or retrieval work, the query string is checked for basic validity such as length. Validation errors return structured HTTP errors.

### 4. Claims Normalization and ACL Context

Source: `services/query-service/internal/claims/normalizer.py`, `services/query-service/internal/claims/acl_adapter.py`, `services/query-service/internal/cache/auth_cache.py`

The query service receives `X-Trusted-Claims` and `X-Claims-Sig` from the gateway.

It:

1. Base64-decodes the claims.
2. Verifies the HMAC signature.
3. Checks required fields: `user_id`, `groups`, and `clearance_level`.
4. Deduplicates and sorts groups.
5. Computes a claims hash.
6. Looks up a cached `UserContext` in Redis.
7. If cache misses, derives a new `UserContext`.

The derived `UserContext` contains:

| Field | Meaning |
| --- | --- |
| `user_id` | Stable user identifier |
| `effective_groups` | Group ACL tokens |
| `effective_clearance` | Numeric clearance level, 0 through 3 |
| `acl_tokens` | Tokens used for Elasticsearch filtering |
| `acl_key` | Deterministic hash of ACL tokens and versions |
| `claims_hash` | Deterministic hash of incoming claims and versions |

Clearance levels also add `level:0`, `level:1`, and so on up to the user's clearance. If token count exceeds `ACL_TOKEN_MAX_COUNT`, hierarchy compression is attempted using `HIERARCHY_CONFIG_PATH`.

### 5. Query Guard

Source: `services/query-service/internal/guard/*`

The guard runs before parsing and retrieval.

| Check | Behavior |
| --- | --- |
| Rate limit | Uses Redis counters and returns `429` when exceeded. |
| Injection detection | Blocks high-risk prompt-injection patterns. Medium-risk patterns are allowed but passed forward as risk signal. |
| Enumeration detection | Compares recent query history for repetitive probing patterns and can return `429`. |

If the guard passes, it returns a risk signal: `none`, `low`, `medium`, or `high`.

### 6. Query Understanding

Source: `services/query-service/internal/understanding/*`

The parser converts raw text into a `QueryContext`:

| Field | Meaning |
| --- | --- |
| `raw_query` | The original query text |
| `keywords` | Extracted keywords |
| `topic` | Optional topic such as finance, HR, engineering, legal, strategy |
| `doc_type` | Optional document type |
| `time_range` | Optional year or range |
| `intent` | `factual_lookup`, `comparison`, `policy_lookup`, `summary`, or `unknown` |
| `risk_signal` | Guard result |
| `expanded_queries` | Optional expansions |

LLM parsing and query expansion are disabled by default unless the relevant environment variables are enabled. For L2/L3 users, the code uses rules-based parsing to avoid sending sensitive queries to an external parser.

Comparison queries may be decomposed into sub-queries before retrieval.

### 7. Routing

Source: `services/query-service/internal/routing/router.py`

Routing maps user clearance and query topic to Elasticsearch indexes.

| Clearance | Accessible indexes |
| --- | --- |
| 0 | `public_index` |
| 1 | `public_index`, `internal_index` |
| 2 | `public_index`, `internal_index`, `confidential_index` |
| 3 | `public_index`, `internal_index`, `confidential_index`, `restricted_index` |

If a topic has an index affinity in `TOPIC_ROUTING_PATH`, the route can narrow to one accessible index. Otherwise it searches all accessible indexes.

kNN is disabled when routing crosses L0/L1 and L2/L3 indexes because those tiers use different embedding dimensions.

### 8. Secure Query Builder

Source: `services/query-service/internal/querybuilder/*`

The secure query builder is the only code path that assembles Elasticsearch queries.

It:

1. Gets a query embedding when kNN is allowed.
2. Falls back to BM25-only if embeddings fail or kNN is disabled.
3. Builds one query per target index.
4. Injects ACL filters into the query.
5. Asserts that ACL filters are present before returning the query.

Every query includes:

| Filter | Purpose |
| --- | --- |
| `terms: acl_tokens` | User must share at least one ACL token with the chunk. |
| `range: sensitivity_level <= effective_clearance` | User cannot retrieve above their clearance level. |

Hybrid queries place the ACL filters in both `query.bool.filter` and `knn.filter`.

### 9. Retrieval Orchestrator

Source: `services/query-service/internal/orchestrator/*`

The orchestrator:

1. Checks the Redis result cache using query text, ACL key, and target indexes.
2. Fans out Elasticsearch searches concurrently.
3. For L2/L3 users, fails closed if Elasticsearch search errors.
4. For L0/L1 users, skips failed indexes and continues.
5. Normalizes per-index scores.
6. Deduplicates by `chunk_id`.
7. Caps total candidates.
8. Stores results in Redis.

The actual Elasticsearch hit mapping is in `es_client.py`. It maps each hit into a `RetrievalCandidate` with content, citation hint, ACL key, sensitivity level, score, and source index.

### 10. Reranker

Source: `services/query-service/internal/reranker_client.py`, `services/reranker-service/*`

The query service calls the reranker only if `RERANKER_ENABLED=true`.

The client deliberately sends only:

```json
{
  "chunk_id": "...",
  "content": "..."
}
```

It strips ACL fields and other metadata before calling the reranker service. If the reranker times out, returns a server error, or is disabled, the query service keeps retrieval order.

The reranker service uses a SentenceTransformers CrossEncoder and returns ranked chunk IDs with scores. If batch scoring fails, it tries per-item scoring and marks the response as partial.

### 11. Model Gateway

Source: `services/query-service/internal/modelgateway/*`, `services/llm-stub/main.py`

The model gateway chooses a model path from the highest sensitivity level among retrieved candidates.

It:

1. Selects top chunks.
2. Strips ACL and authorization fields.
3. Truncates chunk content.
4. Builds a system prompt with document excerpts.
5. Calls an OpenAI-compatible or Anthropic-compatible endpoint.
6. Marks the answer insufficient only when the model returns exactly `Insufficient data`.
7. Returns citations based on the chunks included in the prompt.

The local `llm-stub` implements `/v1/chat/completions`. It returns `Insufficient data` when there are no document excerpts or when query words do not sufficiently match the context.

### 12. Audit

Source: `services/query-service/internal/audit/*`

After model generation, the service builds an audit event containing:

| Field | Meaning |
| --- | --- |
| `request_id` | Request correlation ID |
| `user_id` | User who asked |
| `claims_digest` | Hashed claims |
| `acl_key` | Effective ACL hash |
| `target_indexes` | Indexes searched |
| `retrieved_chunk_ids` | Retrieved chunks |
| `ranked_chunk_ids` | Reranker output order |
| `sensitivity_levels_accessed` | Sensitivity levels seen in retrieval |
| `model_path` | Model route used |
| `authorization_decision` | Allowed, denied, or fail-closed |
| `answer_returned` | Whether an answer was returned |
| `latency_ms` | Request latency |

For users at or above `AUDIT_FAIL_CLOSED_MIN_CLEARANCE`, default `2`, the service gates the response on a successful audit write. Lower-clearance responses use non-blocking audit behavior.

## Ingestion Workflow

The ingestion path is operator-facing rather than normal end-user-facing. It is implemented as Kafka workers that pass an `IngestionJob` through a sequence of topics.

```text
Source document
  -> connector
  -> parser
  -> risk scanner
  -> chunker
  -> metadata enricher
  -> ACL binder
  -> embedding worker
  -> indexer
  -> Elasticsearch
```

Kafka topic flow:

```text
ingestion.raw
  -> ingestion.parsed
  -> ingestion.scanned
  -> ingestion.chunked
  -> ingestion.enriched
  -> ingestion.acl_bound
  -> ingestion.embedded
  -> Elasticsearch
```

Failures are retried up to `MAX_RETRIES=3`, then sent to `ingestion.dlq`. Quarantined documents go to `ingestion.quarantine`.

### Connector Worker

Source: `workers/ingestion/workers/connector_worker.py`

The connector can build an `IngestionJob` from a URL or local file. For PDFs it stores bytes in `raw_content_bytes`; for text formats it stores text in `raw_content`.

Supported source types are:

```text
pdf
html
markdown
wiki_export
db_export
```

### Parser Worker

Source: `workers/ingestion/workers/parser_worker.py`

The parser converts raw content into `ParsedSection` objects.

| Source type | Parser behavior |
| --- | --- |
| `pdf` | Uses PyMuPDF to extract text by page. |
| `html` | Uses BeautifulSoup if available, otherwise raw text. |
| `markdown` | Splits content by headings. |
| `wiki_export` | Reuses markdown parsing. |
| `db_export` | Treats content as one structured text block. |

### Risk Scanner Worker

Source: `workers/ingestion/workers/risk_scanner_worker.py`

The scanner detects sensitivity labels and prompt-injection-like document content.

Sensitivity examples:

| Level | Example markers |
| --- | --- |
| 3 | `TOP SECRET`, `RESTRICTED ACCESS` |
| 2 | `CONFIDENTIAL`, `DO NOT DISTRIBUTE` |
| 1 | `INTERNAL USE ONLY`, `NOT FOR PUBLIC RELEASE` |
| 0 | No matching marker |

Some injection markers are sanitized to `[FILTERED]`. Stronger markers send the job to the quarantine topic and stop normal processing.

### Chunker Worker

Source: `workers/ingestion/workers/chunker_worker.py`

The chunker uses `tiktoken` and produces overlapping chunks. Defaults come from configuration:

```text
chunk_size_tokens = 400
chunk_overlap_tokens = 75
chunker_tokenizer = cl100k_base
```

Page number and section metadata are preserved on each chunk.

### Metadata Enricher Worker

Source: `workers/ingestion/workers/enricher_worker.py`

The enricher creates:

| Field | Behavior |
| --- | --- |
| `doc_id` | SHA-256 hash of `source_uri` |
| `chunk_id` | `{doc_id}-{chunk_index}` |
| `updated_at` | Current UTC timestamp |

The file also contains topic, document type, and year classifiers, but the current `Chunk` model does not store those fields and the worker does not currently persist them.

### ACL Binder Worker

Source: `workers/ingestion/workers/acl_binder_worker.py`

The binder expects `job.acl_policy` to already be present. It converts allowed groups and roles into ACL tokens and computes an ACL key.

If no ACL policy exists, it deliberately creates an empty ACL policy. That makes the chunks invisible to query-time ACL filters.

The repository contains `test/fixtures/acl-policies.yaml`, but the current binder code does not load or match that file by `source_pattern`.

### Embedding Worker

Source: `workers/ingestion/workers/embedding_worker.py`

The embedding worker chooses the embedding backend from document sensitivity:

| Sensitivity | Backend |
| --- | --- |
| 0 or 1 | Cloud/enterprise embedding API |
| 2 or 3 | Private embedding service |

Private embeddings are sent to `services/embedding-service` by default. The worker asserts that private chunks are under a safe sequence length before embedding.

### Indexer Worker

Source: `workers/ingestion/workers/indexer_worker.py`

The indexer routes chunks to Elasticsearch by sensitivity level:

| Sensitivity | Index |
| --- | --- |
| 0 | `public_index` |
| 1 | `internal_index` |
| 2 | `confidential_index` |
| 3 | `restricted_index` |

Each indexed document includes content, source URI, source type, sensitivity level, ACL tokens, ACL key, page, section, and vector.

## Shared Models and ACL Utilities

Source: `packages/rag-common/rag_common/*`

Shared models include:

| Model | Purpose |
| --- | --- |
| `QueryRequest` | Incoming query body |
| `QueryResponse` | Answer, citations, model path, retrieved chunk IDs, latency |
| `QueryContext` | Parsed query state used internally |
| `UserContext` | Derived user identity and ACL state |
| `RetrievalCandidate` | Search result chunk |
| `RankedCandidate` | Reranker result |
| `IngestionJob` | Document processing state across workers |
| `AuditEvent` | Audit event schema |

Shared ACL helpers compute deterministic hashes:

| Helper | Purpose |
| --- | --- |
| `compress_groups_to_tokens` | Converts groups to compact ACL tokens. |
| `compute_acl_key` | Hashes sorted ACL tokens with schema/version information. |
| `compute_claims_hash` | Hashes groups, role, clearance, and versions for auth caching. |

## How Users Interact With It

### End Users

End users interact with the query endpoint. In local development, they call the gateway stub with a mock bearer token.

Example:

```bash
curl -s http://localhost:8080/v1/query \
  -H 'Authorization: Bearer test-token-l1' \
  -H 'Content-Type: application/json' \
  -d '{"query":"What engineering guidelines are available?"}'
```

Expected response shape:

```json
{
  "request_id": "...",
  "answer": "...",
  "citations": [
    {
      "chunk_id": "...",
      "path": "...",
      "page_number": null,
      "section": "...",
      "sensitivity_level": 1,
      "source_index": "internal_index",
      "retrieval_score": 0.91
    }
  ],
  "answer_sufficient": true,
  "model_path": "...",
  "retrieved_chunk_ids": ["..."],
  "latency_ms": 123
}
```

Users cannot choose their own clearance or ACLs. Their token maps to claims, and the gateway signs those claims before the query service accepts them.

### Developers

Developers can interact with individual services:

| Service | Useful endpoint |
| --- | --- |
| gateway-stub | `GET /readyz` shows how many mock users loaded. |
| query-service | `GET /readyz` checks Redis and Elasticsearch. |
| embedding-service | `POST /v1/embed` with `{"texts":["hello"]}`. |
| reranker-service | `POST /v1/rerank` with query and candidate chunks. |
| llm-stub | `POST /v1/chat/completions` with OpenAI-style messages. |

They can also run focused tests from each component directory. The `pyproject.toml` files define pytest dev dependencies for each service.

### Operators

Operators interact with the system through deployment files and infrastructure:

| File | Purpose |
| --- | --- |
| `deploy/local/namespaces.yaml` | Local Kubernetes namespaces. |
| `deploy/local/infra.yaml` | Local Redis and Elasticsearch. |
| `deploy/local/services.yaml` | Local service deployments. |
| `deploy/kafka/kafka-cluster.yaml` | Strimzi Kafka cluster. |
| `deploy/kafka/topics.yaml` | Kafka topic declarations. |
| `deploy/local/jobs/es-init.yaml` | Elasticsearch index and alias initialization. |
| `deploy/local/jobs/audit-es-init.yaml` | Audit index initialization. |
| `deploy/charts/rag` | Helm chart skeleton and values. |

### Ingestion Operators

Ingestion operators feed source documents into the Kafka worker pipeline. In code, this means creating or receiving an `IngestionJob` and sending it to `ingestion.raw`, then letting the worker stages transform it until the indexer writes to Elasticsearch.

The current source includes worker classes but does not include a complete CLI entry point for the `seed-data` job shown in `deploy/local/jobs/seed-data.yaml`.

## Important Source Observations

These are implementation details worth reviewing because they affect how complete the current prototype is.

1. The design docs describe a full production architecture, but parts of the code are still prototype-level.
2. `services/query-service/internal/orchestrator/orchestrator.py` relies on query-time ACL filters but does not do an explicit second post-filter ACL intersection in the shown implementation.
3. `workers/ingestion/workers/acl_binder_worker.py` does not currently load `test/fixtures/acl-policies.yaml` or match policies by `source_pattern`; it expects `job.acl_policy` to be set beforehand.
4. `workers/ingestion/workers/enricher_worker.py` defines topic, doc type, and year classifiers, but those values are not persisted into the current chunk/index documents.
5. `workers/ingestion/workers/indexer_worker.py` writes `source_uri`, but query-time citation mapping reads `path`; unless mappings or seed data add `path`, citations may have an empty path.
6. `deploy/local/jobs/seed-data.yaml` references a seed command, but the current connector worker file does not expose that CLI.
7. `services/query-service/internal/querybuilder/embedding_client.py` defaults `EMBEDDING_API_URL_L2L3` to `/embed`, while the embedding service exposes `/v1/embed`; local manifests override some URLs, but the code default is inconsistent.

## Mental Model

The system has two major flows:

```text
Documents flow in through ingestion:
source -> chunks -> ACL + vectors -> Elasticsearch

Questions flow in through query:
user claims -> ACL context -> guarded query -> secure ES search -> model answer -> audit
```

The core security idea is that both flows stamp or derive ACL data, and query-time search always filters by the user's derived ACL tokens and clearance level before any answer is generated.
