# RAG System

## What is RAG?

Imagine you ask an AI "What was Rocket Lab's revenue in 2025?" The model will either make something up or say it doesn't know — because that data isn't in its training data. **RAG (Retrieval-Augmented Generation)** solves this by giving the AI a private library to look things up in before it answers. Instead of answering from memory, the model first retrieves the relevant document excerpts and then generates an answer grounded in those excerpts.

This system is a production-grade RAG built for querying SEC 10-K filings (annual financial reports).

---

## System Overview

The system has two phases: **Ingestion** (loading documents into the library) and **Query** (answering user questions).

### Phase 1 — Ingestion

Before any user can ask a question, documents are prepared and stored in Elasticsearch. Each file goes through a pipeline:

```
Raw document (PDF / Markdown)
        ↓
   [1] Parse      — extract clean text from the file
        ↓
   [2] Risk scan  — check for secrets or sensitive content; quarantine if flagged
        ↓
   [3] Chunk      — split text into small pieces (~500 words each)
        ↓
   [4] Enrich     — tag each chunk with metadata (company, ticker, year, topic)
        ↓
   [5] ACL bind   — attach access control (who is allowed to see this chunk)
        ↓
   [6] Embed      — convert each chunk into a vector (~1536 numbers representing meaning)
        ↓
   [7] Index      — store chunk text + vector into Elasticsearch
```

**Why chunk?** A 100-page PDF is too large to hand to an AI model. Cutting it into small pieces lets you find just the relevant paragraph instead of dumping the whole document.

**Why embed?** A vector is a mathematical representation of meaning. Two chunks that mean similar things will have vectors that are "close" to each other in space. This makes semantic search possible — the query "How profitable was RKLB?" and the chunk "Rocket Lab gross margin was 28%" will have similar vectors even if they share no exact words.

The ingestion pipeline lives in `workers/ingestion/pipeline/` — each step is its own file (`parse.py`, `chunk.py`, `enrich.py`, `embed.py`, `index.py`).

---

### Phase 2 — Query

When a user asks a question, it flows through several services in sequence:

```
User question
      ↓
[Gateway]       — authenticate the user, sign their identity claims
      ↓
[Query service] — orchestrates everything below
      ↓
  ┌────────────────────────────────────────┐
  │  [1] Guard     rate-limit check        │
  │  [2] Parser    understand intent       │
  │  [3] Expander  split comparison query  │
  │  [4] Router    pick ES index(es)       │
  │  [5] Embedder  vectorize the query     │
  │  [6] ES search hybrid BM25 + kNN      │
  │  [7] Reranker  re-score chunks         │
  │  [8] Context   select top-N chunks     │
  │  [9] LLM       generate answer         │
  │ [10] Audit     log everything          │
  └────────────────────────────────────────┘
      ↓
  Answer + citations → user
```

**[1] Guard** — checks rate limits. Protects against abuse before doing any expensive work.

**[2] Parser** (`services/query-service/internal/understanding/parser_rules.py`) — extracts structured info from the raw question: keywords, time range, and intent (factual lookup, comparison, summary, etc.).

**[3] Expander** — if the query is a comparison ("compare 2024 vs 2025"), it splits it into sub-queries and runs each separately, then merges the candidates.

**[4] Router** — decides which Elasticsearch index to search. Separate indexes exist for L0/L1 (public) and L2/L3 (sensitive) documents. Your clearance level determines which indexes you can query.

**[5] Embed query** — the same embedding model used at ingestion time converts the question into a vector. It must be the same model as ingestion — otherwise the vectors are in different "spaces" and similarity comparisons break.

**[6] Hybrid search** (`services/query-service/internal/querybuilder/hybrid_query.py`) — runs two searches simultaneously and combines their scores:
- **BM25** (keyword search) — classic "does this chunk contain the word 'revenue'?" with field boosts: ticker (8×), company (5×), section (2×), content (3×).
- **kNN** (vector search) — finds chunks whose *meaning* is similar to the query, even if they use different words.

An ACL filter is applied to both — you only see chunks your clearance permits.

**[7] Reranker** (`services/reranker-service/reranker.py`) — a CrossEncoder model reads each (query, chunk) pair *together* and produces a more accurate relevance score. BM25/kNN score each side independently; CrossEncoder compares them jointly. This is slower but significantly more accurate, especially when the correct chunk uses different vocabulary than the query.

**[8] Context builder** (`services/query-service/internal/modelgateway/context_builder.py`) — selects the top-N chunks (default: 5 for L0/L1, 3 for L2/L3) and formats them into a system prompt. The model never sees chunks beyond this window.

