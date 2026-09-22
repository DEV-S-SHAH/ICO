# Cost Analysis — 50-Query LangGraph RAG Benchmark

Generated from `benchmark_results/responses_50_queries.json` by `scripts/cost_analysis.py`.

## Run Profile

| Metric | Without Cache | With Cache |
| :--- | ---: | ---: |
| Queries | 50 | 50 |
| Total cost | $0.006707 | $0.003910 |
| Total saved | — | **$0.002797 (41.7%)** |
| Mean cost / query | $0.000134 | $0.000078 |
| Mean latency | 4217 ms | 2253 ms |
| p95 latency | 9946 ms | — |

## Hit Mix

- **EXACT hits: 20** (40%) — zero inference cost on repeats.
- **Semantic hits: 0** (0%) — none fired in this run (0.88 threshold + keyword retriever).
- **Misses (paid LLM): 30** (60%) — the entire remaining cost.

## The Interesting Part

Savings today are **capped at the repeat rate** (40%). Paraphrased
traffic still pays full LLM price because the semantic tier never served in this run.
That invisible spend is exactly what serve-gate / paraphrase-threshold tuning recovers:
on the v1.0.5 multi-corpus matrix (`serve_threshold=0.90`) the cache eliminated
**74–100% of LLM calls** at zero answer regressions — so cost reduction scales with
semantic recall, not just repeats.

## Extrapolation (Gemini flash-lite pricing, as incurred)

| Volume | Without Cache | With Cache | Saved |
| :--- | ---: | ---: | ---: |
| 1k queries/mo | $0.134140 | $0.078200 | $0.055940 |
| 100k queries/mo | $13.41 | $7.82 | $5.59 |

With semantic hits enabled those savings roughly double because ~60% of this workload
is paraphrase traffic currently paying full price.
