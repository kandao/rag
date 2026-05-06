#!/usr/bin/env python3
"""Run a JSONL eval set against the gateway /v1/query endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TOKENS = {
    "l0": "test-token-l0",
    "l1": "test-token-l1",
    "l1_b": "test-token-l1-b",
    "l2": "test-token-l2",
    "l3": "test-token-l3",
    "attacker": "test-token-attacker",
    "no_acl": "test-token-no-acl",
}


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    latency_ms: int
    failures: list[str]
    response: dict[str, Any] | None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            cases.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return cases


def _lower_text(value: Any) -> str:
    return str(value or "").lower()


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _query_gateway(
    *,
    gateway_url: str,
    token: str,
    query: str,
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    url = gateway_url.rstrip("/") + "/v1/query"
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = {"http_status": exc.code, "error": raw}
    except urllib.error.URLError as exc:
        payload = {"http_status": "connection_error", "error": str(exc.reason)}
    latency_ms = int((time.monotonic() - started) * 1000)
    return latency_ms, payload


def _evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    answer = _lower_text(response.get("answer"))
    citations = response.get("citations") or []
    citation_blob = "\n".join(
        " ".join(
            _lower_text(c.get(field))
            for field in ("path", "section", "content", "source_index")
        )
        for c in citations
    )

    if "http_status" in response:
        return [f"HTTP {response['http_status']}: {response.get('error', '')[:200]}"]

    expected_sufficient = case.get("expected_answer_sufficient")
    if expected_sufficient is not None and response.get("answer_sufficient") != expected_sufficient:
        failures.append(
            f"answer_sufficient expected {expected_sufficient}, got {response.get('answer_sufficient')}"
        )

    min_citations = case.get("min_citations")
    if min_citations is not None and len(citations) < int(min_citations):
        failures.append(f"expected at least {min_citations} citations, got {len(citations)}")

    max_citations = case.get("max_citations")
    if max_citations is not None and len(citations) > int(max_citations):
        failures.append(f"expected at most {max_citations} citations, got {len(citations)}")

    for group in case.get("required_answer_terms", []):
        if not _contains_any(answer, list(group)):
            failures.append(f"answer missing one of {group}")

    for term in case.get("forbidden_answer_terms", []):
        if term.lower() in answer:
            failures.append(f"answer contains forbidden term {term!r}")

    for ticker in case.get("expected_tickers", []):
        ticker_l = ticker.lower()
        if ticker_l not in citation_blob:
            failures.append(f"citations missing ticker/source marker {ticker}")

    for term in case.get("citation_section_terms", []):
        if term.lower() not in citation_blob:
            failures.append(f"citations missing section/content term {term!r}")

    return failures


def run_eval(
    *,
    cases: list[dict[str, Any]],
    gateway_url: str,
    tokens: dict[str, str],
    timeout_s: float,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for case in cases:
        token_key = case.get("token", "l0")
        token = tokens.get(token_key, token_key)
        latency_ms, response = _query_gateway(
            gateway_url=gateway_url,
            token=token,
            query=case["query"],
            timeout_s=timeout_s,
        )
        failures = _evaluate_case(case, response)
        results.append(
            EvalResult(
                case_id=case["id"],
                passed=not failures,
                latency_ms=int(response.get("latency_ms") or latency_ms),
                failures=failures,
                response=response,
            )
        )
    return results


def _print_summary(results: list[EvalResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg_latency = sum(r.latency_ms for r in results) / total if total else 0
    print(f"RAG eval: {passed}/{total} passed ({passed / total:.1%}), avg latency {avg_latency:.0f} ms")
    print()
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.case_id} ({result.latency_ms} ms)")
        for failure in result.failures:
            print(f"  - {failure}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RAG eval cases against /v1/query")
    parser.add_argument(
        "--dataset",
        default="evals/sec_10k_rag_eval.jsonl",
        help="JSONL eval dataset path",
    )
    parser.add_argument(
        "--gateway-url",
        default="http://127.0.0.1:8080",
        help="Gateway base URL",
    )
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-query timeout in seconds")
    parser.add_argument("--case", action="append", help="Run only a case id; can be repeated")
    parser.add_argument("--limit", type=int, help="Run only the first N selected cases")
    parser.add_argument("--fail-under", type=float, default=1.0, help="Minimum pass rate required")
    parser.add_argument("--json-output", help="Write detailed JSON results to this path")
    args = parser.parse_args()

    cases = _load_jsonl(Path(args.dataset))
    if args.case:
        selected = set(args.case)
        cases = [case for case in cases if case["id"] in selected]
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print("No eval cases selected", file=sys.stderr)
        return 2

    results = run_eval(
        cases=cases,
        gateway_url=args.gateway_url,
        tokens=DEFAULT_TOKENS,
        timeout_s=args.timeout,
    )
    _print_summary(results)

    if args.json_output:
        output = [
            {
                "case_id": r.case_id,
                "passed": r.passed,
                "latency_ms": r.latency_ms,
                "failures": r.failures,
                "response": r.response,
            }
            for r in results
        ]
        Path(args.json_output).write_text(json.dumps(output, indent=2), encoding="utf-8")

    pass_rate = sum(1 for r in results if r.passed) / len(results)
    return 0 if pass_rate >= args.fail_under else 1


if __name__ == "__main__":
    raise SystemExit(main())
