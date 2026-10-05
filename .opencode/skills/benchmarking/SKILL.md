---
name: benchmarking
description: Measure optimization against a baseline. Runs benchmark harness, compares before/after, produces JSON reports, detects regressions. Use for every major optimization, release gates, and regression detection.
---

# Benchmarking Skill

## Purpose

Reliably measure and compare system performance across versions, configurations, and optimizations.

## When to Use

- Every major optimization (cache, RAG, token, memory)
- Release gates (CI must pass benchmarks)
- Regression detection (performance drift)
- Architecture decision validation
- Capacity planning

## When NOT to Use

- Micro-optimizations without user-visible impact
- Feature development (use during validation only)
- Ad-hoc profiling (use observability tools instead)

## Workflow

### 1. Define Baseline Configuration

```python
# Baseline = current main branch, standard config
baseline_config = {
    "cache_engine": "embedded",      # or "distributed"
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "chunking": "default",
    "reranker": None,
    "llm_model": "gemini/gemini-flash-latest",
    "thresh_semantic": 0.85,
    "thresh_ctx_q": 0.75,
    "thresh_ctx_c": 0.85,
}
```

### 2. Prepare Query Workload

```python
# 5 standard datasets (from benchmark.py)
datasets = {
    "financial": "SEC filings Q&A (500 queries)",
    "code": "Repository analysis (300 queries)",
    "legal": "Contract analysis (200 queries)",
    "medical": "Clinical Q&A (150 queries)",
    "general": "Conversational QA (400 queries)",
}

# Each dataset: deterministic fixtures from fixtures_gen.py
# No external downloads, fully reproducible
```

### 3. Run Benchmark

```bash
# Full benchmark suite
python benchmark.py --dataset all --output benchmark-reports/run_$(date +%s).json

# Single dataset (faster iteration)
python benchmark.py --dataset financial --output benchmark-reports/financial_$(date +%s).json

# With custom config
python benchmark.py --dataset all --config benchmark_config.yaml
```

### 4. Compare Results

```python
def compare_benchmarks(baseline_path, candidate_path):
    base = json.load(open(baseline_path))
    cand = json.load(open(candidate_path))
    
    results = {}
    for dataset in base["datasets"]:
        b = base["datasets"][dataset]
        c = cand["datasets"][dataset]
        
        results[dataset] = {
            "tokens_saved_pct": (b["tokens"] - c["tokens"]) / b["tokens"] * 100,
            "cost_saved_pct": (b["cost"] - c["cost"]) / b["cost"] * 100,
            "latency_reduction_pct": (b["latency"] - c["latency"]) / b["latency"] * 100,
            "hit_rate_l1_delta": c["hit_rate_l1"] - b["hit_rate_l1"],
            "hit_rate_l2_delta": c["hit_rate_l2"] - b["hit_rate_l2"],
            "hit_rate_l3_delta": c["hit_rate_l3"] - b["hit_rate_l3"],
            "llm_calls_avoided_delta": c["llm_calls_avoided"] - b["llm_calls_avoided"],
            "quality_delta": c["quality_score"] - b["quality_score"],
        }
    return results
```

### 5. Regression Gate

```yaml
# In CI: fail if any metric regresses beyond threshold
regression_thresholds:
  tokens_saved_pct: -5%      # No more than 5% token increase
  cost_saved_pct: -5%
  latency_reduction_pct: -10%
  hit_rate_l1_delta: -0.02   # No more than 2pp hit rate drop
  hit_rate_l2_delta: -0.02
  hit_rate_l3_delta: -0.02
  quality_delta: -0.01       # Quality score drop < 1pp
```

## Inputs

- Baseline benchmark report (JSON)
- Candidate benchmark report (JSON)
- Regression thresholds (configurable)
- Query datasets (standard 5 + custom)

## Outputs

- Comparison report (JSON + human-readable summary)
- Pass/fail per metric per dataset
- Overall regression verdict
- Trend data (if historical reports available)

## Validation

- **Reproducibility** — Same config + same seed = same results (±2%)
- **Statistical significance** — Minimum 100 queries per dataset
- **Hardware consistency** — Same runner class for comparison
- **Environment isolation** — No other workloads during benchmark

## Failure Conditions

- Non-reproducible results (variance > 5%)
- Regression on any critical metric beyond threshold
- Quality degradation (hallucination, incomplete answers)
- Benchmark infrastructure failure (OOM, timeout, backend down)
- Insufficient sample size for statistical confidence

## Report Format (benchmark.py output)

```json
{
  "timestamp": "2026-01-15T10:30:00Z",
  "git_sha": "abc123...",
  "config": { ... },
  "datasets": {
    "financial": {
      "queries": 500,
      "tokens_total": 2_340_000,
      "tokens_saved": 1_890_000,
      "cost_usd": 12.45,
      "cost_saved_usd": 9.87,
      "latency_avg_ms": 145,
      "latency_p50_ms": 89,
      "latency_p95_ms": 420,
      "hit_rate_l1": 0.35,
      "hit_rate_l2": 0.42,
      "hit_rate_l3": 0.15,
      "miss_rate": 0.08,
      "llm_calls_total": 460,
      "llm_calls_avoided": 1890,
      "embeddings_computed": 500,
      "embeddings_avoided": 1890,
      "quality_score": 0.92
    },
    ...
  },
  "aggregate": {
    "total_queries": 1550,
    "tokens_saved_pct": 81,
    "cost_saved_pct": 79,
    "latency_reduction_pct": 78,
    "overall_hit_rate": 0.92,
    "overall_quality": 0.91
  }
}
```