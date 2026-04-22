# DDD v1.0 11: Elasticsearch Infrastructure
​
## 1. Responsibilities
​
- Define the Elasticsearch cluster topology for the retrieval indexes
- Provide index initialization scripts (mappings, settings, aliases)
- Define index naming, ILM policy, and blue/green alias strategy
- Document shard and replica configuration for v1.0 scale
​
**Covers**: `public_index`, `internal_index`, `confidential_index`, `restricted_index`, and the strategy for the Audit Elasticsearch cluster (index schema in `09-audit-emitter.md`).
​
---
​
## 2. Cluster Topology
​
### 2.1 Retrieval Elasticsearch
​
```
Namespace: retrieval-deps
StatefulSet: elasticsearch
  - 3 nodes (1 master + 2 data in v1.0; expand to 3 dedicated data nodes for production)
  - Storage: 500Gi PersistentVolume per node (SSD)
  - Memory: 16Gi per node (JVM heap = 8Gi)
  - CPU: 4 cores per node
​
Kubernetes Service:
  elasticsearch.retrieval-deps:9200 (ClusterIP, internal only)
```
​
### 2.2 Audit Elasticsearch
​
```
Namespace: retrieval-deps
StatefulSet: audit-elasticsearch
  - 1 node (v1.0; add replica for production)
  - Storage: 200Gi PersistentVolume per node
  - Memory: 8Gi per node (JVM heap = 4Gi)
​
Kubernetes Service:
  audit-elasticsearch.retrieval-deps:9200 (ClusterIP, internal only)
```
​
---
​
## 3. Index Initialization
​
Create all 4 retrieval indexes with identical mapping structure. Run this at cluster bootstrap (Kubernetes `Job`).
​
### 3.1 L0/L1 Index Mapping (dims=1536)
​
Physical index names use a `_v1` suffix; application code always uses the alias (e.g. `public_index`), never the physical name directly. The init script creates both the physical index and the alias in one step.
​
```json
PUT /public_index_v1
{
  "mappings": {
    "properties": {
      "doc_id":           { "type": "keyword" },
      "chunk_id":         { "type": "keyword" },
      "content":          { "type": "text", "analyzer": "standard" },
      "vector":           { "type": "dense_vector", "dims": 1536, "index": true, "similarity": "cosine" },
      "path":             { "type": "keyword", "index": false },
      "page_number":      { "type": "integer" },
      "section":          { "type": "text", "index": false },
      "topic":            { "type": "keyword" },
      "doc_type":         { "type": "keyword" },
      "year":             { "type": "integer" },
      "source":           { "type": "keyword" },
      "allowed_groups":   { "type": "keyword" },
      "acl_tokens":       { "type": "keyword" },
      "acl_key":          { "type": "keyword" },
      "acl_version":      { "type": "keyword" },
      "sensitivity_level": { "type": "integer" },
      "created_at":       { "type": "date" },
      "updated_at":       { "type": "date" }
    }
  },
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "index.refresh_interval": "1s"
  }
}
```
​
Apply the same mapping to `internal_index` (both use `dims=1536`).
​
### 3.2 L2/L3 Index Mapping (dims=1024)
​
```json
PUT /confidential_index_v1
{
  "mappings": {
    "properties": {
      // ... same fields as above, EXCEPT:
      "vector": { "type": "dense_vector", "dims": 1024, "index": true, "similarity": "cosine" }
    }
  },
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  }
}
```
​
Apply the same mapping to `restricted_index`.
​
### 3.3 Index Initialization Script
​
```bash
#!/bin/bash
# run as Kubernetes Job at cluster bootstrap
ES_URL="https://elasticsearch.retrieval-deps:9200"
AUTH="-u ${ES_USERNAME}:${ES_PASSWORD} --cacert /certs/ca.crt"
​
# Step 1: Create physical indexes with _v1 suffix
for INDEX in public_index_v1 internal_index_v1; do
  curl -X PUT "$ES_URL/$INDEX" \
    -H "Content-Type: application/json" \
    -d @/mappings/l0l1-mapping.json \
    $AUTH
done
​
for INDEX in confidential_index_v1 restricted_index_v1; do
  curl -X PUT "$ES_URL/$INDEX" \
    -H "Content-Type: application/json" \
    -d @/mappings/l2l3-mapping.json \
    $AUTH
done
​
# Step 2: Create aliases — application code uses aliases, never physical names
curl -X POST "$ES_URL/_aliases" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      { "add": { "index": "public_index_v1",       "alias": "public_index" } },
      { "add": { "index": "internal_index_v1",     "alias": "internal_index" } },
      { "add": { "index": "confidential_index_v1", "alias": "confidential_index" } },
      { "add": { "index": "restricted_index_v1",   "alias": "restricted_index" } }
    ]
  }' \
  $AUTH
```
​
---
​
## 4. Aliases and Blue/Green Rebuild
​
Each index has a corresponding alias used by the application. The alias allows zero-downtime index rebuilds.
​
```
Alias:        public_index         → actual index: public_index_v1
Alias:        internal_index       → actual index: internal_index_v1
Alias:        confidential_index   → actual index: confidential_index_v1
Alias:        restricted_index     → actual index: restricted_index_v1
```
​
### Blue/Green Rebuild Procedure
​
```bash
# 1. Create new index version
PUT /public_index_v2   { same mapping }
​
# 2. Populate v2 (ingestion pipeline writes to v2)
​
# 3. Verify v2 doc count and sample quality
​
# 4. Atomic alias cutover
POST /_aliases
{
  "actions": [
    { "remove": { "index": "public_index_v1", "alias": "public_index" } },
    { "add":    { "index": "public_index_v2", "alias": "public_index" } }
  ]
}
​
# 5. Delete v1 after confirmation window (e.g., 24 hours)
DELETE /public_index_v1
```
​
---
​
## 5. Elasticsearch User Roles
​
```json
// query-service role: read-only on retrieval indexes
{
  "indices": [{
    "names": ["public_index", "internal_index", "confidential_index", "restricted_index"],
    "privileges": ["read", "view_index_metadata"]
  }]
}
​
// ingestion-worker role: write to retrieval indexes
{
  "indices": [{
    "names": ["public_index*", "internal_index*", "confidential_index*", "restricted_index*"],
    "privileges": ["create_index", "create", "delete", "index"]
  }]
}
​
// admin role: manage indexes (for bootstrap and rebuild)
{
  "indices": [{
    "names": ["*"],
    "privileges": ["all"]
  }]
}
```
​
Credentials stored in Kubernetes `Secret` objects; mounted as environment variables in pod specs.
​
---
​
## 6. ILM (Index Lifecycle Management)
​
> **Open decision (HLD §11-open-decisions #4)**: Audit retention period and ILM tiering strategy are not finalized. The values below (`30d` rollover, `90d` freeze) are placeholders. These must be confirmed with the compliance/legal owner before production deployment.
​
For the retrieval indexes, ILM is optional in v1.0 (data grows over time but does not need auto-deletion). For the audit indexes, ILM is required to enforce retention limits:
​
```json
PUT /_ilm/policy/audit-policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": { "max_age": "30d", "max_size": "50gb" }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": { "forcemerge": { "max_num_segments": 1 } }
      },
      "cold": {
        "min_age": "90d",
        "actions": { "freeze": {} }
      }
    }
  }
}
```
​
---
​
## 7. HNSW Parameters
​
The default HNSW parameters from Elasticsearch 8.x are used. For production tuning:
​
```json
"vector": {
  "type": "dense_vector",
  "dims": 1536,
  "index": true,
  "similarity": "cosine",
  "index_options": {
    "type": "hnsw",
    "m": 16,               // HNSW graph connectivity; higher = better recall, more memory
    "ef_construction": 100 // Index-time build quality; higher = better recall, slower build
  }
}
```
​
v1.0 uses defaults (`m=16`, `ef_construction=100`). Tune if recall benchmarks (RET-01/02) fail to meet targets.
​
---
​
## 8. Kubernetes StatefulSet Configuration
​
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
  namespace: retrieval-deps
spec:
  serviceName: elasticsearch
  replicas: 3
  selector:
    matchLabels:
      app: elasticsearch
  template:
    spec:
      containers:
        - name: elasticsearch
          image: docker.elastic.co/elasticsearch/elasticsearch:8.12.0
          env:
            - name: node.name
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: cluster.name
              value: rag-cluster
            - name: discovery.seed_hosts
              value: "elasticsearch-0.elasticsearch,elasticsearch-1.elasticsearch"
            - name: cluster.initial_master_nodes
              value: "elasticsearch-0"
            - name: ES_JAVA_OPTS
              value: "-Xms8g -Xmx8g"
            - name: xpack.security.enabled
              value: "true"
          resources:
            requests:
              cpu: "4"
              memory: "16Gi"
            limits:
              cpu: "4"
              memory: "16Gi"
          volumeMounts:
            - name: data
              mountPath: /usr/share/elasticsearch/data
            - name: certs
              mountPath: /usr/share/elasticsearch/config/certs
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 500Gi
        storageClassName: ssd
```
​
---
​
## 9. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| ES-01 | Index initialization script runs | All 4 indexes created with correct mappings |
| ES-02 | Write L0/L1 doc with vector dims=1536 | Indexed without error |
| ES-03 | Write L2/L3 doc with vector dims=1024 | Indexed without error |
| ES-04 | Write L0/L1 doc with vector dims=1024 | Rejected (dimension mismatch) |
| ES-05 | Blue/green alias cutover | Zero-downtime; query during cutover succeeds |
| ES-06 | ingestion-worker role attempts DELETE on index | Rejected by ES role |
| ES-07 | query-service role attempts CREATE | Rejected |
| ES-08 | BM25 + kNN hybrid query returns results | Authorized results returned; ACL filter applied |
| ES-09 | ACL filter with empty acl_tokens | Zero results returned |