# SEC 10-K RAG Eval

This eval checks the currently loaded public SEC 10-K corpus through the real
gateway/query-service path.

## Files

- `evals/sec_10k_rag_eval.jsonl`: JSONL eval cases.
- `tools/eval_rag.py`: CLI runner.

## Run

Start or reuse the gateway port-forward:

```bash
kubectl -n api-gateway port-forward svc/gateway-stub 8080:8080
```

Then run:

```bash
${PYTHON:-python} \
  tools/eval_rag.py \
  --dataset evals/sec_10k_rag_eval.jsonl \
  --gateway-url http://127.0.0.1:8080
```

Optional JSON output:

```bash
${PYTHON:-python} \
  tools/eval_rag.py \
  --json-output /private/tmp/sec_10k_rag_eval_results.json
```

## What It Measures

Each case can assert:

- expected answer sufficiency,
- minimum or maximum citation count,
- expected ticker/source marker in citations,
- expected citation section/content terms,
- required answer terms,
- forbidden answer terms.

The eval intentionally avoids exact `chunk_id` expectations. Chunk IDs can change after
legitimate parser or chunker improvements, while the stable behavior we care about is:
the answer is sufficient when the corpus contains the fact, cites the right filing, and
includes the expected factual values.

## Current Baseline

Last local run against the current 10-K index:

```text
RAG eval: 6/10 passed (60.0%)
```

Passing cases:

- BlackSky AI-enabled software platform.
- Planet Labs fiscal 2026 total revenue.
- AST SpaceMobile SpaceMobile Service revenue status.
- Globalstar replacement satellite launch timing.
- Vacation policy no-answer.
- Rocket Lab fiscal 2099 guidance no-answer.

Failing cases:

- Rocket Lab 2025 vs. 2024 revenue comparison.
- Intuitive Machines cash and working capital.
- Redwire contracted backlog.
- Rocket Lab backlog split between space systems and launch services.

The failures are not dataset-format issues. They indicate that relevant chunks either
do not make it into the top model context or are displaced by weaker nearby chunks.
These cases should be kept as regression targets for retrieval ranking, table-aware
chunking, and context selection work.
