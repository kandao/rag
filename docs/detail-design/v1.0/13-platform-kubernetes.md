# DDD v1.0 13: Platform and Kubernetes
​
## 1. Purpose
​
Defines the Kubernetes topology, namespace design, network policies, RBAC, secrets management, and deployment patterns for `v1.0`. This document is the implementation reference for the platform/infrastructure team.
​
---
​
## 2. Namespace Design
​
```
┌─────────────────────────────────────────────────────────────┐
│ api-gateway      API Gateway pods                           │
│ query            Query Service pods                         │
│ reranker         Reranker Service GPU pods                  │
│ ingestion        Ingestion pipeline worker pods             │
│ retrieval-deps   Elasticsearch, Redis, Audit ES             │
│ cert-manager     TLS cert issuance (Let's Encrypt or CA)    │
│ monitoring       Prometheus, Grafana, OpenTelemetry Collector│
└─────────────────────────────────────────────────────────────┘
​
[v1.1 Reserved]
│ control-plane    Principal Service, Group Sync, Token Registry
```
​
---
​
## 3. Network Policies
​
All namespaces default-deny. Explicit allow rules:
​
### api-gateway
​
```yaml
# Allow inbound from internet (via Ingress/LoadBalancer)
# Allow outbound to: query:8080, redis (rate-limiting DB)
# Allow outbound to: DNS
​
NetworkPolicy: api-gateway-egress
  egress:
    - to namespace=query, port=8080
    - to namespace=kube-system (DNS)
    - to external: IdP JWKS endpoint (by IP or FQDN; implementation-dependent)
```
​
### query
​
```yaml
# Allow inbound from: api-gateway
# Allow outbound to: retrieval-deps (ES:9200, Redis:6379),
#                    reranker:8080, model endpoints, audit-es:9200
# Allow outbound to: DNS, embedding API
​
NetworkPolicy: query-ingress
  ingress:
    - from namespace=api-gateway, port=8080
​
NetworkPolicy: query-egress
  egress:
    - to namespace=retrieval-deps, port=9200  # ES
    - to namespace=retrieval-deps, port=6379  # Redis
    - to namespace=reranker, port=8080
    - to external: model endpoints (by CIDR or FQDN)
    - to external: embedding API (L0/L1 only)
    - to kube-system (DNS)
```
​
### reranker
​
```yaml
# Allow inbound from: query only
# Allow outbound to: DNS only (no external API calls)
​
NetworkPolicy: reranker-ingress
  ingress:
    - from namespace=query, port=8080
​
NetworkPolicy: reranker-egress
  egress:
    - to kube-system (DNS)
```
​
### ingestion
​
```yaml
# Allow inbound from: job triggers (internal only)
# Allow outbound to: retrieval-deps (ES, Redis), embedding API, source connectors
​
NetworkPolicy: ingestion-egress
  egress:
    - to namespace=retrieval-deps, port=9200
    - to namespace=retrieval-deps, port=6379
    - to external: embedding API, source systems
    - to kube-system (DNS)
```
​
### retrieval-deps
​
```yaml
# ES: only from query + ingestion
# Redis: only from query + ingestion + api-gateway
​
NetworkPolicy: es-ingress
  ingress:
    - from namespace=query, port=9200
    - from namespace=ingestion, port=9200
​
NetworkPolicy: redis-ingress
  ingress:
    - from namespace=query, port=6379
    - from namespace=ingestion, port=6379
    - from namespace=api-gateway, port=6379
```
​
---
​
## 4. mTLS Service Mesh
​
All intra-cluster communication uses mTLS. In v1.0, this is implemented via **Istio** or **Cilium** (environment-dependent). Service-to-service identity is tied to Kubernetes ServiceAccount → SPIFFE SVID.
​
```yaml
# Example: Istio PeerAuthentication — enforce mTLS for query namespace
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: query
spec:
  mtls:
    mode: STRICT
```
​
Without a service mesh, the alternative is to configure mutual TLS directly on each service using cert-manager-issued certificates.
​
---
​
## 5. Secrets Management
​
All secrets are stored in Kubernetes `Secret` objects. **Never in ConfigMaps or environment variables set directly in pod specs.**
​
| Secret Name | Namespace | Contents |
|------------|-----------|----------|
| `api-gateway-claims-key` | api-gateway | HMAC signing key (base64) |
| `es-credentials` | query, ingestion | ES username + password |
| `redis-secret` | retrieval-deps | Redis password |
| `model-api-key-l0l1` | query | Cloud LLM API key |
| `audit-es-credentials` | query | Audit ES username + password |
| `embedding-api-key` | query, ingestion | Embedding API key (L0/L1) |
​
Secrets are created via:
```bash
kubectl create secret generic es-credentials \
  --from-literal=username=query-service \
  --from-literal=password='<generated>' \
  -n query
```
​
For production, secrets should be managed via an external secrets manager (HashiCorp Vault, AWS Secrets Manager) with the External Secrets Operator syncing into Kubernetes Secrets.
​
---
​
## 6. RBAC
​
### 6.1 ServiceAccounts
​
Each pod uses a dedicated ServiceAccount:
​
```yaml
ServiceAccount: api-gateway-sa      # namespace: api-gateway
ServiceAccount: query-service-sa    # namespace: query
ServiceAccount: reranker-sa         # namespace: reranker
ServiceAccount: ingestion-worker-sa # namespace: ingestion
ServiceAccount: es-sa               # namespace: retrieval-deps
```
​
### 6.2 Kubernetes RBAC Roles
​
```yaml
# query-service: can read its own secrets, configmaps; no cluster-wide access
Role: query-service-role
  namespace: query
  rules:
    - apiGroups: [""]
      resources: ["secrets", "configmaps"]
      verbs: ["get", "list"]
​
# ingestion-worker: same scope in ingestion namespace
Role: ingestion-worker-role
  namespace: ingestion
  rules:
    - apiGroups: [""]
      resources: ["secrets", "configmaps"]
      verbs: ["get", "list"]
```
​
No pod should have `ClusterRole` access unless it is the platform admin.
​
---
​
## 7. Deployment Manifests Summary
​
All services follow the same Deployment pattern:
​
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: query-service
  namespace: query
