# QA Test Plan

This QA plan is for a human tester who will execute the system manually and record evidence. It complements the automated E2E plan.

Use this with:

- `docs/test/qa-execution-runbook.md`
- `docs/test/e2e-test-plan.md`
- `docs/test/e2e-troubleshooting.md`

## Goal

QA verifies that the deployed RAG system behaves correctly from a user point of view:

- Valid users can ask questions.
- Unauthorized users cannot see restricted content.
- The system gives citations when it has data.
- The system says insufficient data when it does not have data.
- Errors do not leak internal details.
- Local secrets are not committed.
- The operator can repeat the run and explain failures.

## Test Environments

Run QA in this order:

1. `local_test`
   - Stubbed LLM.
   - No OpenAI cost.
   - Best for functional QA.

2. `local`
   - Real OpenAI LLM and embeddings.
   - Costs tokens.
   - Best for real-provider smoke QA.

Do not start with `local` unless `local_test` is healthy.

## QA Roles

QA operator:

- Runs the commands.
- Records actual output.
- Marks each test pass, fail, skip, or blocked.
- Does not change code during the test.

Developer:

- Fixes failed tests.
- Explains known limitations.
- Provides missing seed data or environment fixes.

## Test Data Concepts

The mock users are represented by tokens:

| Token | Meaning |
|---|---|
| `test-token-l0` | Public user |
| `test-token-l1` | Internal engineering user |
| `test-token-l1-b` | Internal public-only user |
| `test-token-l2` | Confidential-level user |
| `test-token-l3` | Restricted-level user |
| `test-token-attacker` | Low-privilege attacker |
| `test-token-no-acl` | User with no ACL groups |

The system should never trust a user just because the query asks for access. Access comes from signed claims produced by the gateway.

## QA Entry Criteria

Start QA only when:

- Docker images are built.
- Helm release is deployed.
- `gateway-stub` pod is running.
- `query-service` pod is running.
- Elasticsearch pod is running.
- Redis pod is running.
- Gateway `/healthz` passes.
- Gateway `/readyz` passes.

For data-dependent QA, also require:

- Retrieval indexes exist.
- Audit alias exists.
- Expected chunks are present.

## QA Exit Criteria

QA can sign off when:

- All P0 and P1 test cases pass.
- P2 failures are documented and accepted.
- No real secrets are staged in git.
- Test result notes include commands, pass/fail counts, and blockers.

## Severity

P0:

- Security leak.
- Wrong user can see restricted content.
- Real secret appears in staged git content.
- System cannot answer any query.

P1:

- Valid user flow broken.
- Citations missing when data exists.
- OpenAI-backed local profile cannot call provider.
- Error responses leak internal index names.

P2:

- Documentation confusion.
- Non-critical test flake.
- Performance slower than expected on local machine.

## Manual QA Test Cases

| ID | Area | Test | Expected |
|---|---|---|---|
| QA-001 | Deploy | Helm release status | `STATUS: deployed` |
| QA-002 | Deploy | Required pods running | Gateway, query, ES, Redis are running |
| QA-003 | Gateway | `/healthz` | Returns ok |
| QA-004 | Gateway | `/readyz` | Users loaded |
| QA-005 | Auth | Missing auth header | Request is rejected |
| QA-006 | Auth | Invalid token | Request is rejected |
| QA-007 | Query | L1 valid question | HTTP 200 |
| QA-008 | Query | Unknown question | Insufficient data |
| QA-009 | ACL | L1 cannot see L2 data | No L2 citations |
| QA-010 | ACL | L2 can see L2 data | L2 citation appears if seeded |
| QA-011 | Isolation | L1 and L1-B differ | Engineering-only data hidden from L1-B |
| QA-012 | Security | Prompt injection | Blocked or no metadata leak |
| QA-013 | Security | Sensitive title enumeration | Attacker gets no citations |
| QA-014 | Error | Oversized query | 400/422 without index names |
| QA-015 | Secrets | Git ignored real secret file | `values-local.secret.yaml` ignored |
| QA-016 | Provider | `local` config uses OpenAI | ConfigMap shows OpenAI model |
| QA-017 | Audit | Audit alias exists | `audit-events-current` alias exists |
| QA-018 | Cache | Redis responds | `PONG` or cache test passes |

## Evidence To Capture

For every QA run, save:

- Date.
- Git status summary.
- Helm status.
- Pod status.
- ConfigMap provider check.
- Health check outputs.
- Manual query output snippets.
- Automated pytest result line.
- Any failed command and its full error text.

Do not capture or paste real API keys.

## Result Template

```text
QA Run:
Date:
Tester:
Profile:
Git status:
Helm revision:
Data readiness:

QA-001:
QA-002:
QA-003:
QA-004:
QA-005:
QA-006:
QA-007:
QA-008:
QA-009:
QA-010:
QA-011:
QA-012:
QA-013:
QA-014:
QA-015:
QA-016:
QA-017:
QA-018:

Automated E2E result:
Open blockers:
Signoff:
```
