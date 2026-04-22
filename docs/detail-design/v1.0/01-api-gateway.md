# DDD v1.0 01: API Gateway
​
## 1. Responsibilities
​
- Validate bearer tokens / session cookies against the upstream Enterprise SSO / IdP
- Extract and normalize trusted identity claims
- Forward a verified claims header (`X-Trusted-Claims`) to the Query Service
- Enforce per-user and global rate limits
- Route requests to downstream services
- Strip client-supplied `X-Trusted-Claims` headers (prevent header injection)
​
**Not responsible for**: ACL filter assembly, query parsing, or authorization decisions.
​
---
​
## 2. Technology Choice
​
`v1.0` uses **Kong Gateway** (self-managed, Kubernetes-native) or a compatible enterprise reverse proxy. The internal implementation can be replaced without changing the downstream contract — the Query Service only observes the forwarded claims header.
​
For local development, a lightweight FastAPI stub may substitute (see `14-local-dev-environment.md`).
​
---
​
## 3. Endpoint Routing Table
​
| Route Pattern | Upstream Service | Notes |
|--------------|-----------------|-------|
| `POST /v1/query` | Query Service `:8080/v1/query` | Main query endpoint |
| `POST /v1/ingest` | Ingestion Coordinator `:8090/v1/ingest` | Admin / service-account only |
| `GET /healthz` | (gateway itself) | Liveness probe |
​
---
​
## 4. Authentication Flow
​
```
Client
  │
  │  Authorization: Bearer <access_token>
  ▼
API Gateway
  ├── [OIDC / JWT validation]
  │     • verify signature against IdP JWKS endpoint
  │     • check `exp`, `iat`, `iss`, `aud` claims
  │     • reject if any check fails → 401 ERR_AUTH_INVALID_TOKEN
  │
  ├── [Claims Extraction]
  │     • extract: sub → user_id
  │     • extract: groups (array of raw group strings)
  │     • extract: role (string, may be absent → null)
  │     • extract: clearance_level (integer, must be present)
  │     • if any required field absent → 401 ERR_AUTH_MISSING_CLAIMS
  │
  ├── [Claims Sanitization]
  │     • strip any client-injected X-Trusted-Claims header
  │     • encode verified claims as JSON, sign with HMAC-SHA256 (shared secret
  │       between gateway and Query Service — stored in Kubernetes Secret)
  │     • set header: X-Trusted-Claims: base64(JSON claims)
  │     • set header: X-Claims-Sig: HMAC-SHA256(claims-json, signing-key)
  │
  └── Forward request to Query Service
```
​
### Claims JSON Structure
​
```json
{
  "user_id": "uid-abc123",
  "groups": ["eng:engineering", "eng:public", "dept:finance"],
  "role": "manager",
  "clearance_level": 2,
  "iss": "https://sso.company.com",
  "iat": 1700000000
}
```
​
### Configuration Parameters
​
```yaml
AUTH_JWKS_URI: https://sso.company.com/.well-known/jwks.json
AUTH_JWKS_CACHE_TTL_S: 300
AUTH_REQUIRED_CLAIMS: ["sub", "groups", "clearance_level"]
AUTH_AUDIENCE: "rag-api-v1"
CLAIMS_SIGNING_KEY_SECRET: api-gateway-claims-key   # K8s Secret name
CLAIMS_SIGNING_ALGO: HS256
```
​
---
​
## 5. Rate Limiting
​
Rate limiting is applied per `user_id` (extracted from the validated token).
​
| Tier | Limit | Window | Action on Breach |
|------|-------|--------|-----------------|
| Default | 20 req | 60 s | 429 ERR_GUARD_RATE_LIMIT |
| Admin service accounts | 200 req | 60 s | 429 |
| Global (all users) | 500 req | 1 s | 429 |
​
Implementation: Redis-backed sliding window counter using the gateway's built-in rate-limit plugin.
​
```yaml
RATE_LIMIT_REDIS_HOST: redis-gateway.retrieval-deps
RATE_LIMIT_REDIS_PORT: 6379
RATE_LIMIT_USER_RPM: 20
RATE_LIMIT_ADMIN_RPM: 200
RATE_LIMIT_GLOBAL_RPS: 500
```
​
---
​
## 6. Request/Response Contract
​
### POST /v1/query
​
**Request (from client):**
```json
{
  "query": "string (required, max 1000 chars)",
  "session_id": "string (optional, for multi-turn context)"
}
```
​
**Request forwarded to Query Service (with added headers):**
```
POST /v1/query
X-Request-ID: <uuid>
X-Trusted-Claims: <base64-json>
X-Claims-Sig: <hmac-hex>
X-Forwarded-For: <client-ip>
Body: { "query": "...", "session_id": "..." }
```
​
**Response (from Query Service, passed through):**
```json
{
  "request_id": "uuid",
  "data": {
    "answer": "string",
    "citations": [
      {
        "chunk_id": "string",
        "path": "string",
        "page_number": 3,
        "section": "Section 2.1"
      }
    ],
    "answer_sufficient": true,
    "audit_correlation_id": "uuid"
  }
}
```
​
---
​
## 7. Security Controls
​
- **Header injection prevention**: any `X-Trusted-Claims` or `X-Claims-Sig` header present in the incoming request is stripped before forwarding.
- **TLS termination**: gateway terminates TLS from client; re-establishes mTLS to Query Service.
- **Token revocation**: JWKS cache TTL is 5 minutes; revoked tokens remain valid for up to 5 minutes. Formal revocation list checking is deferred to `v1.1`. [v1.1]
- **CORS**: allowed origins configured to the enterprise frontend domain only.
- **Sensitive paths**: `/v1/ingest` requires a service-account token with `scope=ingest`; user tokens are rejected.
​
---
​
## 8. Kubernetes Manifest Summary
​
```yaml
Namespace: api-gateway
Deployment: api-gateway
  replicas: 2
  resources:
    requests: { cpu: "500m", memory: "512Mi" }
    limits:   { cpu: "1",    memory: "1Gi" }
Service: api-gateway (ClusterIP + Ingress)
ConfigMap: api-gateway-config
Secret: api-gateway-claims-key      # HMAC signing key
NetworkPolicy: allow ingress from 0.0.0.0/0 on 443;
               allow egress to query-service:8080, redis-gateway:6379
```
​
---
​
## 9. Test Cases
​
| Test ID | Description | Expected |
|---------|-------------|----------|
| GW-01 | Valid token, all required claims present | 200, X-Trusted-Claims forwarded |
| GW-02 | Expired token | 401 ERR_AUTH_INVALID_TOKEN |
| GW-03 | Missing `clearance_level` claim | 401 ERR_AUTH_MISSING_CLAIMS |
| GW-04 | Client injects X-Trusted-Claims header | Header stripped; gateway-derived header used |
| GW-05 | User exceeds 20 req/min | 429 ERR_GUARD_RATE_LIMIT on 21st request |
| GW-06 | JWKS endpoint unavailable | 503 (gateway cannot validate token) |
| GW-07 | User token on `/v1/ingest` | 403 (wrong scope) |