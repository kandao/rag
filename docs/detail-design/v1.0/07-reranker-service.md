# DDD v1.0 07: Reranker Service
​
## 1. Responsibilities
​
- Accept authorized `RetrievalCandidate` sets from the Query Service
- Run cross-encoder inference to produce relevance scores for each (query, chunk) pair
- Return only `chunk_id + rerank_score` (no content, no ACL metadata)
- Support batch inference for latency efficiency
- Degrade gracefully on timeout: the Query Service falls back to retrieval order
​
**Not responsible for**: ACL enforcement, ES queries, content retrieval, or authorization metadata.
​
---
​
## 2. Service Architecture
​
The Reranker Service is a **standalone Kubernetes Deployment** in the `reranker` namespace. It is not part of the Query Service process. This allows independent GPU scaling and prevents inference from blocking the Query Service request thread.
​
```
Query Service
  │
  │  POST /v1/rerank
  ▼
Reranker Service (GPU Pod)
  │
  │  { chunk_id, rerank_score }[]
  ▼
Query Service (continues to Model Gateway)
```
​
---
​
## 3. API Contract
​
### POST /v1/rerank
​
**Request:**
```json
{
  "request_id": "uuid-v4",
  "query": "What are the 2024 medical device regulation amendments?",
  "candidates": [
    {
      "chunk_id": "chunk-abc-001",
      "content": "The 2024 amendments to medical device regulations..."
    },
    {
      "chunk_id": "chunk-xyz-002",
      "content": "Medical equipment safety standards..."
    }
  ]
}
```
​
**Response (success):**
```json
{
  "request_id": "uuid-v4",
  "ranked": [
    { "chunk_id": "chunk-abc-001", "rerank_score": 0.92 },
    { "chunk_id": "chunk-xyz-002", "rerank_score": 0.61 }
  ]
}
```
​
**Response (partial failure — some candidates could not be scored):**
```json
{
  "request_id": "uuid-v4",
  "ranked": [
    { "chunk_id": "chunk-abc-001", "rerank_score": 0.92 }
  ],
  "partial": true,
  "unscored_chunk_ids": ["chunk-xyz-002"]
}
```
​
### Invariants
​
- Request payload must **not** contain `allowed_groups`, `acl_tokens`, `acl_key`, or `acl_version`. The Query Service strips these before sending (see `06-retrieval-orchestrator.md` and `08-model-gateway.md`).
- Response must **not** include content; only `chunk_id` and `rerank_score`.
​
---
​
## 4. Query Service Integration
​
### 4.1 Reranker Client (inside Query Service)
​
```
function rerank(query: string, candidates: RetrievalCandidate[]) -> RankedCandidate[]:
  if len(candidates) == 0:
    return []
​
  // Skip reranking when disabled (e.g. local dev without GPU)
  if not RERANKER_ENABLED:
    log.debug("Reranker disabled; using retrieval order fallback")
    return retrieval_order_fallback(candidates)
​
  // Strip ACL fields before sending
  payload = {
    request_id: new_uuid(),
    query: query,
    candidates: candidates.map(c => { chunk_id: c.chunk_id, content: c.content })
  }
​
  response = http_post(RERANKER_URL + "/v1/rerank", payload, timeout=RERANKER_TIMEOUT_MS)
​
  if response.timed_out or response.error:
    log.warn("Reranker unavailable; using retrieval order fallback")
    emit_alert("reranker_fallback", { request_id: ... })
    return retrieval_order_fallback(candidates)
​
  return response.ranked
```
​
### 4.2 Retrieval Order Fallback
​
```
function retrieval_order_fallback(candidates: RetrievalCandidate[]) -> RankedCandidate[]:
  // Use existing retrieval_score as the rerank_score proxy
  return candidates.map(c => {
    chunk_id: c.chunk_id,
    rerank_score: c.retrieval_score
  })
```
​
Configuration:
```yaml
RERANKER_ENABLED: true                              # set to false to skip reranking (local dev)
RERANKER_URL: http://reranker-service.reranker:8080
RERANKER_TIMEOUT_MS: 1000
RERANKER_MAX_CANDIDATES_PER_REQUEST: 200
```
​
---
​
## 5. Model Selection
​
`v1.0` baseline: `BAAI/bge-reranker-large` (multilingual, self-hostable).
​
| Scenario | Model |
|----------|-------|
| Primarily Chinese documents | `BAAI/bge-reranker-large` |
| Mixed language | `BAAI/bge-reranker-v2-m3` |
| Low traffic / local dev | `ms-marco-MiniLM-L-6-v2` |
​
The model is mounted as a persistent volume or baked into the container image. It does not call any external API.
​
---
​
## 6. Inference Implementation
​
### 6.1 Batch Inference
​
```python
from sentence_transformers import CrossEncoder
​
model = CrossEncoder(MODEL_PATH, max_length=512)
​
def rerank(query: str, candidates: list[dict]) -> list[dict]:
    pairs = [(query, c["content"]) for c in candidates]
    scores = model.predict(pairs, batch_size=BATCH_SIZE, show_progress_bar=False)
    results = [
        {"chunk_id": c["chunk_id"], "rerank_score": float(score)}
        for c, score in zip(candidates, scores)
    ]
    return sorted(results, key=lambda x: -x["rerank_score"])
```
​
Configuration:
```yaml
MODEL_PATH: /models/bge-reranker-large
BATCH_SIZE: 32
MAX_SEQUENCE_LENGTH: 512
```
​
### 6.2 Two-Stage Rerank (medium-to-large scale option)
​
Not required at v1.0 launch, but the API supports it via the `stage` parameter:
​
```
Stage 1: Lightweight model (MiniLM) → Top 100 → Top 20
Stage 2: Heavyweight model (bge-reranker-large) → Top 20 → Top 5
```
​
This is toggled via `RERANKER_TWO_STAGE_ENABLED: false` in v1.0.
​
---
​
## 7. Kubernetes Resource Specification
​
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reranker-service
  namespace: reranker
