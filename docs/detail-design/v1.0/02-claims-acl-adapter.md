# DDD v1.0 02: Claims Normalizer and Claims-to-ACL Adapter
​
## 1. Responsibilities
​
**Claims Normalizer**:
- Parse and validate the `X-Trusted-Claims` header forwarded by the API Gateway
- Verify the HMAC signature
- Deduplicate and sort the `groups` array
- Validate that all required fields are present and within expected ranges
​
**Claims-to-ACL Adapter**:
- Convert normalized claims into `acl_tokens` (bounded ≤ 30)
- Compute `acl_key = SHA-256(sorted_acl_tokens + token_schema_version + acl_version)`
- Compute `claims_hash` (Redis auth-cache lookup key)
- Apply group hierarchy compression when token count exceeds the limit
- Read from / write to Redis auth-cache
​
**Not responsible for**: Elasticsearch query assembly, routing decisions, or authorization result evaluation.
​
---
​
## 2. Module Location
​
Both components run **inside the Query Service process** as internal modules, not separate microservices. They execute on every query before any downstream call.
​
```
query-service/
└── internal/
    ├── claims/
    │   ├── normalizer.py
    │   └── acl_adapter.py
    └── cache/
        └── auth_cache.py
```
​
---
​
## 3. Claims Normalizer
​
### 3.1 Input
​
The raw `X-Trusted-Claims` header value (base64-encoded JSON) and `X-Claims-Sig` (HMAC-SHA256 hex).
​
### 3.2 Algorithm
​
```
function normalize_claims(header_value, sig_header):
  1. base64_decode(header_value) → claims_json
  2. verify HMAC-SHA256(claims_json, CLAIMS_SIGNING_KEY) == sig_header
     → if mismatch: raise ERR_AUTH_UNTRUSTED_CLAIMS
  3. parse claims_json → raw_claims
  4. validate required fields: [user_id, groups, clearance_level]
     → if any missing: raise ERR_AUTH_MISSING_CLAIMS
  5. validate clearance_level ∈ {0, 1, 2, 3}
     → if out of range: raise ERR_AUTH_MISSING_CLAIMS
  6. deduplicate groups: sorted(set(raw_claims.groups))
  7. return NormalizedClaims {
       user_id: raw_claims.user_id,    // gateway already normalized sub → user_id before forwarding
       groups: deduplicated_sorted_groups,
       role: raw_claims.role ?? null,
       clearance_level: raw_claims.clearance_level
     }
```
​
### 3.3 Configuration
​
```yaml
CLAIMS_SIGNING_KEY_SECRET: api-gateway-claims-key   # K8s Secret name; mounted as env var
CLAIMS_SIGNING_ALGO: HS256
```
​
---
​
## 4. Claims-to-ACL Adapter
​
### 4.1 Redis Auth-Cache Check (First)
​
Before running full derivation:
​
```
claims_hash = SHA-256(
  sorted(raw_groups)
  + "|" + role
  + "|" + clearance_level
  + "|" + TOKEN_SCHEMA_VERSION
  + "|" + ACL_VERSION
)
​
cache_key = "acl:" + claims_hash
​
if redis.get(cache_key) exists and not expired:
  return cached { acl_tokens, acl_key, effective_clearance }
else:
  run full derivation (§4.2)
  redis.set(cache_key, result, EX=300)
  return result
```
​
### 4.2 Full Token Derivation Algorithm
​
```
function derive_acl_tokens(normalized_claims):
  raw_tokens = []
​
  for each group in normalized_claims.groups:
    token = compress_group(group)      // see §4.3
    if token is not None:
      raw_tokens.append(token)
​
  if normalized_claims.role is not None:
    raw_tokens.append("role:" + normalize_role(normalized_claims.role))
​
  raw_tokens.append("level:" + str(normalized_claims.clearance_level))
​
  raw_tokens = deduplicate(raw_tokens)
​
  if len(raw_tokens) > 30:
    raw_tokens = apply_hierarchy_compression(raw_tokens)  // see §4.4
    if len(raw_tokens) > 30:
      // HLD requires acl_tokens to be non-lossy for ALL tiers (§02 §5 "must not be a lossy projection")
      // Reject for all tiers when compression cannot bring count within limit
      raise ERR_AUTH_CLEARANCE_INSUFFICIENT  // reject; do not silently truncate (truncation is lossy)
​
  sorted_tokens = sorted(raw_tokens)
​
  acl_key = SHA-256(
    "|".join(sorted_tokens)
    + "|" + TOKEN_SCHEMA_VERSION
    + "|" + ACL_VERSION
  )
​
  return UserContext {
    user_id: normalized_claims.user_id,
    effective_groups: sorted_tokens.filter(t => t.startsWith("group:")),
    effective_clearance: normalized_claims.clearance_level,
    acl_tokens: sorted_tokens,
    acl_key: acl_key,
    token_schema_version: TOKEN_SCHEMA_VERSION,
    acl_version: ACL_VERSION,
    claims_hash: claims_hash,         // computed in §4.1
    derived_at: now_utc_iso()
  }
```
​
### 4.3 Group Compression Rules
​
```
function compress_group(raw_group):
  // Strip known enterprise domain suffixes
  name = raw_group
    .replace(/@company\.com$/, "")
    .replace(/@[-\w]+\.company\.com$/, "")
​
  // Normalize to lowercase, replace spaces and dots with hyphens
  name = name.toLowerCase().replaceAll(/[\s\.]+/, "-")
​
  // Return as namespaced token
  return "group:" + name
```
​
The compression mapping must be deterministic and versioned. Any change to compression rules requires bumping `TOKEN_SCHEMA_VERSION`.
​
### 4.4 Group Hierarchy Compression
​
```
function apply_hierarchy_compression(tokens):
  // Load parent-child mapping from config
  hierarchy = load_hierarchy_config()   // e.g., infra-prod → infra, infra-staging → infra
​
  result = set(tokens)
  for child, parent in hierarchy.items():
    if ("group:" + child) in result and ("group:" + parent) in result:
      result.remove("group:" + child)   // child is covered by parent
​
  return list(result)
```
​
Compression config is a static YAML file (`acl-hierarchy-config.yaml`) mounted as a ConfigMap. Compression is only safe if all chunks accessible via the child token are also accessible via the parent token; this must be verified when updating the config.
​
---
​
## 5. Configuration Parameters
​
```yaml
TOKEN_SCHEMA_VERSION: "v1"        # bump when compression rules change
ACL_VERSION: "v1"                  # bump when ACL policy changes globally
ACL_TOKEN_MAX_COUNT: 30
REDIS_AUTH_CACHE_TTL_S: 300
REDIS_HOST: redis.retrieval-deps
REDIS_PORT: 6379
REDIS_DB: 0
CLAIMS_SIGNING_KEY_SECRET: api-gateway-claims-key
HIERARCHY_CONFIG_PATH: /config/acl-hierarchy-config.yaml
```
​
---
​
## 6. Redis Key Schema
​
```
Key:   "acl:{claims_hash}"
Value: JSON {
  "acl_tokens": [...],
  "acl_key": "hex-string",
  "effective_clearance": 2,
  "cached_at": "ISO-8601",
  "token_schema_version": "v1",
  "acl_version": "v1"
}
TTL:   300 seconds
```
​
Cache invalidation: bumping `TOKEN_SCHEMA_VERSION` or `ACL_VERSION` in configuration changes the `claims_hash` computation, causing all existing cache entries to become unreachable (they will expire naturally within 300s). There is no explicit eviction needed for global schema changes.
​
---
​
## 7. Error Handling
​
| Condition | L0/L1 Behavior | L2/L3 Behavior |
|-----------|---------------|----------------|
| HMAC signature mismatch | 403 ERR_AUTH_UNTRUSTED_CLAIMS | 403 ERR_AUTH_UNTRUSTED_CLAIMS |
| Missing required claims | 401 ERR_AUTH_MISSING_CLAIMS | 401 ERR_AUTH_MISSING_CLAIMS |
| Redis unavailable | Proceed with full derivation (log warning) | Proceed with full derivation (log warning) |
| Token count > 30 after compression | 403 ERR_AUTH_CLEARANCE_INSUFFICIENT (truncation is lossy; reject per HLD §02 §5) | 403 ERR_AUTH_CLEARANCE_INSUFFICIENT |
| acl_version mismatch detected at result cache | Force re-derivation | Force re-derivation |
​
---
​
## 8. Test Cases
​
| Test ID | Input | Expected Output |
|---------|-------|-----------------|
| ACL-NORM-01 | Valid claims, 5 groups | UserContext with 6 tokens (5 groups + 1 level) |
| ACL-NORM-02 | Duplicate groups in raw claims | Deduplicated tokens |
| ACL-NORM-03 | Invalid HMAC signature | ERR_AUTH_UNTRUSTED_CLAIMS |
| ACL-NORM-04 | Missing clearance_level | ERR_AUTH_MISSING_CLAIMS |
| ACL-NORM-05 | Same claims twice → cache hit on 2nd call | Redis hit; derivation not re-run |
| ACL-NORM-06 | Bump TOKEN_SCHEMA_VERSION → new claims | New claims_hash; cache miss; re-derived |
| ACL-NORM-07 | 100 groups, hierarchy compresses to 28 | 28 tokens ≤ 30; L2 request accepted |
| ACL-NORM-08 | 100 groups, compression yields 35 on any path | ERR_AUTH_CLEARANCE_INSUFFICIENT (all tiers; truncation prohibited) |
| ACL-NORM-09 | Same authorization semantics, different group order | Identical acl_key (deterministic) |
| ACL-NORM-10 | Redis unavailable | Derivation runs without cache; result returned; warning logged |
​
---
​
## 9. v1.1 Extension Points
​
- [v1.1] `acl_version` will be issued by the Token Registry control plane, not computed locally
- [v1.1] Hierarchy compression config will be managed by the Token Registry with versioned snapshots
- [v1.1] Redis cache TTL will be controlled precisely by the ACL Version Fence Manager
- [v1.1] The canonical `principal_id` will replace `user_id` (field name preserved for compatibility)
