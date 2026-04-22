# DDD v1.0 12: Redis Cache Layer
​
## 1. Responsibilities
​
Redis serves three independent caching purposes in v1.0. Each uses a separate logical database to avoid key collisions.
​
| DB | Purpose | Key Pattern | TTL |
|----|---------|-------------|-----|
| DB 0 | ACL authorization cache | `acl:{claims_hash}` | 300s |
| DB 1 | Query Guard state (rate limit + enum history) | `guard_rl:{user_id}`, `guard_hist:{user_id}` | 60–300s |
| DB 2 | Query result cache | `result:{query_hash}:{acl_key}` | 60s |
| DB 3 | Embedding cache | `emb:{model_id}:{text_hash}` | 3600s |
​
The API Gateway rate-limiting (Kong plugin) uses a separate Redis instance or DB; it is not covered in this document.
​
---
​
## 2. Cluster Configuration
​
```
Namespace: retrieval-deps
Deployment: redis (single node in v1.0; Redis Sentinel or Cluster for production)
  Image: redis:7.2-alpine
  Port: 6379
  Memory: 4Gi
  Storage: 10Gi PersistentVolume (for AOF / RDB snapshots)
​
Service: redis.retrieval-deps:6379 (ClusterIP)
```
​
### 2.1 Redis Configuration (`redis.conf`)
​
```conf
maxmemory 3gb
maxmemory-policy allkeys-lru     # evict least-recently-used when near limit
appendonly yes                   # AOF persistence for durability
appendfsync everysec
save 900 1                       # RDB snapshot: if 1 key changed in 900s
save 300 10
bind 0.0.0.0
requirepass ${REDIS_PASSWORD}    # injected from K8s Secret
```
​
---
​
## 3. DB 0: ACL Authorization Cache
​
**Purpose**: Avoid re-running group expansion and token compression on every request for the same user.
​
**Key**: `acl:{claims_hash}` where `claims_hash = SHA-256(sorted_groups + "|" + role + "|" + clearance_level + "|" + TOKEN_SCHEMA_VERSION + "|" + ACL_VERSION)`
​
**Value** (JSON string):
```json
{
  "acl_tokens": ["group:eng", "group:infra", "role:manager", "level:2"],
  "acl_key": "sha256-hex",
  "effective_clearance": 2,
  "cached_at": "2024-01-15T10:30:00Z",
  "token_schema_version": "v1",
  "acl_version": "v1"
}
```
​
**TTL**: 300 seconds
​
**Cache invalidation**: by design, bumping `TOKEN_SCHEMA_VERSION` or `ACL_VERSION` changes the `claims_hash` computation, making all existing entries unreachable. Old entries expire naturally within 300s. No explicit `DEL` is needed for global schema changes.
​
**Read/Write pattern**:
```
read:  redis.get("acl:" + claims_hash)
write: redis.set("acl:" + claims_hash, json_value, ex=300)
```
​
---
​
## 4. DB 1: Query Guard State
​
### 4.1 Rate Limit Counter
​
```
Key: "guard_rl:{user_id}"
Value: integer (request count)
TTL: 60 seconds (sliding window via expire-on-first-write)
```
​
```
write: redis.incr("guard_rl:" + user_id)
       if result == 1: redis.expire("guard_rl:" + user_id, 60)
read:  implicitly via incr (no separate read)
```
​
### 4.2 Enumeration History
​
```
Key:   "guard_hist:{user_id}"
Value: Redis List, each element = query string (last 10 queries)
TTL:   300 seconds
```
​
```
write: redis.lpush("guard_hist:" + user_id, query)
       redis.ltrim("guard_hist:" + user_id, 0, 9)
       redis.expire("guard_hist:" + user_id, 300)
read:  redis.lrange("guard_hist:" + user_id, 0, 9)
```
​
---
​
## 5. DB 2: Query Result Cache
​
**Purpose**: Avoid redundant Elasticsearch + Reranker calls for identical (query, authorization context) pairs.
​
**Key**: `result:{query_hash}:{acl_key}` where `query_hash = SHA-256(raw_query + "|" + "|".join(sorted(target_indexes)))`
​
**Value**: JSON-serialized array of `RetrievalCandidate` objects (with content)
​
**TTL**: 60 seconds (short; indexed content changes frequently)
​
**Authorization binding**: the `acl_key` component ensures users with different authorization contexts never share a result cache entry.
​
**Size considerations**: a RetrievalCandidate array of 200 items with 500-token content per chunk can be ~200KB. With 1000 concurrent users and 50% cache hit rate, total cache size ≈ 200KB × 1000 = 200MB for this DB. Fits comfortably within the 3GB `maxmemory` limit.
​
---
​
## 6. DB 3: Embedding Cache
​
**Purpose**: Avoid re-embedding identical query text.
​
**Key**: `emb:{model_id}:{text_hash}` where `text_hash = SHA-256(query_text)`
​
The key **must include `model_id`** to prevent cross-dimension cache collisions. L0/L1 uses `text-embedding-3-small` (1536d) and L2/L3 uses `bge-m3` (1024d). Without `model_id` in the key, a 1536d vector cached for an L0/L1 query could be incorrectly returned for the same text on an L2/L3 path (different dimension → invalid kNN query).
​
**Value**: JSON-serialized float array (e.g., 1536 floats for L0/L1 ≈ 12KB per entry)
​
**TTL**: 3600 seconds (1 hour)
​
**Note**: this cache does not need ACL binding because the embedding is a pure function of (text, model); the same (text, model) pair always produces the same vector regardless of who is asking.
​
---
​
## 7. Kubernetes Deployment
​
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: retrieval-deps
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    spec:
      containers:
        - name: redis
          image: redis:7.2-alpine
          ports:
            - containerPort: 6379
          command: ["redis-server", "/etc/redis/redis.conf"]
          resources:
            requests:
              cpu: "500m"
              memory: "4Gi"
            limits:
              cpu: "1"
              memory: "4Gi"
          volumeMounts:
            - name: config
              mountPath: /etc/redis
            - name: data
              mountPath: /data
          env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: redis-secret
                  key: password
      volumes:
        - name: config
          configMap:
            name: redis-config
        - name: data
          persistentVolumeClaim:
            claimName: redis-data-pvc
