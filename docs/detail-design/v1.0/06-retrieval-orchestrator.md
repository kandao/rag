# DDD v1.0 06: Retrieval Orchestrator
​
## 1. Responsibilities
​
- Fan out SecureQueryBuilder queries to one or more Elasticsearch indexes in parallel
- Collect `RetrievalCandidate` sets from each index
- Deduplicate candidates across indexes (by `chunk_id`)
- Apply candidate set size cap
- Compute the result cache key (`query_hash + acl_key`)
- Check and populate the Redis query-result cache
- Pass the authorized candidate set to the Reranker Client
​
**Not responsible for**: ACL filter assembly (SecureQueryBuilder), reranking, model invocation, or audit emission.
​
---
​
## 2. Module Location
​
```
query-service/
└── internal/
    └── orchestrator/
        ├── orchestrator.py
        ├── es_client.py         # Elasticsearch HTTP client
        ├── result_cache.py      # Redis query-result cache
        └── merger.py            # dedup + score normalization
```
​
---
​
## 3. Orchestration Flow
​
```
inputs:
  per_index_queries: list of (index_name, es_query)
  user_context: UserContext
  raw_query: string
​
[Step 1] Compute cache key
  query_hash = SHA-256(raw_query + "|" + "|".join(sorted(target_index_names)))
  cache_key = "result:" + query_hash + ":" + user_context.acl_key
​
[Step 2] Check result cache
  if redis.get(cache_key) exists:
    return cached_candidates
  // cache miss → proceed
​
[Step 3] Fan out queries to Elasticsearch in parallel
  for each (index, query) in per_index_queries:
    async es_client.search(index, query)     // parallel goroutines / asyncio tasks
​
[Step 4] Collect results
  all_candidates = []
  for each response:
    if response.error:
      log_error(response.index, response.error)
      if effective_clearance >= 2: raise ERR_RETRIEVAL_FAILED  // infrastructure failure; fail-closed for L2/L3
      // L0/L1: continue with partial results; log warning
    all_candidates.extend(map_es_hits_to_candidates(response.hits))
​
[Step 5] Deduplicate by chunk_id
  seen = {}
  deduped = []
  for c in sorted(all_candidates, key=lambda x: -x.retrieval_score):
    if c.chunk_id not in seen:
      seen[c.chunk_id] = True
      deduped.append(c)
​
[Step 6] Cap at MAX_CANDIDATES
  final_candidates = deduped[:MAX_CANDIDATES]    // default 200
​
[Step 7] Cache result
  if len(final_candidates) > 0:
    redis.set(cache_key, serialize(final_candidates), EX=RESULT_CACHE_TTL_S)
​
[Step 8] Return final_candidates
```
​
---
​
## 4. Elasticsearch Hit Mapping
​
ES returns `_source` fields as defined in SecureQueryBuilder (§_source). Map them to `RetrievalCandidate`:
​
```
function map_es_hit(hit, source_index) -> RetrievalCandidate:
  return {
    chunk_id: hit._source.chunk_id,
    doc_id: hit._source.doc_id,
    content: hit._source.content,
    citation_hint: {
      path: hit._source.path,
      page_number: hit._source.page_number,
      section: hit._source.section
    },
    topic: hit._source.topic,
    doc_type: hit._source.doc_type,
    acl_key: hit._source.acl_key,              // chunk-side; for audit only
    sensitivity_level: hit._source.sensitivity_level,
    retrieval_score: hit._score,
    source_index: source_index
  }
```
​
---
​
## 5. Score Normalization (Multi-Index Merge)
​
When candidates from multiple indexes are merged, scores may not be on the same scale (BM25 scores differ across indexes). Apply min-max normalization per index before merging:
​
```
function normalize_scores(candidates_by_index):
  result = []
  for index, candidates in candidates_by_index.items():
    scores = [c.retrieval_score for c in candidates]
    min_s, max_s = min(scores), max(scores)
    for c in candidates:
      if max_s == min_s:
        c.retrieval_score = 1.0
      else:
        c.retrieval_score = (c.retrieval_score - min_s) / (max_s - min_s)
    result.extend(candidates)
  return result
```
​
This is applied before deduplication (§3 Step 5). The reranker then re-scores from scratch, so the merged score is only used for fallback ordering.
​
---
​
## 6. Redis Query-Result Cache
​
This cache stores full `RetrievalCandidate` sets. It is **separate** from the auth cache (see `12-redis-cache.md`).
​
```
Key:    "result:{query_hash}:{acl_key}"
Value:  JSON array of RetrievalCandidate objects
TTL:    60 seconds (short; content changes are common)
Redis DB: 2  (separate from auth cache DB=0 and guard DB=1)
```
​
**Authorization binding**: the cache key includes `acl_key`, ensuring different users with different authorization contexts never share a result cache entry. Using only `query_hash` is prohibited.
​
**Cache invalidation**: TTL-based only in v1.0. When a document is re-indexed, the short TTL (60s) limits stale result exposure. [v1.1] formal invalidation via document update events.
​
```yaml
RESULT_CACHE_TTL_S: 60
RESULT_CACHE_REDIS_DB: 2
MAX_CANDIDATES_PER_INDEX: 100   # matches SecureQueryBuilder size parameter
MAX_CANDIDATES_TOTAL: 200       # post-dedup cap
```
​
---
​
## 7. Elasticsearch Client Configuration
​
```yaml
ES_HOSTS: ["https://elasticsearch.retrieval-deps:9200"]
ES_USERNAME: query-service        # from K8s Secret
ES_PASSWORD: <secret>
ES_TLS_CA_CERT_PATH: /certs/ca.crt
ES_REQUEST_TIMEOUT_MS: 5000
ES_MAX_RETRIES: 2
ES_RETRY_ON_TIMEOUT: false       # do not retry on timeout; fail-fast for sensitive paths
```
​
---
​
## 8. Failure Handling
​
| Condition | L0/L1 Behavior | L2/L3 Behavior |
|-----------|---------------|----------------|
| ES index unreachable | Return partial results from reachable indexes; warn | Fail-closed (ERR_RETRIEVAL_FAILED) |
| ES timeout | Return empty result for that index; warn | Fail-closed (ERR_RETRIEVAL_FAILED) |
| Zero candidates after merge | Return empty set; proceed to no-answer | Same |
| Redis cache write failure | Log warning; return results without caching | Same (cache is best-effort) |
​
---
​
## 9. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| ORC-01 | Single index, 50 hits | 50 RetrievalCandidates returned |
| ORC-02 | Two indexes, 60 hits each, 10 shared chunk_ids | 110 deduped candidates (60+60-10) |
| ORC-03 | Same query + same acl_key → 2nd call | Cache hit; ES not called |
| ORC-04 | Same query, different acl_key | Cache miss (different key); ES called |
| ORC-05 | ES index returns 150 hits per index, 2 indexes | Cap at 200 after dedup |
| ORC-06 | One index unreachable, L0 user | Partial results from reachable index; warning logged |
| ORC-07 | One index unreachable, L2 user | ERR_RETRIEVAL_FAILED (fail-closed; infrastructure failure distinct from zero results) |
| ORC-08 | Zero hits across all indexes | Empty candidate set; no error raised here |
| ORC-09 | allowed_groups not present in returned candidates | Confirmed via field inspection |