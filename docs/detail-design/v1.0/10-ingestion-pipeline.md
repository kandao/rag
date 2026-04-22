# DDD v1.0 10: Ingestion Pipeline
​
## 1. Responsibilities
​
The ingestion pipeline processes raw documents from source systems through a sequential chain of stages, resulting in ACL-tagged, embedded chunks written to Elasticsearch.
​
**Stages**: Source Connector → Parser/Extractor → Risk Scanner → Chunker → Metadata Enricher → ACL Binder → Embedding Client → Indexer
​
**Deployment**: Kubernetes worker pods per stage, communicating via **Apache Kafka** topics.
​
---
​
## 2. Architecture Overview
​
```
Source
  │
  ▼
Connector Worker
  │ (raw IngestionJob → topic: ingestion.raw)
  ▼
Parser Worker
  │ (parsed IngestionJob → topic: ingestion.parsed)
  ▼
Risk Scanner Worker
  │ (scanned IngestionJob → topic: ingestion.scanned
  │                       or → topic: ingestion.quarantine)
  ▼
Chunker Worker
  │ (chunked IngestionJob → topic: ingestion.chunked)
  ▼
Metadata Enricher Worker
  │ (enriched IngestionJob → topic: ingestion.enriched)
  ▼
ACL Binder Worker
  │ (ACL-bound IngestionJob → topic: ingestion.acl_bound)
  ▼
Embedding Worker
  │ (embedded IngestionJob → topic: ingestion.embedded)
  ▼
Indexer Worker
  │
  ▼
Elasticsearch
```
​
All Kafka messages include the full `IngestionJob` serialized as JSON (see `00-conventions-contracts.md §3.6`). The `source_uri` is used as the Kafka message key to ensure ordering for a given document.
​
---
​
## 3. Message Queue (Kafka)
​
**Deployment**: Kafka cluster managed by the **Strimzi Kafka Operator** in the `kafka` namespace. Python workers use `aiokafka` (async).
​
### 3.1 Topic Definitions
​
```yaml
# Topic names
KAFKA_TOPIC_RAW:         ingestion.raw
KAFKA_TOPIC_PARSED:      ingestion.parsed
KAFKA_TOPIC_SCANNED:     ingestion.scanned
KAFKA_TOPIC_QUARANTINE:  ingestion.quarantine
KAFKA_TOPIC_CHUNKED:     ingestion.chunked
KAFKA_TOPIC_ENRICHED:    ingestion.enriched
KAFKA_TOPIC_ACL_BOUND:   ingestion.acl_bound
KAFKA_TOPIC_EMBEDDED:    ingestion.embedded
KAFKA_TOPIC_DLQ:         ingestion.dlq       # dead letter; failed after MAX_RETRIES
​
# Kafka connection
KAFKA_BOOTSTRAP_SERVERS: kafka.kafka.svc.cluster.local:9092
KAFKA_CONSUMER_GROUP:    ingestion-workers
KAFKA_SECURITY_PROTOCOL: SASL_SSL            # mTLS or SASL in production
```
​
### 3.2 Topic Configuration
​
```yaml
# Applied via Strimzi KafkaTopic CRD (deploy/kafka/topics.yaml)
# All ingestion topics share these defaults:
partitions:           3        # parallel consumers per stage
replication.factor:   2        # 2 replicas for fault tolerance (v1.0)
retention.ms:         604800000 # 7 days; enables replay without re-fetching source
retention.bytes:      -1        # unlimited within retention.ms window
​
# DLQ and quarantine: long retention for human review
ingestion.dlq:
  retention.ms: 2592000000      # 30 days
ingestion.quarantine:
  retention.ms: 2592000000      # 30 days
```
​
### 3.3 Consumer Pattern (each worker)
​
```python
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
​
async def run_worker(input_topic: str, output_topic: str):
    consumer = AIOKafkaConsumer(
        input_topic,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP,
        enable_auto_commit=False,          # manual commit after processing
        auto_offset_reset="earliest",
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
​
    async with consumer, producer:
        async for msg in consumer:
            job = IngestionJob.model_validate_json(msg.value)
            retry_count = int(msg.headers.get("retry_count", b"0"))
            try:
                result = await process(job)
                await producer.send(output_topic, value=result.model_dump_json().encode(),
                                    key=job.source_uri.encode())
                await consumer.commit()
            except Exception as e:
                if retry_count >= MAX_RETRIES:
                    await producer.send(
                        KAFKA_TOPIC_DLQ,
                        value=msg.value,
                        headers=[("failed_stage", input_topic.encode()),
                                 ("error", str(e).encode())],
                        key=job.source_uri.encode(),
                    )
                else:
                    await producer.send(
                        input_topic,
                        value=msg.value,
                        headers=[("retry_count", str(retry_count + 1).encode())],
                        key=job.source_uri.encode(),
                    )
                await consumer.commit()
```
​
**Key properties**:
- `enable_auto_commit=False` — commit only after successful downstream produce; guarantees at-least-once delivery
- Message key = `source_uri` — ensures all messages for a given document land on the same partition, preserving per-document ordering
- 7-day retention — stuck workers can be replayed without re-fetching source documents
- DLQ is a native Kafka topic — no custom tracking needed; observable via standard Kafka tooling
​
---
​
## 4. Source Connector
​
### 4.1 Supported Source Types
​
| Type | Implementation | Output |
|------|---------------|--------|
| PDF | `pypdf2` / `pdfminer` | text pages |
| HTML | `beautifulsoup4` | cleaned text |
| Markdown | `markdown-it` | AST → text blocks |
| Wiki export (Confluence) | Confluence REST API or export ZIP | pages as Markdown |
| DB export | CSV / JSON | structured rows |
​
### 4.2 Connector Output (normalized)
​
Each connector writes an `IngestionJob` with:
- `raw_content`: full text extracted from source
- `source_uri`: original URI or file path
- `source_metadata`: title, author, created_at from source system
- `source_type`: type enum
- `stage: "connector"`
​
### 4.3 Trigger Modes
​
- **Pull (scheduled)**: CronJob triggers connector at configurable interval
- **Event-driven**: webhook or watch on source system pushes job onto queue
​
Configuration:
```yaml
CONNECTOR_PULL_INTERVAL_S: 3600    # hourly
CONNECTOR_MAX_FILE_SIZE_MB: 50
CONNECTOR_SUPPORTED_MIME: ["application/pdf", "text/html", "text/markdown", "text/plain"]
```
​
---
​
## 5. Parser / Extractor
​
Converts `raw_content` into `parsed_sections` (array of `ParsedSection`).
​
```
function parse(job: IngestionJob) -> IngestionJob:
  sections = []
  match job.source_type:
    case "pdf":
      // PDF uses raw_content_bytes (binary); other formats use raw_content (text)
      sections = parse_pdf(job.raw_content_bytes)
    case "html":
      sections = parse_html(job.raw_content)
    case "markdown":
      sections = parse_markdown(job.raw_content)
    case "wiki_export":
      sections = parse_wiki(job.raw_content)
    case "db_export":
      sections = parse_structured(job.raw_content)
​
  job.parsed_sections = sections
  job.stage = "parser"
  return job
```
​
**Immutable Source Principle**: `raw_content` is never modified. All derived representations (parsed, sanitized) are separate fields.
​
### PDF Parser Details
​
```python
def parse_pdf(raw_bytes: bytes) -> list[ParsedSection]:
    reader = PdfReader(io.BytesIO(raw_bytes))
    sections = []
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text.strip():
            sections.append(ParsedSection(
                content=text,
                page_number=page_num + 1,
                section=None,
                table_cells=None
            ))
    return sections
```
​
---
​
## 6. Risk Scanner
​
Analyzes parsed content for sensitivity signals, injection patterns, and format anomalies.
​
```
function scan(job: IngestionJob) -> IngestionJob:
  max_sensitivity = 0
  flags = []
​
  for section in job.parsed_sections:
    result = scan_section(section.content)
    max_sensitivity = max(max_sensitivity, result.sensitivity_candidate)
    flags.extend(result.flags)
​
  if "quarantine" in flags:
    job.stage = "quarantined"
    enqueue(QUARANTINE_QUEUE, job)
    return None    // stop processing
​
  job.sensitivity_level = max_sensitivity
  job.stage = "risk_scanner"
  return job
```
​
### 6.1 Sensitivity Detection Rules
​
```yaml
sensitivity_rules:
  - id: SENS-001
    level: 3  # restricted
    patterns:
      - "CONFIDENTIAL - RESTRICTED"
      - "TOP SECRET"
      - "RESTRICTED ACCESS"
​
  - id: SENS-002
    level: 2  # confidential
    patterns:
      - "CONFIDENTIAL"
      - "DO NOT DISTRIBUTE"
      - "INTERNAL ONLY - CONFIDENTIAL"
​
  - id: SENS-003
    level: 1  # internal
    patterns:
      - "INTERNAL USE ONLY"
      - "NOT FOR PUBLIC RELEASE"
​
  # Default: level 0 (public) if no markers found
```
​
### 6.2 Injection Pattern Scanning
​
```yaml
injection_scan_rules:
  - id: INJ-DOC-001
    action: sanitize_chunk
    description: "LLM instruction injection in document"
    patterns:
      - "<\\|im_start\\|>system"
      - "ignore previous instructions"
      - "\\[SYSTEM\\]"
​
  - id: INJ-DOC-002
    action: quarantine
    description: "Severe injection attempt"
    patterns:
      - "OVERRIDE ALL SAFETY RULES"
```
​
For `sanitize_chunk`: the **indexed chunk** is sanitized (e.g., replacing the pattern with `[FILTERED]`). The `raw_content` in the original `IngestionJob` is not modified (Immutable Source Principle).
​
For `quarantine`: the entire job is routed to the quarantine queue.
​
### 6.3 Format Anomalies
​
- Chunk content > 800 tokens: flag and force-split
- Excessively long paragraphs (> 2000 chars with no line breaks): flag for review
- Binary or non-text content: quarantine
​
---
​
## 7. Chunker
​
Splits parsed sections into `300–500` token chunks with `50–100` token overlap.
​
```
function chunk(job: IngestionJob) -> IngestionJob:
  all_chunks = []
  for section in job.parsed_sections:
    chunks = split_into_chunks(
      text=section.content,
      chunk_size=CHUNK_SIZE_TOKENS,
      overlap=CHUNK_OVERLAP_TOKENS,
      section_label=section.section,
      page_number=section.page_number
    )
    all_chunks.extend(chunks)
​
  job.chunks = all_chunks    // replace parsed_sections with chunks
  job.stage = "chunker"
  return job
```
​
### Chunking Algorithm
​
Use `tiktoken` (for OpenAI models) or `transformers` tokenizer for token counting.
​
```python
def split_into_chunks(text, chunk_size=400, overlap=75, **meta):
    tokens = tokenizer.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens)
        chunks.append(Chunk(
            content=chunk_text,
            page_number=meta.get("page_number"),
            section=meta.get("section_label")
        ))
        start += chunk_size - overlap
    return chunks
```
​
Configuration:
```yaml
CHUNK_SIZE_TOKENS: 400
CHUNK_OVERLAP_TOKENS: 75
CHUNKER_TOKENIZER: cl100k_base    # tiktoken encoding for text-embedding-3-small
```
​
---
​
## 8. Metadata Enricher
​
Assigns required metadata fields to each chunk.
​
```
function enrich(job: IngestionJob) -> IngestionJob:
  doc_id = generate_doc_id(job.source_uri)    // SHA-256 of canonical URI
  now = utc_now()
​
  for i, chunk in enumerate(job.chunks):
    chunk.doc_id = doc_id
    chunk.chunk_id = doc_id + "-" + str(i)
    chunk.path = job.source_metadata.get("path", job.source_uri)
    chunk.topic = classify_topic(chunk.content)  // keyword matching
    chunk.doc_type = classify_doc_type(chunk.content, job.source_metadata)
    chunk.year = extract_year(chunk.content, job.source_metadata)
    chunk.source = job.source_type
    chunk.created_at = job.source_metadata.get("created_at", now)
    chunk.updated_at = now
​
  job.stage = "metadata_enricher"
  return job
```
​
---
​
## 9. ACL Binder
​
Attaches chunk-level ACL based on document-level policy.
​
```
function bind_acl(job: IngestionJob, acl_policy: ACLPolicy) -> IngestionJob:
  // acl_policy provided by caller (admin API or configuration)
  // Default: empty ACL → invisible (zero-length acl_tokens → no query-time match)
​
  if acl_policy is None or (acl_policy.allowed_groups is empty and acl_policy.allowed_roles is empty):
    // No ACL policy: chunk is invisible by default.
    // acl_key must still be computed deterministically (HLD §02 §5 — must not be empty sentinel)
    empty_acl_key = SHA-256("[]" + "|" + TOKEN_SCHEMA_VERSION + "|" + ACL_VERSION)
    for chunk in job.chunks:
      chunk.allowed_groups = []
      chunk.acl_tokens = []
      chunk.acl_key = empty_acl_key    // deterministic fingerprint of an empty ACL, not ""
      chunk.acl_version = TOKEN_SCHEMA_VERSION
    log.warn("Document has no ACL policy; all chunks will be invisible", job.source_uri)
    job.stage = "acl_binder"
    return job
​
  // Compress both groups and roles to tokens using the same rules as the query-side adapter
  // allowed_roles are separate from allowed_groups in ACLPolicy (see §00 §3.6)
  group_tokens = compress_groups_to_tokens(acl_policy.allowed_groups)
  role_tokens  = ["role:" + normalize_role(r) for r in acl_policy.allowed_roles]
  acl_tokens   = deduplicate(group_tokens + role_tokens)
  acl_key = SHA-256("|".join(sorted(acl_tokens)) + "|" + TOKEN_SCHEMA_VERSION + "|" + ACL_VERSION)
​
  for chunk in job.chunks:
    chunk.allowed_groups = acl_policy.allowed_groups
    chunk.acl_tokens = acl_tokens
    chunk.acl_key = acl_key
    chunk.acl_version = TOKEN_SCHEMA_VERSION
    chunk.sensitivity_level = job.sensitivity_level
​
  job.stage = "acl_binder"
  return job
```
​
**Token compression**: uses the same compression rules as the query-side `Claims-to-ACL Adapter` (see `02-claims-acl-adapter.md §4.3`). `allowed_roles` are compressed using the `role:` namespace (same as query-side role derivation). This ensures that query-side `acl_tokens` and document-side `acl_tokens` use the same token namespace and will produce intersection matches at query time.
​
---
​
## 10. Embedding Client
​
Generates dense vector embeddings for each chunk.
​
**Multilingual support**: Documents may be in English, Japanese, or Chinese. The L0/L1 model (`text-embedding-3-small`) is multilingual by design. The L2/L3 model must also be multilingual — `bge-m3` supports 100+ languages including ZH-S, ZH-T, and JA with the same 1024d output as the prior English-only model, requiring no index schema change.
​
```
function embed(job: IngestionJob) -> IngestionJob:
  for chunk in job.chunks:
    // Route by sensitivity level
    if chunk.sensitivity_level <= 1:
      vector = embed_cloud_batch([chunk.content], EMBEDDING_BATCH_SIZE_L0L1)[0]
    else:
      // Guard: bge-m3 max sequence length is 8192 tokens (its own tokenizer)
      // cl100k_base count is a proxy; assert conservative ceiling
      assert token_count(chunk.content) <= 7000, \
        "Chunk exceeds safe bge-m3 sequence length: " + chunk.chunk_id
      vector = embed_private_batch([chunk.content], EMBEDDING_BATCH_SIZE_L2L3)[0]
​
    chunk.vector = vector
​
  job.stage = "embedding"
  return job
```
​
```yaml
# L0/L1: OpenAI text-embedding-3-small — multilingual, cloud API
EMBEDDING_MODEL_L0L1: text-embedding-3-small
EMBEDDING_DIMS_L0L1: 1536
EMBEDDING_API_URL_L0L1: https://api-gateway.company.internal/v1/embeddings
EMBEDDING_BATCH_SIZE_L0L1: 200      # cloud API; up to 2048 inputs/request; 200 is conservative
​
# L2/L3: BGE-M3 — multilingual (EN/ZH/JA/100+ langs), self-hosted, same 1024d output
# Replaces bge-large-en-v1.5 which was English-only
EMBEDDING_MODEL_L2L3: bge-m3
EMBEDDING_DIMS_L2L3: 1024
EMBEDDING_API_URL_L2L3: http://embedding-service.retrieval-deps:8080/embed
EMBEDDING_BATCH_SIZE_L2L3: 32       # GPU memory bound (570M param model); tune per hardware
                                     # A10G (24GB): 16–32 safe; A100 (40GB): up to 64
​
EMBEDDING_TIMEOUT_MS: 30000
​
# Note on CJK chunking: cl100k_base assigns ~1 token/character for CJK, so a
# 400-token chunk covers fewer words than an equivalent English chunk. This is
# semantically acceptable for v1.0. Language-aware chunk sizing is a v1.1 item.
```
​
For local dev: `text-embedding-3-small` with `dimensions: 1024` parameter can be used for L2/L3 to avoid running a self-hosted model.
​
---
​
## 11. Indexer
​
Writes each chunk as an `ElasticsearchChunk` document.
​
```
function index(job: IngestionJob) -> void:
  target_index = sensitivity_to_index(job.sensitivity_level)
  // public_index, internal_index, confidential_index, restricted_index
​
  bulk_body = []
  for chunk in job.chunks:
    bulk_body.append({ "index": { "_index": target_index, "_id": chunk.chunk_id } })
    bulk_body.append(chunk_to_es_doc(chunk))
​
  result = es_client.bulk(bulk_body)
  if result.errors:
    log_and_raise("Bulk indexing errors", result.items)
​
  job.stage = "complete"
```
​
**Update strategy**:
- `create`: new document → `PUT /{index}/_doc/{chunk_id}`
- `update`: re-chunked document → delete old chunks by `doc_id`, bulk-create new ones
- `delete`: by `doc_id` → `DELETE_BY_QUERY { "term": { "doc_id": ... } }`
- `rebuild`: write to alias-switched index; cutover alias
​
---
​
## 12. Quarantine Handling
​
Documents in the quarantine queue are held for manual review. No automated re-ingestion.
​
A quarantine review tool (out of scope for v1.0 implementation, but the queue and schema must exist) will allow reviewers to:
1. View the quarantined document and the risk flags
2. Approve (re-inject with manual sensitivity label) or reject (discard)
​
---
​
## 13. Kubernetes Worker Specifications
​
```yaml
# Per-stage worker deployment pattern
Namespace: ingestion
Deployment per stage:
  connector-worker:     replicas=1, cpu=500m, memory=512Mi
  parser-worker:        replicas=2, cpu=1,    memory=1Gi
  risk-scanner-worker:  replicas=2, cpu=1,    memory=1Gi
  chunker-worker:       replicas=2, cpu=1,    memory=512Mi
  enricher-worker:      replicas=2, cpu=500m, memory=512Mi
  acl-binder-worker:    replicas=2, cpu=500m, memory=512Mi
  embedding-worker:     replicas=2, cpu=2,    memory=2Gi     # I/O-bound; may increase
  indexer-worker:       replicas=2, cpu=1,    memory=1Gi
```
​
---
​
## 14. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| ING-01 | PDF with 10 pages | 10+ chunks produced; page_number populated |
| ING-02 | Document with "CONFIDENTIAL" header | sensitivity_level=2; routed to confidential_index |
| ING-03 | Document with injection pattern | Chunk sanitized; [FILTERED] in indexed content; raw_content unchanged |
| ING-04 | Document with "OVERRIDE ALL SAFETY RULES" | Quarantined; not indexed |
| ING-05 | Document with no ACL policy | allowed_groups=[]; chunk invisible (acl_tokens=[]) |
| ING-06 | 100 chunks, L0 | text-embedding-3-small used; 1536d vectors |
| ING-07 | 100 chunks, L2 | Private embedding endpoint used; 1024d vectors |
| ING-08 | Blue/green rebuild | Alias cutover; zero-downtime; query error rate=0 |
| ING-09 | Concurrent embedding workers, no race | All chunks indexed; no duplicates |
| ING-10 | ACL tokens on doc-side match query-side tokens | Same compression rules → same tokens for same groups |
