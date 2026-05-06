# SEC 10-K Retrieval Quality Improvement Plan

## Goal

Improve retrieval and answer quality for SEC 10-K markdown filings, especially questions
that target ticker/company-specific financial facts such as revenue, launch services,
risk factors, and company comparisons.

The current data is already present in Elasticsearch. The main problem is that the
right chunks do not reliably reach the model context.

## Current Findings

### Query Path After Elasticsearch

The current query path is:

```text
gateway-stub
  -> query-service /v1/query
  -> query understanding
  -> routing
  -> secure query builder
  -> Elasticsearch search
  -> normalize/deduplicate/cap candidates
  -> optional reranker client
  -> model context selection
  -> model answer
```

Important implementation details:

- `query.py` calls `reranker_rerank(...)`, but local config sets
  `RERANKER_ENABLED: "false"`.
- Even if reranking is enabled, the returned `ranked` list is currently used only for
  audit metadata. It is not used to reorder candidates before model generation.
- `generate(...)` receives the raw `all_candidates` list from Elasticsearch.
- `minimize_context(...)` sends only the first 5 L0/L1 candidates to the model.
- The system prompt instructs the model to answer exactly `Insufficient data` when
  those excerpts are not enough.

### Why Some Queries Return `Insufficient data`

The Elasticsearch index contains useful chunks, but the model often sees weak top
chunks:

- exhibit lists,
- table-of-contents text,
- front matter,
- broad accounting policy sections,
- company background sections,
- chunks where the ticker/company appears separately from the relevant financial table.

For example, a broad query like:

```text
Compare Planet Labs and BlackSky revenue trends.
```

can retrieve public-index citations, but the first 5 chunks may not include clean
revenue tables for both companies. The model is correctly following the prompt and
returning `Insufficient data`.

## Design Principles

1. Do not fetch more internet data until retrieval over existing filings is improved.
2. Preserve source facts and citations; avoid summarizing at ingestion time as the only
   searchable representation.
3. Keep ACL filters mandatory and unchanged.
4. Prefer better structure and metadata over broad prompt changes.
5. Tune chunk size only after markdown normalization and table handling are improved.

## Phase 1: Normalize SEC Markdown Before Parsing

### Problem

The current markdown parser treats only lines beginning with `#` as section headers.
The SEC markdown files mostly use bold headings and item labels such as:

```text
**Item 7. Management's Discussion and Analysis...**
**Revenue**
***Revenue and Cost Per Launch***
```

As a result, section metadata is weak and chunks become generic token windows.

### Plan

Add a SEC 10-K markdown normalization stage before `parse_markdown`.

Normalize common heading patterns into proper markdown headings:

```text
**Item 1. Business**                    -> ## Item 1. Business
**Item 1A. Risk Factors**               -> ## Item 1A. Risk Factors
**Item 7. Management's Discussion...**  -> ## Item 7. Management's Discussion...
***Revenue***                           -> ### Revenue
***Revenue and Cost Per Launch***       -> ### Revenue and Cost Per Launch
```

Also remove or mark low-value regions where safe:

- repeated `Table of Contents`,
- page number-only lines,
- image placeholders,
- long exhibit index sections when the query is not exhibit-related.

### Acceptance Criteria

- Parsed chunks have useful `section` values such as `Item 7`, `Revenue`,
  `Risk Factors`, and `Notes to Consolidated Financial Statements`.
- The normalized markdown remains readable and traceable to the original file.
- Existing non-SEC markdown fixtures still parse correctly.

## Phase 2: Extract Filing Metadata And Attach It To Every Chunk

### Problem

The markdown frontmatter contains high-value metadata:

```yaml
ticker: RKLB
company: "Rocket Lab Corp"
cik: 1819994
form: 10-K
report_date: 2025-12-31
filing_date: 2026-02-26
```

But the indexed chunks currently do not reliably carry those fields as searchable
metadata. A query like `RKLB revenue` depends on ticker text appearing in the same
chunk as the revenue table, which is usually not true.

### Plan

Parse frontmatter during local ingestion and attach these fields to `source_metadata`:

- `ticker`
- `company`
- `cik`
- `form`
- `report_date`
- `filing_date`
- `accession_number`
- `source_url`

Write these fields into each Elasticsearch document.

Add mappings for the metadata fields as `keyword` where appropriate, plus a text field
or normalized keyword for company search.

Optionally prefix chunk content before embedding/indexing with a compact searchable
header:

```text
Ticker: RKLB
Company: Rocket Lab Corp
Form: 10-K
Report date: 2025-12-31
Section: Revenue and Cost Per Launch

<chunk content>
```

### Acceptance Criteria

- Every indexed 10-K chunk includes `ticker`, `company`, `form`, and `report_date`.
- Exact ticker queries can filter or boost the matching filing.
- Company-name queries match even when the company name is not repeated in the body
  chunk.

