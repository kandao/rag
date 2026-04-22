# DDD v1.0 09: Audit Emitter
​
## 1. Responsibilities
​
- Emit a structured `AuditEvent` to Audit Elasticsearch after every query (success or failure)
- For L2/L3 paths: hold the response until the audit write is confirmed (fail-closed gate)
- For L0/L1 paths: emit asynchronously; a write failure degrades gracefully (log error, continue)
- Write blocked queries (Query Guard blocks) as abbreviated audit events
- Enforce append-only semantics via restricted Elasticsearch roles
​
**Not responsible for**: evaluating authorization, reading audit logs, or generating reports.
​
---
​
## 2. Audit Elasticsearch Cluster
​
Audit logs are written to a **separate Elasticsearch cluster** (`audit-elasticsearch`) with append-only index settings. This cluster is never queried by the Query Service for retrieval.
​
```
Cluster: audit-elasticsearch.retrieval-deps:9200
Index: audit-events-{YYYY-MM}    // monthly rollover (naming convention; see retention note below)
Alias: audit-events-current       // writer uses alias
```
​
> **Open decision (HLD §11-open-decisions #4)**: Audit retention period and index tiering strategy have not been finalized. The monthly rollover naming convention above is a working proposal. Retention duration (e.g., 90 days, 1 year) and ILM policy details must be resolved and documented before production deployment.
​
Index settings enforce immutability:
- Writer role has `create` privilege only (no `delete`, `update`)
- Reader role has `read` privilege only
- ILM policy: 90-day rollover (configurable); frozen after 30 days; archived after 90 days
​
---
​
## 3. Audit Event Schema
​
See `AuditEvent` in `00-conventions-contracts.md §3.5`. Additional fields for the Elasticsearch document:
​
```json
{
  "event_id": "uuid-v4",
  "request_id": "uuid-v4",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "user_id": "uid-abc123",
  "claims_digest": "sha256-hex",
  "acl_key": "sha256-hex",
  "acl_version": "v1",
  "target_indexes": ["internal_index"],
  "retrieved_chunk_ids": ["chunk-001", "chunk-002"],
  "ranked_chunk_ids": ["chunk-001"],
  "sensitivity_levels_accessed": [1],
  "model_path": "cloud_l1",
  "authorization_decision": "allowed",
  "query_risk_signal": "none",
  "answer_returned": true,
  "latency_ms": 1234,
  "event_type": "query",
  "guard_pattern_id": null,
  "partial_result": false
}
```
​
For Query Guard blocks:
```json
{
  "event_id": "uuid-v4",
  "request_id": "uuid-v4",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "user_id": "uid-abc123",
  "claims_digest": "sha256-hex",
  "event_type": "guard_block",
  "guard_pattern_id": "INJ-001",
  "risk_level": "HIGH",
  "query_fragment": "ignore all instructions...",  // first 100 chars only
  "answer_returned": false
}
```
​
---
​
## 4. Emitter Module Location
​
```
query-service/
└── internal/
    └── audit/
        ├── emitter.py
        ├── event_builder.py
        └── es_writer.py
```
​
---
​
## 5. Emit Flow
​
### 5.1 L0/L1 (Async, Non-blocking)
​
```
function emit_async(event: AuditEvent):
  go background_write(event)      // fire-and-forget goroutine
  // query response is returned immediately; audit write does not block
​
function background_write(event):
  result = audit_es_client.index(INDEX_ALIAS, event)
  if result.error:
    log.error("Audit write failed (non-critical)", event.request_id)
    increment_metric("audit_write_failures_total")
```
​
### 5.2 L2/L3 (Sync, Response Gate)
​
```
function emit_and_gate(event: AuditEvent) -> void | raise:
  result = audit_es_client.index(INDEX_ALIAS, event, timeout=AUDIT_WRITE_TIMEOUT_MS)
  if result.error or result.timed_out:
    log.error("AUDIT WRITE FAILED — fail-closed for L2/L3", event.request_id)
    raise ERR_AUDIT_FAILED_CLOSED    // response is withheld
  // only returns (without raising) on successful write
```
​
Configuration:
```yaml
AUDIT_WRITE_TIMEOUT_MS: 5000
AUDIT_ES_HOSTS: ["https://audit-elasticsearch.retrieval-deps:9200"]
AUDIT_ES_USERNAME: audit-writer    # from K8s Secret
AUDIT_ES_PASSWORD: <secret>
AUDIT_INDEX_ALIAS: audit-events-current
AUDIT_FAIL_CLOSED_MIN_CLEARANCE: 2    # L2 and above are fail-closed
```
​
---
​
## 6. Sensitivity Decision: Sync vs Async
​
```
// Gate is determined by the REQUEST PATH sensitivity (user clearance level),
// not by the maximum chunk sensitivity of the retrieved results.
// A L2 user querying L0+L2 indexes that happens to return only L0 chunks
// is still a sensitive-path request and must be gated. (HLD §00 §7, §01 query flow)
function should_gate_on_audit(user_context: UserContext) -> bool:
  return user_context.effective_clearance >= AUDIT_FAIL_CLOSED_MIN_CLEARANCE
```
​
The gate decision is made using the user's `effective_clearance` before retrieval runs, so it is fixed for the duration of the request regardless of which chunks are returned.
​
---
​
## 7. Audit Index Elasticsearch Setup
​
Index mapping:
```json
{
  "mappings": {
    "properties": {
      "event_id":               { "type": "keyword" },
      "request_id":             { "type": "keyword" },
      "timestamp":              { "type": "date" },
      "user_id":                { "type": "keyword" },
      "claims_digest":          { "type": "keyword" },
      "acl_key":                { "type": "keyword" },
      "acl_version":            { "type": "keyword" },
      "target_indexes":         { "type": "keyword" },
      "retrieved_chunk_ids":    { "type": "keyword" },
      "ranked_chunk_ids":       { "type": "keyword" },
      "sensitivity_levels_accessed": { "type": "integer" },
      "model_path":             { "type": "keyword" },
      "authorization_decision": { "type": "keyword" },
      "query_risk_signal":      { "type": "keyword" },
      "answer_returned":        { "type": "boolean" },
      "latency_ms":             { "type": "long" },
      "event_type":             { "type": "keyword" },
      "guard_pattern_id":       { "type": "keyword" },
      "partial_result":         { "type": "boolean" }
    }
  },
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 1
  }
}
```
​
Role configuration (Elasticsearch security):
```json
// audit-writer role
{
  "indices": [{
    "names": ["audit-events-*"],
    "privileges": ["create_index", "create"]   // no delete, no update
  }]
}
​
// audit-reader role
{
  "indices": [{
    "names": ["audit-events-*"],
    "privileges": ["read", "view_index_metadata"]
  }]
}
```
​
---
​
## 8. Log Redaction Rules
​
Audit events must not contain:
- Raw query text (only `query_fragment` of max 100 chars, and only for guard blocks)
- Chunk content (`content` field)
- Plaintext `acl_tokens` or `allowed_groups`
​
The `claims_digest` and `acl_key` are safe to store (they are hash values, not raw claims).
​
---
​
## 9. Metrics and Alerting
​
```yaml
Metrics:
  - audit_write_latency_ms (histogram)
  - audit_write_failures_total (counter)
  - audit_gate_blocked_total (counter)   # L2/L3 responses withheld due to audit failure
​
Alerts:
  - audit_write_failures_total > 0 → PagerDuty (any audit write failure is high-priority)
  - audit_write_latency_ms p95 > 3000ms → warning
```
​
---
​
## 10. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| AUD-01 | L1 query, audit ES available | Event written; response returned |
| AUD-02 | L1 query, audit ES unavailable | Error logged; response still returned (async, non-blocking) |
| AUD-03 | L3 query, audit ES available | Event written synchronously; response returned after write |
| AUD-04 | L3 query, audit ES unavailable | ERR_AUDIT_FAILED_CLOSED; no response returned |
| AUD-05 | L3 query, audit write takes 6s (timeout=5s) | ERR_AUDIT_FAILED_CLOSED |
| AUD-06 | Guard block event | Abbreviated event written; query_fragment truncated at 100 chars |
| AUD-07 | Attempt to DELETE audit document | Rejected (writer role has no delete privilege) |
| AUD-08 | Audit event contains acl_tokens in plaintext | Not present (test by inspecting stored document) |
| AUD-09 | L2 user (clearance=2) query, any chunk sensitivity | Gate=true (clearance ≥ 2); response held until write confirmed |
| AUD-10 | L1 user (clearance=1) query, any chunk sensitivity | Gate=false (clearance < 2); async emit |