# Local Ingestion Development Plan

## Goal

Make local development able to ingest a small set of real documents, create real
OpenAI embeddings, index them into Elasticsearch, and then run RAG eval questions
against the existing gateway/query-service path.

Target local flow:

```text
local files
  -> parse
  -> risk scan
  -> chunk
  -> enrich metadata
  -> bind ACL
  -> call OpenAI embeddings
  -> bulk index into Elasticsearch
  -> run RAG eval through gateway-stub/query-service
```

## Current State

The ingestion worker code exists under `workers/ingestion`, but the local Helm profile
does not deploy it:

- `deploy/charts/rag/values.yaml` has `services.ingestionWorker.enabled=false`.
- `deploy/charts/rag/values-local.yaml` configures the ingestion worker image/env, but
  does not set `enabled=true`.
- The worker classes are currently Kafka consumer workers. Their constructors create
  Kafka consumers/producers, so they are not convenient to run directly for a local
  file-seeding command.
- `deploy/local/jobs/seed-data.yaml` references a seed CLI, but the source-code notes say
  the current repo does not expose a complete CLI entry point for that job.

Because of this, local testing currently depends on data already being present in
Elasticsearch.

## Design Choice

Build the local ingestion path first as a direct runner, not as Kafka.

Reason:

- The user need is to feed several documents and test RAG/eval locally.
- Kafka is useful for production-like ingestion, but it adds deployment and debugging
  surface before the document-to-Elasticsearch path is proven.
- The direct runner can reuse the same stage logic as the Kafka workers after we extract
  stage processing into importable functions.

The Kafka workers should remain the long-term production shape. The direct runner is the
local/dev entry point.

## Phase 1: Extract Reusable Stage Logic

Refactor each ingestion worker so the transformation logic is callable without creating
a Kafka consumer.

Create pure or dependency-light functions, for example:

```text
workers/ingestion/pipeline/
  parse.py
  risk_scan.py
  chunk.py
  enrich.py
  acl_bind.py
  embed.py
  index.py
  runner.py
```

Keep the existing Kafka workers, but make them thin wrappers:

```text
Kafka message -> IngestionJob -> pipeline function -> next Kafka topic
```

Acceptance criteria:

- Unit tests can call each stage without Kafka.
- Existing worker unit tests still pass.
- No stage opens network connections in its constructor.

## Phase 2: Add Local File Ingestion CLI

Add a CLI entry point that runs the whole pipeline in-process for a folder of local files.

Proposed command:

```bash
PYTHONPATH=packages/rag-common:workers/ingestion \
  /Users/chengtaowu/Desktop/AiWorkSpace/learn-claude-code/bin/python \
  -m ingestion_local ingest \
  --input deploy/charts/rag/files/fixtures/documents \
  --acl-policy deploy/charts/rag/files/fixtures/acl-policies.yaml \
  --es-url http://127.0.0.1:9200 \
  --embedding-provider openai
```

The CLI should support:

- `--input`: file or directory.
- `--glob`: optional file pattern, defaulting to markdown/text files first.
- `--acl-policy`: YAML policy file.
- `--default-clearance`: fallback sensitivity/clearance if no rule matches.
- `--dry-run`: print jobs/chunks without calling OpenAI or Elasticsearch.
- `--limit`: ingest only the first N files for cost control.
- `--force-reindex`: overwrite existing chunk IDs.

Acceptance criteria:

- Running with `--dry-run` produces parsed chunks and ACL metadata.
- Running without `--dry-run` calls OpenAI embeddings and writes chunks to Elasticsearch.
- The command exits non-zero on failed embedding or failed ES bulk write.

## Phase 3: Create / Verify Elasticsearch Indexes Locally

The local real-provider profile needs vector dimensions matching current OpenAI config:

| Index alias | Sensitivity | Vector dims |
|---|---:|---:|
| `public_index` | 0 | 1536 |
| `internal_index` | 1 | 1536 |
| `confidential_index` | 2 | 1024 |
| `restricted_index` | 3 | 1024 |

Add a local command or Helm job to create:

- physical indexes: `public_index_v1`, `internal_index_v1`, `confidential_index_v1`,
  `restricted_index_v1`;
- aliases: `public_index`, `internal_index`, `confidential_index`, `restricted_index`;
- audit index alias: `audit-events-current`.

Acceptance criteria:

- `curl http://127.0.0.1:9200/_cat/aliases?v` shows all required aliases.
- Re-running init is safe or clearly reports already-existing indexes.

## Phase 4: ACL Policy Binding That Works For Fixtures

Implement local ACL policy selection from `acl-policies.yaml`.

Current issue:

- `ACLBinderWorker` expects `job.acl_policy` to already be set in some cases.
- For local file ingestion, the runner must choose a policy by source path, metadata, or
  a CLI-provided default.

Plan:

- Load `acl-policies.yaml`.
- Match policy by source path/pattern.
- Compute `acl_tokens` and `acl_key`.
- Ensure document `acl_tokens` contain group/role tokens that query-time user contexts
  can match.

Acceptance criteria:

- A `test-token-l1` user can retrieve L1/internal seeded docs.
- A lower-clearance user cannot retrieve confidential/restricted docs.
- Seeded document ACL tokens do not accidentally include only synthetic `level:*` tokens.

## Phase 5: Embedding Worker Behavior

Use OpenAI embeddings for local real-provider ingestion:

```text
L0/L1 -> text-embedding-3-small, 1536 dims
L2/L3 -> text-embedding-3-small, 1024 dims
```

Implementation details:

- Reuse the existing `_embed_openai` behavior from
  `workers/ingestion/workers/embedding_worker.py`.
- Add batching and cost controls.
- Log document count, chunk count, model, dimensions, and elapsed time.
- Do not log API keys or full document text.

Acceptance criteria:

- Indexed chunks include a non-empty `vector`.
- Vector length matches target index mapping.
- A query through `query-service` uses hybrid retrieval instead of falling back to BM25-only.

## Phase 6: Indexing Behavior

Make indexing produce the fields query-service actually reads:

```text
chunk_id
doc_id
content
path
page_number
section
topic
doc_type
acl_key
acl_tokens
acl_version
sensitivity_level
vector
created_at
updated_at
```

Current issue:

- `IndexerWorker` writes `source_uri`, while query-service citation mapping reads `path`.

Plan:

- Include both `source_uri` and `path`.
- Preserve stable `doc_id` and `chunk_id` so reindexing is deterministic.
- Route by sensitivity level:
  - `0 -> public_index`
  - `1 -> internal_index`
  - `2 -> confidential_index`
  - `3 -> restricted_index`

Acceptance criteria:

- Direct ES search shows seeded chunks.
- Query citations include usable `path` values.
- Re-running ingestion for the same file updates/replaces the same chunk IDs.

## Phase 7: Local Runbook And Eval

Update `docs/test/e2e-local-real-provider-runbook.md` with:

1. Start port-forwards.
2. Initialize Elasticsearch aliases.
3. Run local ingestion CLI.
4. Verify data readiness.
5. Run manual query.
6. Run retrieval and answer eval tests.

Add a small eval fixture:

```text
docs/eval/local-real-provider/
  questions.yaml
  expected_citations.yaml
```

Acceptance criteria:

- A developer can add 3-5 local docs and run a documented command.
- Data readiness checks pass.
- At least one real-world question returns a cited answer through `/v1/query`.

## Phase 8: Optional Kafka Deployment

After the direct local runner works, decide whether to enable Kafka-backed ingestion locally.

Difficulty estimate:

- Adding Kafka after the direct local runner works: 2-4 focused development days.
- Adding Kafka before the direct local runner works: 4-7 focused development days.

The extra cost of doing Kafka first is debugging ambiguity. A failure could be caused by
Kafka deployment, topic wiring, worker lifecycle, stage transformation logic, OpenAI
embedding calls, ACL binding, or Elasticsearch indexing. Once the direct runner proves the
document-to-Elasticsearch path, Kafka work becomes mostly orchestration.

Tasks:

