# RAG v1.0 — HLD Eval / E2E Test Cases

> Carved out of the original combined `test-plan.md`. These tests are **not** run during development.
> They are run against a fully deployed environment as pre-launch quality and security gates.
> All test IDs are prefixed `HLD-` to distinguish them from the DDD unit/integration tests in `test-plan-unit.md`.
> Skipped HLD tests (those already covered by DDD tests in `test-plan-unit.md`): ACL-01/02/03/06/07, INJ-01–06, ENUM-01–02, FC-01–06, RNK-03–04, TOK-01/02/04/05, AUD-01–05, CACHE-02/03, ING-01–03.

**Total: 29 HLD eval / E2E tests.**

> **Test type legend**:
> - **Integration** — real ES/Redis/Kafka; no LLM
> - **E2E** — full stack with real LLM API calls
> - **Load** — requires deployed cluster + concurrent users

### HLD Eval / E2E Gate → Test ID Lookup

| Gate | Test IDs | Type |
|------|----------|------|
| Retrieval quality gate (pre-launch) | HLD-RET-01 – HLD-RET-07 | E2E |
| Reranker quality gate (pre-launch) | HLD-RNK-01, HLD-RNK-02 | E2E |
| Answer quality gate (pre-launch) | HLD-ANS-01 – HLD-ANS-06 | E2E |
| Performance gate (pre-launch) | HLD-PERF-01 – HLD-PERF-05, HLD-CACHE-01 | Load / Integration |
| ACL boundary + isolation (integration env) | HLD-ACL-04, HLD-ACL-05, HLD-ACL-08 | Integration |
| Security gaps (integration env) | HLD-INJ-07, HLD-ENUM-03, HLD-ENUM-04, HLD-ENUM-05, HLD-TOK-03 | Integration / Unit |

---

## 14. Retrieval Quality (`HLD/12 §3.1`) — E2E

> **Test type**: E2E — requires real Elasticsearch, real embedding service, and a ground-truth dataset of 50 annotated chunks per test index (see HLD/12 §2.3).

| Test ID | Description | Input | Pass Criteria |
|---------|-------------|-------|---------------|
| HLD-RET-01 | Recall@5 (authorized user) | 50 ground truth queries | Recall@5 ≥ 0.70 |
| HLD-RET-02 | Recall@10 (authorized user) | Same as above | Recall@10 ≥ 0.80 |
| HLD-RET-03 | MRR (Mean Reciprocal Rank) | Same as above | MRR ≥ 0.60 |
| HLD-RET-04 | BM25 exact term match | Queries containing proper nouns, numbers, and dates | Correct chunk in Top 10 |
| HLD-RET-05 | Semantic match without keyword hit | Queries expressed with synonyms | Correct chunk in Top 10 |
| HLD-RET-06 | Multi-index query across tier merge | `user_l1` querying topics spanning L0 + L1 | Results from both indexes appear in candidate set |
| HLD-RET-07 | ACL filter correctly narrows results | `user_l1` query where ground truth includes L2 chunks | L2 chunks do not appear in candidate set |

---

## 14b. Reranker Quality (`HLD/12 §3.2`) — E2E

> **Test type**: E2E — requires real Elasticsearch and a ground-truth dataset. Measures precision improvement and scope preservation with real ranked results.

| Test ID | Description | Pass Criteria |
|---------|-------------|---------------|
| HLD-RNK-01 | Precision@5 (reranker output vs. retrieval order) | Reranker Precision@5 ≥ retrieval Precision@5 + 0.10 |
| HLD-RNK-02 | Reranker does not change authorized scope | All chunks in reranker output are within the authorized candidate set |

---

## 15. Answer Quality (`HLD/12 §3.3`) — E2E

> **Test type**: E2E — requires real LLM API calls (cloud model for L0/L1, private model for L2/L3). Use an LLM judge or human evaluator for ANS-01/02.

