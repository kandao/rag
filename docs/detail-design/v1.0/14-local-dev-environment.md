# DDD v1.0 14: Local Development Environment
​
## 1. Purpose
​
Define the local development environment that enables developers to run, test, and validate the full RAG system on a single machine without cloud dependencies. The local environment prioritizes:
​
- Full query path validation (ACL, retrieval, rerank, generation)
- Ingestion pipeline testing
- Fail-closed behavior and audit testing
- No cloud credentials required for basic functionality
​
---
​
## 2. Local Stack Components
​
| Component | Local Replacement | Notes |
|-----------|-----------------|-------|
| Kubernetes | `kind` or `k3d` | Single-node cluster |
| Enterprise SSO / IdP | Mock Claims Injector | Static JSON claims file |
| Elasticsearch (retrieval) | Single-node ES 8.x in kind | No replicas |
| Elasticsearch (audit) | Same node, different index | Separate URL |
| Redis | Redis 7.x in kind | Single instance |
| Reranker Service | Disabled (`RERANKER_ENABLED: false`); retrieval order used as fallback | No GPU required |
| Embedding API (L0/L1) | `text-embedding-3-small` via OpenAI (1536d, requires key) | — |
| Embedding API (L2/L3) | `text-embedding-3-small` with `dimensions=1024` via OpenAI | Matryoshka truncation; index mapping stays at `dims=1024` (compatible with production self-hosted BGE) |
| LLM (L0/L1) | OpenAI (`gpt-4o`) OR Anthropic (`claude-sonnet-4-6`) — switch via `provider` config; Ollama (`llama3`) for fully offline | Set `LLM_PROVIDER_L0L1` to `openai` or `anthropic` |
| LLM (L2/L3) | OpenAI (`gpt-4o`) OR Anthropic (`claude-sonnet-4-6`) — switch via `provider` config; Ollama (`llama3`) for fully offline | Local dev only — production L2/L3 must use self-hosted; no external API calls |
| API Gateway | FastAPI stub (replaces Kong locally) | Signs claims headers; same FastAPI stack as all other services |
| mTLS | Disabled (HTTP only for local) | Enable for integration tests |
​
---
​
## 3. Quick Start
​
### Prerequisites
​
```bash
# Required
brew install kind kubectl helm
​
# Optional (for offline LLM)
brew install ollama
ollama pull llama3:8b
# Note: embedding uses OpenAI API (text-embedding-3-small); no local embedding model needed
```
​
### Cluster Setup
​
```bash
# Create kind cluster
cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30080    # api-gateway
        hostPort: 8080
        protocol: TCP
EOF
​
kind create cluster --config kind-config.yaml --name rag-local
​
# Apply namespace manifests
kubectl apply -f deploy/local/namespaces.yaml
​
# Deploy all services (local values)
helm upgrade --install rag-system ./charts/rag \
  -f charts/rag/values-local.yaml \
  --create-namespace
```
​
### Seed Test Data
​
```bash
# Initialize ES indexes
kubectl apply -f deploy/local/jobs/es-init.yaml
kubectl wait --for=condition=complete job/es-init -n retrieval-deps
​
# Seed test documents (uses test fixtures from test/fixtures/)
kubectl apply -f deploy/local/jobs/seed-data.yaml
kubectl wait --for=condition=complete job/seed-data -n ingestion
```
​
---
​
## 4. Mock Claims Injector
​
Replaces the API Gateway's OIDC token validation with a static claims file. The mock gateway reads from a `users.yaml` config and signs the claims header with the same HMAC key used by the real gateway.
​
```yaml
# test/fixtures/mock-users.yaml
users:
  - token: "test-token-l0"
    claims:
      user_id: "user_l0"
      groups: ["eng:public"]
      role: null
      clearance_level: 0
​
  - token: "test-token-l1"
    claims:
      user_id: "user_l1"
      groups: ["eng:engineering", "eng:public"]
      role: null
      clearance_level: 1
​
  - token: "test-token-l2"
    claims:
      user_id: "user_l2"
      groups: ["eng:engineering", "eng:infra"]
      role: "manager"
      clearance_level: 2
​
  - token: "test-token-l3"
    claims:
      user_id: "user_l3"
      groups: ["eng:restricted-ops"]
      role: null
      clearance_level: 3
​
  - token: "test-token-attacker"
    claims:
      user_id: "attacker"
      groups: ["eng:public"]
      role: null
      clearance_level: 0
​
  - token: "test-token-no-acl"
    claims:
      user_id: "user_no_acl"
      groups: []
      role: null
      clearance_level: 0
```
​
Usage:
```bash
curl -X POST http://localhost:8080/v1/query \
  -H "Authorization: Bearer test-token-l1" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the 2024 finance reporting requirements?"}'
```
​
---
​
## 5. Local Configuration Overrides (`values-local.yaml`)
​
```yaml
# charts/rag/values-local.yaml
global:
  environment: local
  mtls_enabled: false
​
apiGateway:
  mockMode: true
  mockUsersFile: /config/mock-users.yaml
  claimsSigningKey: local-dev-key-not-for-production
​
queryService:
  replicas: 1
  llmParserEnabled: false
  queryExpansionEnabled: false
  answerVerificationEnabled: false
​
  embedding:
    l0l1:
      provider: openai
      url: https://api.openai.com/v1/embeddings   # direct for local dev only; prod routes via enterprise gateway
      model: text-embedding-3-small
      dims: 1536
    l2l3:
      provider: openai
      url: https://api.openai.com/v1/embeddings
      model: text-embedding-3-small
      dims: 1024                # Matryoshka truncation; index mapping stays at dims=1024 to match production BGE schema
​
  model:
    l0l1:
      provider: anthropic                                  # openai | anthropic | ollama
      url: https://api.anthropic.com/v1/messages           # switch to api.openai.com/v1/chat/completions for openai
      model: claude-sonnet-4-6                             # or gpt-4o for openai; llama3:8b for ollama
      api_key_secret: anthropic-api-key                    # K8s Secret name; set ANTHROPIC_API_KEY env var locally
    l2l3:
      provider: anthropic                                  # openai | anthropic | ollama (local dev only; prod must use self-hosted)
      url: https://api.anthropic.com/v1/messages           # switch to api.openai.com/v1/chat/completions for openai
      model: claude-sonnet-4-6                             # or gpt-4o for openai; llama3:8b for ollama
      api_key_secret: anthropic-api-key                    # K8s Secret name; set ANTHROPIC_API_KEY env var locally
​
rerankerService:
  enabled: false            # disabled locally; no GPU available; retrieval order used as fallback
  gpuRequired: false
​
elasticsearch:
  replicas: 1
  heapSize: 1g                 # reduced for local
  storageSize: 10Gi
​
redis:
  maxmemory: 512mb
​
```
​
> **Note**: local dev uses `text-embedding-3-small` via OpenAI API for both tiers — 1536d for L0/L1 and `dimensions=1024` (Matryoshka truncation) for L2/L3. Local index mappings must be created with the corresponding dims (`1536` and `1024`). This matches the production L2/L3 BGE index schema (`dims=1024`).
​
---
​
## 6. Test Data Fixtures
​
### 6.1 Seed Documents
​
Located in `test/fixtures/documents/`:
​
```
test/fixtures/documents/
├── public/
│   ├── finance_report_2024.pdf         # L0, allowed_groups: ["eng:public"]
│   └── product_overview.md             # L0, allowed_groups: ["eng:public"]
├── internal/
│   ├── engineering_guidelines_2024.md  # L1, allowed_groups: ["eng:engineering"]
│   └── hr_policy_2024.md               # L1, allowed_groups: ["eng:public", "eng:hr"]
├── confidential/
│   ├── m_and_a_memo_2024.pdf           # L2, allowed_groups: ["eng:infra"], allowed_roles: ["manager"]
│   └── legal_contracts_q1.md           # L2, allowed_groups: ["eng:infra"]
└── restricted/
    └── board_minutes_2024.pdf          # L3, allowed_groups: ["eng:restricted-ops"]
```
​
### 6.2 ACL Policy Config
​
```yaml
# test/fixtures/acl-policies.yaml
acl_policies:
  - source_pattern: "public/*"
    allowed_groups: ["eng:public"]
    sensitivity_level: 0
​
  - source_pattern: "internal/engineering_*"
    allowed_groups: ["eng:engineering"]
    sensitivity_level: 1
​
  - source_pattern: "internal/hr_*"
    allowed_groups: ["eng:public", "eng:hr"]
    sensitivity_level: 1
​
  - source_pattern: "confidential/*"
    allowed_groups: ["eng:infra"]
    allowed_roles: ["manager"]    # roles are a separate ACLPolicy field; not mixed into allowed_groups
    sensitivity_level: 2
​
  - source_pattern: "restricted/*"
    allowed_groups: ["eng:restricted-ops"]
    sensitivity_level: 3
```
​
---
​
## 7. Running the Test Suite Locally
​
```bash
# Unit tests (no cluster required)
pytest tests/unit/ -x -q
​
# Integration tests (requires local cluster + seed data)
pytest tests/integration/ --timeout=120 -v
​
# Security / ACL tests (subset of 12-eval-test-plan)
pytest tests/security/ -v
​
# Full eval suite (requires real embedding + LLM)
OPENAI_API_KEY=sk-xxx pytest tests/eval/ -v --tb=short
```
​
---
​
## 8. Development Workflow
​
```
1. Make code changes (Python 3.11 / FastAPI)
2. Build image: docker build -t rag/query-service:dev .
   # Base image: python:3.11-slim; CMD: uvicorn app.main:app --host 0.0.0.0 --port 8080
3. Load into kind: kind load docker-image rag/query-service:dev --name rag-local
4. Roll out: kubectl rollout restart deployment/query-service -n query
5. Check logs: kubectl logs -n query -l app=query-service -f
6. Run unit tests locally (no cluster): pytest tests/unit/ -x -q
7. Run test against cluster: curl http://localhost:8080/v1/query \
     -H "Authorization: Bearer test-token-l1" \
     -H "Content-Type: application/json" \
     -d '{"query": "What are the 2024 finance reporting requirements?"}'
```
​
---
​
## 9. Tear Down
​
```bash
kind delete cluster --name rag-local
```
​
---
​
## 10. Known Local Limitations
​
| Limitation | Impact | Mitigation |
|------------|--------|------------|
| No mTLS | Network security not validated locally | Run integration tests with mTLS enabled in CI |
| Reranker disabled (`RERANKER_ENABLED: false`) | Retrieval order used instead of cross-encoder scores; answer quality lower | Acceptable for functional dev/testing; enable MiniLM or Cohere Rerank API if ranking quality matters |
| Ollama LLM | Slower, different model | Use for functional testing only; eval tests require production models |
| Single ES node | No replica; data loss if pod restarts | Acceptable for local; re-seed from fixtures |
| OpenAI embedding (requires key) | API key needed for local dev; no offline embedding path | Set `OPENAI_API_KEY` env var; for fully offline setups, replace embedding config with a local model (out of scope for this guide) |