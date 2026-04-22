# DDD v1.0 04: Query Understanding and Query Routing
​
## 1. Responsibilities
​
**Query Understanding**:
- Parse the raw user query into a structured `QueryContext` (keywords, topic, doc_type, time_range, intent)
- Optionally generate query variants for multi-query expansion (L0/L1 only)
- Apply rules-based parsing for L2/L3 paths; optional LLM parsing for L0/L1
​
**Query Routing**:
- Map the structured `QueryContext` to one or more target Elasticsearch indexes
- Determine whether kNN (vector) retrieval is permitted (same-dimension tiers only)
- Output a `RoutingDecision` consumed by `SecureQueryBuilder`
​
**Not responsible for**: ACL filter assembly, ES query construction, or authorization decisions.
​
---
​
## 2. Module Location
​
Both run **inside the Query Service process**.
​
```
query-service/
└── internal/
    ├── understanding/
    │   ├── parser_rules.py       # rules-based parser (all tiers)
    │   ├── parser_llm.py         # LLM-based parser (L0/L1, optional)
    │   ├── expander.py           # multi-query expansion
    │   └── understanding.py      # orchestrator
    └── routing/
        └── router.py
```
​
---
​
## 3. Query Understanding
​
### 3.1 Parser Selection
​
```
function select_parser(user_context: UserContext) -> ParserType:
  if user_context.effective_clearance >= 2:
    return RULES_BASED    // L2/L3: no external LLM dependency on query path
  if LLM_PARSER_ENABLED:
    return LLM_BASED      // L0/L1: optional
  return RULES_BASED
```
​
### 3.2 Rules-Based Parser
​
Extracts fields via regex and keyword matching. This is the guaranteed fallback for all tiers.
​
```
function parse_rules(raw_query: string) -> QueryContext:
  context = {}
​
  // Keywords: extract noun phrases and capitalized terms
  context.keywords = extract_keywords(raw_query)     // NLP tokenize + noun-phrase extract
​
  // Topic: match against known topic vocabulary
  context.topic = match_topic_keywords(raw_query, TOPIC_VOCABULARY)
​
  // doc_type: detect patterns like "regulation", "policy", "memo", "report"
  context.doc_type = match_doc_type(raw_query, DOC_TYPE_PATTERNS)
​
  // time_range: detect years (e.g., "2024", "last year", "Q3 2023")
  context.time_range = extract_time_range(raw_query)
​
  // intent: rule-based classification
  context.intent = classify_intent_rules(raw_query)
​
  return context
```
​
**Intent classification rules** (evaluated in order; first match wins):
​
| Rule | Condition | Intent |
|------|-----------|--------|
| Contains "compare", "difference between", "vs." | regex | `comparison` |
| Contains "regulation", "policy", "rule", "procedure", "standard" | keyword | `policy_lookup` |
| Contains "summarize", "overview", "summary of", "what is" (broad) | regex | `summary` |
| Contains specific numbers, dates, proper nouns | heuristic | `factual_lookup` |
| Default | — | `factual_lookup` |
​
**Topic vocabulary** (static YAML config, `topic-vocabulary.yaml`):
​
```yaml
topics:
  finance: ["revenue", "budget", "expense", "finance", "accounting", "tax", "fiscal"]
  hr: ["employee", "hiring", "leave", "payroll", "onboarding", "performance review"]
  legal: ["contract", "agreement", "litigation", "compliance", "regulatory"]
  engineering: ["deployment", "architecture", "service", "API", "infrastructure"]
  default: []  # used when no topic matched
```
​
### 3.3 LLM-Based Parser (L0/L1 optional)
​
Used when `LLM_PARSER_ENABLED=true` and clearance < 2.
​
```
function parse_llm(raw_query: string) -> QueryContext:
  prompt = build_extraction_prompt(raw_query)
  response = llm_client.complete(prompt, model=LLM_PARSER_MODEL, timeout=LLM_PARSER_TIMEOUT_MS)
  if response.timed_out or response.error:
    log.warn("LLM parser failed, falling back to rules")
    return parse_rules(raw_query)
  return parse_llm_response(response.text)   // extract JSON from LLM output
```
​
LLM extraction prompt template:
​
```
System: You are a query parser. Extract structured fields from the user query.
Return ONLY a JSON object with these fields:
  keywords: array of key terms (max 5)
  topic: one of [finance, hr, legal, engineering, null]
  doc_type: one of [regulation, policy, report, memo, null]
  time_range: {year: int} or null
  intent: one of [factual_lookup, comparison, policy_lookup, summary]
​
User query: {{raw_query}}
```
​
Configuration:
```yaml
LLM_PARSER_ENABLED: false        # disabled by default; enable per environment
LLM_PARSER_MODEL: gpt-4o-mini    # lightweight; only for parsing
LLM_PARSER_TIMEOUT_MS: 2000
LLM_PARSER_MAX_TOKENS: 200
```
​
### 3.4 Multi-Query Expansion
​
Rule-based variants are supported on all tiers. LLM-generated variants are only permitted on L0/L1 (per HLD §05 §3). When `QUERY_EXPANSION_ENABLED=false`, no expansion runs on any tier.
​
```
function expand_queries(raw_query, context: QueryContext, user_context) -> string[]:
  if not QUERY_EXPANSION_ENABLED:
    return []
​
  variants = []
​
  // Strategy 1: Rule-based rephrasing templates (all tiers)
  if context.intent == "policy_lookup":
    variants.append("regulations about " + " ".join(context.keywords))
  if context.doc_type is not None:
    variants.append(context.doc_type + " regarding " + " ".join(context.keywords))
​
  // Strategy 2: Synonym substitution from topic vocabulary (all tiers, rules-based only)
  for keyword in context.keywords:
    synonyms = get_synonyms(keyword, SYNONYM_CONFIG)
    for syn in synonyms[:1]:    // limit to 1 synonym per keyword to stay within variant cap
      variants.append(raw_query.replace(keyword, syn))
​
  // Strategy 3: LLM-generated variants — L0/L1 ONLY; never used on L2/L3
  if user_context.effective_clearance < 2 and LLM_EXPANSION_ENABLED:
    llm_variants = generate_llm_variants(raw_query, context)
    variants.extend(llm_variants)
​
  // Cap at 3 variants total
  return deduplicate(variants)[:3]
```
​
Each expanded query variant is passed to SecureQueryBuilder independently; each receives its own ACL filter injection.
​
HyDE (Hypothetical Document Embedding) is **not enabled by default** in v1.0. Configuration toggle exists:
```yaml
HYDE_ENABLED: false    # L0/L1 only; not implemented in v1.0 baseline
```
​
---
​
## 4. Query Routing
​
### 4.1 Routing Decision Output
​
```typescript
interface RoutingDecision {
  target_indexes: string[];       // one or more of: public_index, internal_index, confidential_index, restricted_index
  allow_knn: boolean;             // false when cross-tier dimension mismatch
  routing_reason: string;         // human-readable; for logs and debug only
}
```
​
### 4.2 Routing Algorithm
​
```
function route(context: QueryContext, user_context: UserContext) -> RoutingDecision:
  // Step 1: Determine accessible indexes by clearance level
  accessible = []
  if user_context.effective_clearance >= 0: accessible.append("public_index")
  if user_context.effective_clearance >= 1: accessible.append("internal_index")
  if user_context.effective_clearance >= 2: accessible.append("confidential_index")
  if user_context.effective_clearance >= 3: accessible.append("restricted_index")
​
  // Step 2: Narrow by topic if a specific topic was detected
  if context.topic is not None:
    // Check topic-to-sensitivity affinity (from routing config)
    affinity = TOPIC_INDEX_AFFINITY.get(context.topic, None)
    if affinity is not None and affinity in accessible:
      candidates = [affinity]    // narrow to single index when strong signal
    else:
      candidates = accessible
  else:
    candidates = accessible
​
  // Step 3: Determine kNN eligibility
  // kNN is only valid within same-dimension group: L0+L1 (1536d) OR L2+L3 (1024d)
  has_l0_l1 = any(i in candidates for i in ["public_index", "internal_index"])
  has_l2_l3 = any(i in candidates for i in ["confidential_index", "restricted_index"])
  allow_knn = not (has_l0_l1 and has_l2_l3)   // cross-tier → BM25 only
​
  return RoutingDecision {
    target_indexes: candidates,
    allow_knn: allow_knn,
    routing_reason: "..."
  }
```
​
### 4.3 Topic-to-Index Affinity Config
​
```yaml
# topic-routing-config.yaml
# Maps detected topic to preferred index. Only narrows when there is strong signal.
topic_index_affinity:
  finance: internal_index       # most finance docs are internal-tier
  hr: internal_index
  legal: confidential_index
  engineering: internal_index
  # topics not listed → no narrowing, search all accessible indexes
```
​
### 4.4 Routing Decision Examples
​
| User clearance | Topic detected | Result |
|---------------|---------------|--------|
| L1 | finance | `[internal_index]`, kNN=true |
| L1 | null | `[public_index, internal_index]`, kNN=true |
| L2 | legal | `[confidential_index]`, kNN=true |
| L2 | null | `[public_index, internal_index, confidential_index]`, kNN=false (cross-tier) |
| L3 | null | `[public_index, internal_index, confidential_index, restricted_index]`, kNN=false |
​
---
​
## 5. Query Decomposition
​
For compound or comparison queries (`intent=comparison`), decompose into multiple independent sub-queries. Each sub-query is executed with its own ACL filter (HLD §05 §4).
​
```
function decompose_query(raw_query, context: QueryContext) -> string[]:
  if context.intent != "comparison":
    return [raw_query]    // no decomposition for other intents
​
  // Rule-based decomposition for v1.0; LLM-based decomposition deferred to v1.1
  sub_queries = []
​
  // Split "compare A and B" → ["Details about A", "Details about B"]
  comparison_match = extract_comparison_subjects(raw_query)
  if comparison_match:
    for subject in comparison_match.subjects:
      sub_queries.append("Details about " + subject + " regarding " + " ".join(context.keywords))
  else:
    // Fallback: treat as single query
    return [raw_query]
​
  return sub_queries
```
​
**Design constraints** (from HLD §05 §4):
- Each sub-query runs independently with its own ACL filter
- Sub-query results are merged before the reranker (deduplication by `chunk_id`)
- Decomposition triggers only on `intent=comparison`; all other intents use a single query
- v1.0 uses rule-based decomposition only; LLM decomposition is not used [v1.1]
​
---
​
## 6. Configuration Parameters
​
```yaml
UNDERSTANDING_PARSER: rules          # rules | llm
LLM_PARSER_ENABLED: false
LLM_PARSER_MODEL: gpt-4o-mini
LLM_PARSER_TIMEOUT_MS: 2000
QUERY_EXPANSION_ENABLED: false       # enables rule-based expansion on all tiers
LLM_EXPANSION_ENABLED: false         # enables LLM-generated variants; L0/L1 only
QUERY_EXPANSION_MAX_VARIANTS: 3
QUERY_DECOMPOSITION_ENABLED: true    # rule-based; triggers on intent=comparison
TOPIC_VOCAB_PATH: /config/topic-vocabulary.yaml
TOPIC_ROUTING_PATH: /config/topic-routing-config.yaml
SYNONYM_CONFIG_PATH: /config/synonym-config.yaml
HYDE_ENABLED: false
```
​
---
​
## 6. Test Cases
​
| Test ID | Input | Expected |
|---------|-------|----------|
| QU-01 | "What are the 2024 medical device regulation updates?" | keywords=[medical device, regulation, 2024], doc_type=regulation, intent=policy_lookup |
| QU-02 | "Compare the old and new finance reporting procedures" | intent=comparison, topic=finance |
| QU-03 | "Revenue figures for Q3 2023" | time_range={year:2023}, topic=finance, intent=factual_lookup |
| QU-04 | "Summarize company onboarding policy" | intent=summary, topic=hr, doc_type=policy |
| QU-05 | LLM parser timeout | Falls back to rules-based parser; no error |
| QU-06 | L2 user query, QUERY_EXPANSION_ENABLED=true | rule-based variants generated; LLM variants skipped |
| QU-07 | L1 user, topic=finance | route to `[internal_index]`, kNN=true |
| QU-08 | L3 user, no topic | route to all 4 indexes, kNN=false (cross-tier) |
| QU-09 | L2 user, query with no topic match | route to `[public_index, internal_index, confidential_index]`, kNN=false |
| QU-10 | Query Understanding failure | raw query passed through; no routing error; ACL not relaxed |