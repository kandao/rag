# DDD v1.0 05: SecureQueryBuilder
​
## 1. Responsibilities
​
- The **sole legitimate entry point** for constructing Elasticsearch queries in the Query Service
- Mandatorily inject ACL-aware filters (`acl_tokens` terms filter + `sensitivity_level` range filter) into every query
- Build hybrid queries (BM25 + kNN) for same-dimension tier queries; build BM25-only for cross-tier queries
- Inject optional metadata filters (topic, doc_type, year) from QueryContext
- Enforce result size limits as part of enumeration defense
- Validate that ACL filters are present before submitting any query
​
**Not responsible for**: executing queries (that is the Elasticsearch client), merging multi-index results (that is the Retrieval Orchestrator), or normalizing claims.
​
**Prohibited**:
- Accepting a raw Elasticsearch query from outside this module
- Constructing queries that omit ACL filters in any code path
- Applying ACL filters only at the `bool.filter` level without also applying them in `knn.filter`
​
---
​
## 2. Module Location
​
```
query-service/
└── internal/
    └── querybuilder/
        ├── secure_query_builder.py
        ├── acl_filter.py          # ACL filter construction
        ├── hybrid_query.py        # BM25 + kNN
        ├── bm25_only_query.py     # cross-tier fallback
        └── query_validator.py     # pre-submission validation
```
​
---
​
## 3. Query Construction Flow
​
```
inputs:
  user_context: UserContext          // acl_tokens, effective_clearance
  routing: RoutingDecision           // target_indexes, allow_knn
  query_ctx: QueryContext            // keywords, topic, doc_type, time_range
  query_embedding: float[] | null    // null when allow_knn=false or embedding unavailable
​
for each index in routing.target_indexes:
  1. build_acl_filter(user_context)     → acl_filter
  2. build_metadata_filters(query_ctx)  → metadata_filters
  3. if routing.allow_knn and query_embedding is not None:
       build_hybrid_query(...)          → es_query
     else:
       build_bm25_only_query(...)       → es_query
  4. validate_query(es_query)           → assert ACL filters present
  5. yield (index, es_query)
```
​
---
​
## 4. ACL Filter Construction
​
```
function build_acl_filter(user_context: UserContext) -> ESFilter[]:
  // MUST include both filters; neither is optional
  return [
    {
      "terms": {
        "acl_tokens": user_context.acl_tokens   // array of ≤ 30 tokens
      }
    },
    {
      "range": {
        "sensitivity_level": {
          "lte": user_context.effective_clearance
        }
      }
    }
  ]
```
​
**Invariant**: both filter clauses must always be present. If `acl_tokens` is empty, no documents match (fail-closed by design — empty terms filter returns zero results).
​
---
​
## 5. Hybrid Query (BM25 + kNN)
​
Used when `routing.allow_knn = true` and embedding vector is available.
​
```json
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "{{raw_query}}",
            "fields": ["content"],
            "boost": 0.3
          }
        }
      ],
      "filter": [
        { "terms": { "acl_tokens": ["{{token_1}}", "{{token_2}}"] } },
        { "range": { "sensitivity_level": { "lte": {{clearance}} } } },
        { "term": { "topic": "{{topic}}" } }      // omit if topic is null
        // additional metadata filters if present
      ]
    }
  },
  "knn": {
    "field": "vector",
    "query_vector": [/* embedding vector */],
    "k": 100,
    "num_candidates": 200,
    "boost": 0.7,
    "filter": {
      "bool": {
        "filter": [
          { "terms": { "acl_tokens": ["{{token_1}}", "{{token_2}}"] } },
          { "range": { "sensitivity_level": { "lte": {{clearance}} } } },
          { "term": { "topic": "{{topic}}" } }    // omit if topic is null
        ]
      }
    }
  },
  "size": 100,
  "_source": [
    "doc_id", "chunk_id", "content", "path",
    "page_number", "section", "topic", "doc_type",
    "acl_key", "sensitivity_level"
  ]
}
```
​
**Critical**: ACL filter is injected into **both** `query.bool.filter` and `knn.filter`. These branches execute independently in Elasticsearch; omitting from either leaks unauthorized chunks.
​
**Never returned in `_source`**: `allowed_groups`, `acl_tokens`, `acl_version` (these must not flow to the Reranker or Model Gateway).
​
---
​
## 6. BM25-Only Query (Cross-Tier Fallback)
​
Used when `routing.allow_knn = false` (cross-tier query spanning L0/L1 and L2/L3).
​
```json
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "{{raw_query}}",
            "fields": ["content"]
          }
        }
      ],
      "filter": [
        { "terms": { "acl_tokens": ["{{token_1}}", "{{token_2}}"] } },
        { "range": { "sensitivity_level": { "lte": {{clearance}} } } }
      ]
    }
  },
  "size": 100,
  "_source": [
    "doc_id", "chunk_id", "content", "path",
    "page_number", "section", "topic", "doc_type",
    "acl_key", "sensitivity_level"
  ]
}
```
​
The `knn` block is entirely absent. No `boost` field is needed for BM25-only.
​
---
​
## 7. Metadata Filter Construction
​
```
function build_metadata_filters(query_ctx: QueryContext) -> ESFilter[]:
  filters = []
  if query_ctx.topic is not None:
    filters.append({ "term": { "topic": query_ctx.topic } })
  if query_ctx.doc_type is not None:
    filters.append({ "term": { "doc_type": query_ctx.doc_type } })
  if query_ctx.time_range?.year is not None:
    filters.append({ "term": { "year": query_ctx.time_range.year } })
  return filters
```
​
Metadata filters are applied **in addition to** (not instead of) ACL filters.
​
---
​
## 8. Query Validator
​
Called before query submission; raises a programming error (never a user-visible error) if invariants are violated.
​
```
function validate_query(es_query):
  assert acl_tokens_filter_present(es_query.query.bool.filter),
    "INVARIANT VIOLATED: acl_tokens filter missing from bool.filter"
​
  assert sensitivity_level_filter_present(es_query.query.bool.filter),
    "INVARIANT VIOLATED: sensitivity_level filter missing from bool.filter"
​
  if es_query.knn is not None:
    assert acl_tokens_filter_present(es_query.knn.filter),
      "INVARIANT VIOLATED: acl_tokens filter missing from knn.filter"
    assert sensitivity_level_filter_present(es_query.knn.filter),
      "INVARIANT VIOLATED: sensitivity_level filter missing from knn.filter"
```
​
Validation failure raises an internal panic / fatal error (not a 400). This should be caught in CI, not production.
​
---
​
## 9. Embedding Acquisition
​
Before calling `build_hybrid_query`, the Query Service must obtain the query embedding vector.
​
```
function get_query_embedding(raw_query: string, routing: RoutingDecision) -> float[] | null:
  if not routing.allow_knn:
    return null    // skip embedding call entirely
​
  // Select model based on tier
  if all_l0_l1(routing.target_indexes):
    model_id = EMBEDDING_MODEL_L0L1
    embed_fn = embed_cloud
  else:
    model_id = EMBEDDING_MODEL_L2L3
    embed_fn = embed_private
​
  // Check embedding cache — key must include model_id to prevent cross-dimension cache hits
  // (L0/L1 uses 1536d; L2/L3 uses 1024d; same text must not share a cached vector)
  text_hash = SHA-256(raw_query)
  cache_key = "emb:" + model_id + ":" + text_hash
  cached = redis.get(cache_key)
  if cached: return cached
​
  vector = embed_fn(raw_query, model=model_id)
​
  redis.set(cache_key, vector, EX=EMBEDDING_CACHE_TTL_S)
  return vector
```
​
Configuration:
```yaml
EMBEDDING_MODEL_L0L1: text-embedding-3-small
EMBEDDING_MODEL_L2L3: bge-m3                   # self-hosted; multilingual (EN/ZH/JA/100+ langs)
# L0/L1 embedding must go through the enterprise API gateway, not directly to cloud provider
EMBEDDING_API_URL_L0L1: https://api-gateway.company.internal/v1/embeddings  # enterprise gateway
EMBEDDING_API_URL_L2L3: http://embedding-service.retrieval-deps:8080/embed   # internal only
EMBEDDING_CACHE_TTL_S: 3600
EMBEDDING_TIMEOUT_MS: 5000
```
​
---
​
## 10. Score Fusion Weights
​
```yaml
HYBRID_QUERY_VECTOR_BOOST: 0.7     # knn.boost
HYBRID_QUERY_BM25_BOOST: 0.3       # multi_match.boost
HYBRID_QUERY_K: 100                 # knn.k
HYBRID_QUERY_NUM_CANDIDATES: 200   # knn.num_candidates
QUERY_RESULT_SIZE: 100             # size parameter (enumeration defense)
```
​
---
​
## 11. Test Cases
​
| Test ID | Input | Expected ES Query |
|---------|-------|-------------------|
| SQB-01 | L1 user, L1 index, embedding available | Hybrid query with ACL in both bool.filter and knn.filter |
| SQB-02 | L3 user, all indexes, no kNN | BM25-only query; no knn block |
| SQB-03 | acl_tokens=[] (empty) | terms filter with empty array → zero results (fail-closed) |
| SQB-04 | topic=finance in QueryContext | term filter for topic included |
| SQB-05 | knn.filter missing ACL | Validator panics (caught at test time) |
| SQB-06 | Embedding API timeout | fall back to BM25-only for that query |
| SQB-07 | _source check: allowed_groups not in source | Field not present in ES response |
| SQB-08 | L1 query across L0+L1 | kNN allowed (same 1536d dims) |
| SQB-09 | L2 query across L0+L1+L2 | kNN disabled (cross-tier); BM25-only |