```
​
---
​
## 8. Network Policy
​
```yaml
NetworkPolicy (redis):
  ingress:
    - from namespace=query (DB 0, 2, 3)
    - from namespace=ingestion (DB 3: embedding cache)
    - from namespace=api-gateway (rate limiting, if sharing this Redis)
  egress: none (Redis does not call out)
```
​
---
​
## 9. Circuit Breaker Pattern
​
All Redis clients must implement a circuit breaker:
​
```
function redis_get_with_circuit(key):
  if circuit_state == OPEN:
    return None    // fail open: skip cache; compute directly
  try:
    return redis.get(key, timeout=REDIS_TIMEOUT_MS)
  catch timeout, connection_error:
    increment_failure_count()
    if failure_count > CIRCUIT_OPEN_THRESHOLD:
      circuit_state = OPEN
      schedule_half_open(CIRCUIT_RESET_TIMEOUT_S)
    return None
```
​
Configuration:
```yaml
REDIS_TIMEOUT_MS: 100
CIRCUIT_OPEN_THRESHOLD: 5       # failures before opening circuit
CIRCUIT_RESET_TIMEOUT_S: 30
```
​
When Redis is unavailable:
- DB 0 (auth cache): fall open; full ACL derivation runs
- DB 1 (guard): rate limiting and enumeration detection degrade; injection detection (in-memory patterns) still works
- DB 2 (result cache): fall open; always query ES
- DB 3 (embedding cache): fall open; always call embedding API
​
---
​
## 10. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| REDIS-01 | Same claims_hash → 2 requests | 2nd request hits DB 0 cache; ACL derivation skipped |
| REDIS-02 | TOKEN_SCHEMA_VERSION bumped | Old cache entries unreachable (different hash); re-derived |
| REDIS-03 | Same query + acl_key → 2 requests within 60s | 2nd hits DB 2 result cache |
| REDIS-04 | Same query, different acl_key | Different cache key; ES called again |
| REDIS-05 | Same query text + same model → embedding cache hit | DB 3 hit; embedding API not called |
| REDIS-06 | Redis DB 0 unavailable | ACL derivation runs; no error returned to user |
| REDIS-07 | DB 1 unavailable | Rate limiting skipped; injection detection (in-memory) still active |
| REDIS-08 | DB 2 unavailable | ES always queried; no 500 error |
| REDIS-09 | maxmemory limit reached | LRU eviction; no OOM; old entries evicted first |
| REDIS-10 | 1536d embedding stored under `text-embedding-3-small` key, same text on L2L3 path | Cache miss (different model_id key `bge-m3`); L2/L3 embedding computed separately |