spec:
  replicas: 1    # v1.0 baseline is a single pod per HLD §10 §2; scale up via HPA as load grows
  selector:
    matchLabels:
      app: query-service
  template:
    metadata:
      labels:
        app: query-service
      annotations:
        # Istio sidecar injection
        sidecar.istio.io/inject: "true"
    spec:
      serviceAccountName: query-service-sa
      containers:
        - name: query-service
          image: rag/query-service:v1.0
          ports:
            - containerPort: 8080
          resources:
            requests: { cpu: "1", memory: "1Gi" }
            limits:   { cpu: "2", memory: "2Gi" }
          envFrom:
            - configMapRef:
                name: query-service-config
          env:
            - name: ES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: es-credentials
                  key: password
            - name: MODEL_API_KEY
              valueFrom:
                secretKeyRef:
                  name: model-api-key-l0l1
                  key: api_key
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
```
​
---
​
## 8. HPA (Horizontal Pod Autoscaler)
​
```yaml
# Query Service: scale on CPU
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: query-service-hpa
  namespace: query
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: query-service
  minReplicas: 1    # v1.0 starts with 1 pod; HPA allows scaling beyond 1 under load
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
​
# Reranker Service: scale on GPU queue depth (custom metric via DCGM exporter)
# In v1.0 static replicas; HPA added in v1.1 based on observed load
```
​
---
​
## 9. ConfigMap Convention
​
Each service has one ConfigMap with non-sensitive configuration:
​
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: query-service-config
  namespace: query
data:
  LOG_LEVEL: "info"
  ENVIRONMENT: "production"
  TOKEN_SCHEMA_VERSION: "v1"
  ACL_VERSION: "v1"
  ACL_TOKEN_MAX_COUNT: "30"
  REDIS_HOST: "redis.retrieval-deps"
  REDIS_PORT: "6379"
  ES_HOSTS: "https://elasticsearch.retrieval-deps:9200"
  RERANKER_URL: "http://reranker-service.reranker:8080"
  AUDIT_ES_HOSTS: "https://audit-elasticsearch.retrieval-deps:9200"
  RESULT_CACHE_TTL_S: "60"
  EMBEDDING_CACHE_TTL_S: "3600"
  RERANKER_TIMEOUT_MS: "1000"
  # ... (see individual DDD documents for full parameter lists)
```
​
---
​
## 10. Ingress
​
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-gateway-ingress
  namespace: api-gateway
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "1m"
spec:
  tls:
    - hosts:
        - rag-api.company.internal
      secretName: api-gateway-tls
  rules:
    - host: rag-api.company.internal
      http:
        paths:
          - path: /v1
            pathType: Prefix
            backend:
              service:
                name: api-gateway
                port:
                  number: 443
```
​
---
​
## 11. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| K8S-01 | Pod in `query` namespace attempts to reach `reranker` on non-8080 port | Blocked by NetworkPolicy |
| K8S-02 | Pod in `ingestion` namespace attempts to reach `query` namespace | Blocked |
| K8S-03 | `query-service-sa` attempts to create a Pod | Rejected (no ClusterRole) |
| K8S-04 | Pod reads secret `es-credentials` | Succeeds (Role binding in place) |
| K8S-05 | Query Service pod crashes → HPA scales up | New pod starts; traffic continues |
| K8S-06 | Rolling update of query-service | Zero downtime; health probes prevent routing to unready pods |
| K8S-07 | Reranker pod on non-GPU node | Pod stays Pending (nodeSelector enforced) |