- Add Kafka dependency to the local profile only if needed.
- Set `services.ingestionWorker.enabled=true`.
- Add separate deployments/commands per worker stage, not one ambiguous worker image.
- Add a simple producer command to publish file jobs into `ingestion.raw`.
- Add topic creation/readiness checks for:
  - `ingestion.raw`
  - `ingestion.parsed`
  - `ingestion.scanned`
  - `ingestion.quarantine`
  - `ingestion.chunked`
  - `ingestion.enriched`
  - `ingestion.acl_bound`
  - `ingestion.embedded`
  - `ingestion.dlq`
- Add basic DLQ and retry visibility for local debugging.
- Add an integration test that publishes one local document and verifies the final chunk
  exists in Elasticsearch.

Target Kafka flow:

```text
local file producer
  -> ingestion.raw
  -> parser worker
  -> ingestion.parsed
  -> risk scanner worker
  -> ingestion.scanned / ingestion.quarantine
  -> chunker worker
  -> ingestion.chunked
  -> enricher worker
  -> ingestion.enriched
  -> acl binder worker
  -> ingestion.acl_bound
  -> embedding worker
  -> ingestion.embedded
  -> indexer worker
  -> Elasticsearch
```

Acceptance criteria:

- Kafka path indexes the same document shape as the direct runner.
- Direct runner remains available for fast local development.
- Each Kafka worker reuses the same pipeline functions as the direct runner.
- A developer can inspect topic lag, worker logs, and DLQ messages during local runs.

## Proposed Milestones

1. Local pipeline functions and dry-run CLI.
2. OpenAI embedding and ES bulk indexing from local files.
3. Runbook and data readiness checks.
4. RAG eval questions against seeded local documents.
5. Optional Kafka-backed local ingestion.

## Development Todo

Status legend:

- `[ ]` not started
- `[~]` in progress
- `[x]` complete

Implementation checklist:

- `[x]` Extract reusable ingestion pipeline functions that can run without Kafka.
- `[x]` Keep existing Kafka workers as thin wrappers around the reusable functions.
- `[x]` Add a local ingestion CLI runnable with `python -m ingestion_local`.
- `[x]` Support dry-run ingestion for markdown/text fixtures without OpenAI or Elasticsearch.
- `[x]` Support real OpenAI embedding calls for L0/L1 and L2/L3 vector dimensions.
- `[x]` Bulk index embedded chunks into the existing local Elasticsearch aliases.
- `[x]` Include all fields query-service reads: `chunk_id`, `doc_id`, `content`, `path`,
  `page_number`, `section`, `topic`, `doc_type`, `acl_key`, `acl_tokens`,
  `acl_version`, `sensitivity_level`, `vector`, `created_at`, and `updated_at`.
- `[x]` Match local ACL policy rules from `acl-policies.yaml` by source-relative path.
- `[x]` Add focused unit tests for the direct pipeline and CLI behavior.
- `[x]` Update `docs/test/e2e-local-real-provider-runbook.md` with local ingestion commands.
- `[ ]` Add local eval fixtures after sample documents are indexable.
- `[ ]` Defer Kafka deployment until direct ingestion proves document-to-Elasticsearch behavior.

Kafka follow-up checklist:

- `[ ]` Add Kafka dependency to the local profile only after direct local ingestion works.
- `[ ]` Enable `services.ingestionWorker.enabled=true` when ready to test Kafka workers.
- `[ ]` Add per-stage worker deployments or commands.
- `[ ]` Add a file producer command for `ingestion.raw`.
- `[ ]` Add topic creation/readiness checks and DLQ visibility.
- `[ ]` Add an integration test from one Kafka message to final Elasticsearch chunk.

## First Implementation Slice

Start with the narrowest runnable path:

1. Create reusable pipeline functions for markdown/text files only.
2. Add a local CLI that ingests a directory of markdown files.
3. Generate OpenAI embeddings.
4. Bulk index into existing local Elasticsearch aliases.
5. Verify a query through gateway-stub returns citations.

PDF parsing, Kafka deployment, source connectors, and production-style scheduling can come
after this path is working.