**[9] LLM generation** — the model receives the system prompt (containing the selected document excerpts) and the user's question, then generates an answer. It is instructed to cite sources, only use the provided excerpts, and respond "Insufficient data" if the answer isn't there.

**[10] Audit log** — every query, every retrieved chunk, the answer, and latency are written back to Elasticsearch for a full audit trail.

---

## Services

Each component runs as its own Kubernetes pod:

| Service | What it does |
|---|---|
| `gateway-stub` | Auth gateway — signs user identity before passing requests to query-service |
| `query-service` | The orchestrator — runs all 10 query steps above |
| `embedding-service` | Converts text to vectors (used by both ingestion and query) |
| `reranker-service` | CrossEncoder re-scoring of retrieved chunks |
| `ingestion-worker` | Processes documents through the 7-step ingestion pipeline |
| Elasticsearch | Stores chunks, vectors, and ACL metadata; handles both BM25 and kNN search |
| Redis | Caches auth tokens and query embeddings to avoid repeat API calls |

`packages/rag-common` is a shared Python package that defines the data models all services agree on — `Chunk`, `QueryContext`, `RetrievalCandidate`, etc.

---

# RAG Local Development

This repository has two local Helm profiles:

- `local_test`: deterministic E2E stack using stubbed LLM responses.
- `local`: real-provider stack using local Elasticsearch/Redis plus external OpenAI LLM and embedding APIs.

## Prerequisites

- A local Kubernetes cluster, such as OrbStack, with the current `kubectl` context pointing at that cluster.
- Docker available to the same local cluster image store.
- Helm 3.
- Python 3.11+ with the project dependencies installed. The documented commands use `${PYTHON:-python}`; set `PYTHON` to a virtualenv interpreter path when needed.

## Build Local Images

For the OpenAI-backed `local` profile, build the app images that are deployed by that profile:

```bash
docker build -t rag/query-service:dev -f services/query-service/Dockerfile .
docker build -t rag/gateway-stub:dev -f services/gateway-stub/Dockerfile .
```

For `local_test`, also build the stub/support images used by that deterministic profile:

```bash
docker build -t rag/embedding-service:dev -f services/embedding-service/Dockerfile .
docker build -t rag/reranker-service:dev -f services/reranker-service/Dockerfile .
docker build -t rag/llm-stub:dev -f services/llm-stub/Dockerfile .
```

## Run `local_test`

Use `local_test` for repeatable E2E runs that do not call real external model APIs.

Create the ignored local secret file if it does not exist:

```bash
cp deploy/charts/rag/values-local_test.secret.example.yaml deploy/charts/rag/values-local_test.secret.yaml
```

Deploy:

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local_test.yaml \
  -f deploy/charts/rag/values-local_test.secret.yaml
```

Port-forward the gateway:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Run the deterministic E2E suite:

```bash
PYTHONPATH=packages/rag-common:services/query-service \
  ${PYTHON:-python} \
  -m pytest services/query-service/tests/e2e -q
```

## Run `local`

Use `local` when you want the deployed stack to call real OpenAI LLM and embedding APIs. Elasticsearch and Redis still run locally in Kubernetes.

Create the ignored local secret file if it does not exist:

```bash
cp deploy/charts/rag/values-local.secret.example.yaml deploy/charts/rag/values-local.secret.yaml
```

Fill these values in `deploy/charts/rag/values-local.secret.yaml`:

```yaml
MODEL_API_KEY_L0L1: replace-with-openai-api-key
MODEL_API_KEY_L2: replace-with-openai-api-key
MODEL_API_KEY_L3: replace-with-openai-api-key
EMBEDDING_API_KEY_L0L1: replace-with-openai-api-key
EMBEDDING_API_KEY_L2L3: replace-with-openai-api-key
```

For the local chart, Elasticsearch auth stays blank because local Elasticsearch runs with security disabled:

```yaml
ES_USERNAME: ""
ES_PASSWORD: ""
AUDIT_ES_USERNAME: ""
AUDIT_ES_PASSWORD: ""
```

Deploy:

```bash
helm upgrade --install rag-system deploy/charts/rag \
  -f deploy/charts/rag/values-local.yaml \
  -f deploy/charts/rag/values-local.secret.yaml \
  --set global.createNamespaces=false
```

Port-forward the gateway:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Smoke test with the mock L1 user:

```bash
curl -sS http://127.0.0.1:8080/v1/query \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-token-l1' \
  -d '{"query":"What does the product overview say?","top_k":5}'
```

## Secret Hygiene

The real secret override files are ignored by git:

```bash
git check-ignore -v deploy/charts/rag/values-local.secret.yaml
git check-ignore -v deploy/charts/rag/values-local_test.secret.yaml
```

Commit only `*.secret.example.yaml` files.