| Test ID | Description | Pass Criteria |
|---------|-------------|---------------|
| HLD-ANS-01 | Faithfulness (answer traceable to retrieved chunks) | ≥ 90% of answer sentences can be traced to a citation chunk |
| HLD-ANS-02 | Relevance (answer is relevant to the question) | Human or LLM judge score ≥ 4/5 |
| HLD-ANS-03 | No hallucination (no fabricated additions) | For questions where context is insufficient, returns "Insufficient data" rather than a fabricated answer (all 10 no-answer queries must pass) |
| HLD-ANS-04 | Citation correctness | Citation's `chunk_id`, `path`, and `page_number` match the actual retrieved chunk |
| HLD-ANS-05 | ACL metadata does not appear in answers | Answer does not contain `allowed_groups`, `acl_tokens`, or `group:` prefix content |
| HLD-ANS-06 | Answer Verification (L1+) | When context is insufficient, Verification correctly returns insufficient (10 cases, accuracy ≥ 80%) |

---

## 16. ACL Boundary + Cross-User Isolation (`HLD/12 §4.1`) — Integration

> **Test type**: Integration — requires real Elasticsearch seeded with boundary chunks (HLD/12 §2.3). No LLM needed.

| Test ID | Description | Input | Expected Behavior |
|---------|-------------|-------|-------------------|
| HLD-ACL-04 | Boundary chunk accessible (clearance == sensitivity) | `user_l2` (clearance=L2) queries a sensitivity=L2 chunk | Chunk appears in results (boundary must be accessible) |
| HLD-ACL-05 | Boundary chunk inaccessible (clearance < sensitivity) | `user_l1` (clearance=L1) queries a sensitivity=L2 chunk | Chunk does not appear in results |
| HLD-ACL-08 | Cross-user isolation | `user_l1_a` and `user_l1_b` query the same query but each has partial document access | Results differ between the two users; each sees only authorized chunks |

---

## 17. Security Gaps (`HLD/12 §4.3–4.5`) — Mixed

| Test ID | Description | Input | Expected Behavior | Type |
|---------|-------------|-------|-------------------|------|
| HLD-INJ-07 | Context manipulation: accumulated over long conversation | 10 consecutive turns attempting to guide LLM into leaking context | LLM does not reveal chunk metadata or other user data in its responses | E2E |
| HLD-ENUM-03 | Result count cap | Any query | Number of returned chunks does not exceed Top-N limit (default 5) | Unit |
| HLD-ENUM-04 | Side channel: document does not exist vs. unauthorized | `attacker` queries a known sensitive document title | Same ambiguous error message returned; cannot determine from the error whether the document exists | Integration |
| HLD-ENUM-05 | Error message does not leak internal paths | Any error response | Error message does not contain index names, chunk_id, or `acl_tokens` content | Integration |
| HLD-TOK-03 | False-allow test | Construct a token combination that collides with a high-privilege user's tokens | Low-privilege user does not gain access to high-sensitivity documents due to token collision | Integration |

---

## 18. Performance and Cache (`HLD/12 §5`) — Load / Integration

> **Test type**: Load tests (PERF) require a deployed cluster with a load testing tool (e.g. k6, Locust). Cache test requires real Redis.

### Query Latency

> Test conditions: single index, 10 concurrent users, 5 minutes duration.

| Test ID | Sensitivity Tier | Metric | Pass Criteria | Type |
|---------|-----------------|--------|---------------|------|
| HLD-PERF-01 | L0 | P95 end-to-end latency | ≤ 2s | Load |
| HLD-PERF-02 | L1 | P95 end-to-end latency | ≤ 2s | Load |
| HLD-PERF-03 | L2 | P95 end-to-end latency | ≤ 3s (higher allowance for private model path) | Load |
| HLD-PERF-04 | L1 (reranker enabled) | P95 reranker latency alone | ≤ 500ms (GPU service) | Load |
| HLD-PERF-05 | L1 | P99 latency | ≤ 5s | Load |

### Cache Effectiveness

| Test ID | Description | Input | Pass Criteria | Type |
|---------|-------------|-------|---------------|------|
| HLD-CACHE-01 | ACL auth-cache hit rate | 100 queries from the same user (identical `claims_hash`) | Redis auth-cache hit rate ≥ 80% | Integration |
