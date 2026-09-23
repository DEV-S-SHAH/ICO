# Plan: Expanding Testing Datasets for ico-cache

Status: `DRAFT` — proposal only, nothing implemented unless approved.

## 1. Motivation (current gaps)

| Area | Current data | Gap |
| :--- | :--- | :--- |
| Semantic hits | 50-query benchmark; every row is `EXACT` or `NONE` (`benchmark_results/responses_50_queries.json`) | No *near-duplicate* queries — the `serve_threshold` boundary (0.6–0.99 similarity) is never exercised |
| False hits | `fixtures_gen.py` synthetic `near_miss_negatives.jsonl` | No real adversarial paraphrase sets (high lexical overlap, different intent) |
| Context binding | `context_dependent.jsonl` (synthetic) | No multi-context, real-document QA to test L1 `in_context` binding + L2/L3 TTL |
| Multi-tenant | Synthetic tenants + adversarial payloads | No overlapping real corpus across tenants → weak isolation proof |
| Ingestion loaders | Synthetic PDF/HTML/JSONL/code files | No real-world PDF/OCR/Office/CSV/code corpus |
| Cost/latency model | 50 queries, generated | Too small and biased toward `EXACT`; true hit-rate economics untested |
| Multilinguality | none | Semantic gate across languages untested |
| Invalidation | unit tests only | No versioned-document corpus to prove stale answers are dropped |

## 2. Datasets to add

| # | Dataset | Source | Purpose | Size target |
| :-: | :--- | :--- | :--- | :--- |
| 1 | Paraphrase pairs (graded similarity) | Quora Question Pairs / MRPC, or LLM-generated clusters | Drive `serve_threshold` boundary, semantic-tier hits | ~1k pairs |
| 2 | Adversarial near-miss negatives | PAWS, QQP non-duplicates, MNLI contradictions | Prove 0% false-hit baseline | ~1k pairs |
| 3 | Context-dependent QA | HotpotQA, FiQA, XSum | Same question, many contexts → L1 binding, TTL | ~500 q/ctx |
| 4 | Overlapping tenant corpus | CNN/DailyMail, SEC EDGAR | Cross-tenant isolation (near-identical content per tenant) | 2 tenants × ~200 docs |
| 5 | Document-type corpora | S2ORC/arXiv (PDF), rvl-cdip/FUNSD (OCR), Amazon CSVs (structured), GitHub code (AST) | Real ingestion-loader coverage | 5–20 files/type |
| 6 | Realistic query traffic | MS MARCO dev, LMSYS-Chat-1M sampled | Honest hit-rate + cost/latency model | ~1k queries |
| 7 | Multilingual paraphrases | PAWS-X, XNLI | Cross-language semantic gate | ~500 pairs |
| 8 | Versioned documents | Wikipedia revision dumps (2 snapshots) | Invalidation + staleness (TTL) | 2 snapshots × 100 docs |

## 3. Where it plugs in

- `eval_harness.py` — extends the existing `paraphrases.jsonl` / `near_miss_negatives.jsonl` /
  `context_dependent.jsonl` / `cross_type_adversarial.jsonl` inputs with the real datasets
  (new `--data-dir` takes precedence over `fixtures_gen.py` output).
- `fixtures_gen.py` — kept as the offline fallback; real corpora fetched optionally via
  `scripts/fetch_test_data.py` (no-nets fallback preserved for air-gapped runs).
- `benchmark_results/` — new `responses_1000_queries.json` produced by the benchmark harness;
  `scripts/cost_analysis.py` + `cost-analysis.yml` continue to operate unchanged (schema kept).
- `packages/ico-cache-py/tests/` — unit tests extended where behaviour changes (e.g. TTL expiry
  at scale, cross-tenant overlap).

## 4. Acceptance criteria

1. `eval_harness.py --loader-type text|structured|code|mixed` still passes with **0% false hits**
   on the PAWS/QQP/MNLI real negatives.
2. Semantic-tier: near-duplicate queries at similarity ≥ `serve_threshold` are served from cache;
   below threshold they are regenerated (boundary ±0.02).
3. Multi-tenant: overlapping real corpus yields **0 cross-tenant responses**.
4. Invalidation: after update + expiry, stale answers are never returned.
5. `cost-analysis.yml` stays green on the bigger benchmark (savings invariant holds).

## 5. Work items (approved order)

1. `scripts/fetch_test_data.py` — deterministic downloads, checksum-verified, cached, size-capped.
2. Extend `eval_harness.py` inputs + CI matrix (add PAWS/QQP/MNLI gates).
3. Multi-tenant overlap suite (tenant-corpus ingestion + leakage assert).
4. Versioned-document invalidation corpus + test.
5. Bigger realistic benchmark (MS MARCO/LMSYS sample) → regenerate report via existing pipeline.
6. Multilingual gate (PAWS-X).
7. Update `docs/TESTING_DATASETS_PLAN.md` → `DONE`, reflect totals in `docs/COST_ANALYSIS.md`.

## 6. Non-goals for now

- No live-model test harness beyond the existing Gemini run (`run.py --cost` stays optional).
- No data > ~50 MB committed to the repo; large corpora stay behind the fetch script + CI cache.