## Phase 3: Table-Aware And Section-Aware Chunking

### Problem

Current chunking slices parsed section text by token count. For financial filings this
can split:

- table title from the table,
- header row from data rows,
- year labels from values,
- company identity from financial facts.

Reducing chunk size alone may worsen this if tables are split across chunks.

### Plan

Make chunking section-aware and table-aware:

1. Split by normalized section first.
2. Detect markdown tables as block units.
3. Keep table title, nearby heading, and table rows together when possible.
4. For large tables, split by row groups while repeating the table heading and column
   header in each chunk.
5. For prose, use smaller token windows than today.

Initial tuning proposal:

```text
prose chunk size: 250-350 tokens
prose overlap:    40-60 tokens
table chunk size: allow larger bounded chunks, around 500-700 tokens
```

### Acceptance Criteria

- Revenue tables retain company, section, year labels, and values in the same chunk.
- `Item 7` and `Item 8` financial chunks are not dominated by exhibit-list text.
- Search for `RKLB revenue launch services` returns revenue table chunks near the top.
- Search for `Planet Labs revenue fiscal year 2026` returns Planet revenue chunks near
  the top.

## Phase 4: Improve Retrieval Ranking Before Model Context

### Problem

The query path currently passes raw Elasticsearch candidate order into model context.
Only the first 5 chunks are used for L0/L1 answers.

### Plan

Make candidate ordering explicit before generation.

Short-term local rerank:

- boost exact ticker match,
- boost exact company match,
- boost section matches such as `Revenue`, `Results of Operations`, `Risk Factors`,
- penalize exhibit lists and table-of-contents chunks unless the query asks for exhibits,
- prefer chunks that contain multiple query entities for simple factual lookup,
- for comparison queries, enforce representation from each compared entity.

Longer-term reranker:

- enable `RERANKER_ENABLED`,
- deploy the reranker service locally when practical,
- reorder `all_candidates` using `ranked` before calling `generate(...)`.

### Acceptance Criteria

- `ranked` candidates affect the model context order.
- The top 5 model chunks are selected after reranking, not raw ES order.
- Comparison queries include relevant chunks for both entities when available.

## Phase 5: Comparison Query Retrieval Strategy

### Problem

The current comparison decomposition is rule-based and limited. A query such as:

```text
Compare Planet Labs and BlackSky revenue trends.
```

should retrieve good Planet revenue chunks and good BlackSky revenue chunks separately,
then combine them. A single broad query can over-retrieve generic chunks from only one
company.

### Plan

Add entity-aware retrieval for comparisons:

1. Detect company/ticker mentions from indexed metadata.
2. Build one sub-query per entity:

```text
Planet Labs revenue trends
BlackSky revenue trends
```

3. Apply metadata filters or boosts:

```text
ticker: PL
ticker: BKSY
```

4. Merge results with per-entity quotas before reranking/context selection.

### Acceptance Criteria

- Comparison context contains at least one high-quality chunk for each detected entity.
- If one entity has no matching evidence, the response can say which side is missing.
- The model no longer receives only Planet exhibit chunks for a Planet-vs-BlackSky
  revenue question.

## Phase 6: Evaluation Set

Create a small repeatable eval set for the ingested space 10-K filings.

Initial questions:

```text
What does Rocket Lab report about revenue and launch services?
What revenue did Planet Labs report for fiscal year 2026?
What revenue did BlackSky report for 2025?
Compare Planet Labs and BlackSky revenue trends.
What are the main risk factors disclosed by AST SpaceMobile?
What does Iridium say about government service revenue?
```

For each question, track:

- whether citations are returned,
- whether cited chunks are from the expected ticker/company,
- whether the answer is sufficient,
- whether the cited chunk contains the required numeric evidence,
- latency.

### Acceptance Criteria

- The eval can be run after local ingestion.
- Failures show whether the problem is routing, ES retrieval, candidate ranking, or
  model context generation.

## Proposed Implementation Order

1. Implement frontmatter metadata extraction and index fields.
2. Normalize SEC markdown headings and low-value sections.
3. Add table-aware chunking.
4. Re-ingest the 10-K files with smaller section-aware chunks.
5. Add lightweight local reranking and use its output for model context.
6. Add comparison/entity-aware retrieval.
7. Build the eval set and tune thresholds.

## Open Questions

- Should normalized markdown be written back to disk for inspection, or kept as an
  ingestion-only derived representation?
- Should exhibit sections be indexed but downranked, or excluded from the main
  `public_index` and placed in a secondary index?
- Should chunk content include metadata headers before embedding, or should metadata be
  used only as ES fields and query boosts?
- What is the desired local reranker: deterministic rule-based first, or deploy the
  existing reranker service?