spec:
  replicas: 1          # scale up based on GPU availability
  selector:
    matchLabels:
      app: reranker-service
  template:
    metadata:
      labels:
        app: reranker-service
    spec:
      nodeSelector:
        nvidia.com/gpu.present: "true"    # GPU node pool
      containers:
        - name: reranker
          image: rag/reranker-service:v1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              nvidia.com/gpu: "1"
              memory: "8Gi"
              cpu: "2"
            limits:
              nvidia.com/gpu: "1"
              memory: "16Gi"
              cpu: "4"
          env:
            - name: MODEL_PATH
              value: /models/bge-reranker-large
            - name: BATCH_SIZE
              value: "32"
          volumeMounts:
            - name: model-volume
              mountPath: /models
      volumes:
        - name: model-volume
          persistentVolumeClaim:
            claimName: reranker-model-pvc
```
​
**L2/L3 constraint**: the Reranker Service for L2/L3 sensitive content must run on an enterprise-controlled node pool. Shared multi-tenant GPU resources are not permitted. In practice, v1.0 uses a single Reranker Service instance; L2/L3 isolation is maintained because only authorized content reaches it.
​
---
​
## 8. Security Controls
​
- The Reranker Service is in its own namespace (`reranker`) with a network policy that only allows inbound connections from the `query` namespace.
- The service accepts no authentication header; isolation is network-layer only (mTLS service mesh).
- Response payloads contain only `chunk_id` and `rerank_score`. Content is never echoed back.
- Application logs must not record candidate content.
​
```yaml
NetworkPolicy:
  ingress: from namespace=query, port=8080
  egress: to DNS only
```
​
---
​
## 9. Observability
​
```yaml
Metrics:
  - reranker_request_duration_ms (histogram)
  - reranker_batch_size (histogram)
  - reranker_fallback_total (counter)
  - reranker_gpu_utilization_pct (gauge; exposed via DCGM exporter)
​
Alerts:
  - reranker_fallback_total rate > 5/min → PagerDuty
  - reranker_request_duration_ms p95 > 1000ms → warning
```
​
---
​
## 10. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| RNK-01 | 50 candidates, valid query | 50 RankedCandidates returned, sorted by rerank_score desc |
| RNK-02 | Request payload contains acl_tokens | Test that Query Service strips it before sending (unit test on client) |
| RNK-03 | Reranker times out | Query Service falls back to retrieval order; alert emitted |
| RNK-04 | Reranker pod unavailable | Same as timeout; alert emitted |
| RNK-05 | 0 candidates | Empty ranked list returned immediately |
| RNK-06 | Partial failure (1 of 50 cannot be scored) | 49 scores returned; partial=true; unscored listed |
| RNK-07 | Response does not include content field | Confirmed via payload inspection |
| RNK-08 | Two calls with same query, different candidates | Scores differ (model-based, not cached) |