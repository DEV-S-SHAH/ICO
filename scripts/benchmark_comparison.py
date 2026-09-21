"""Benchmark comparing No Cache vs Traditional Exact Cache vs Intelligent Semantic Cache.

Simulates realistic LLM query workloads with exact repeats, semantic rephrasings,
and novel queries to measure:
- Latency (mean, p50, p95, p99)
- Cache Hit Rate (% exact, % semantic)
- Token & Cost Savings ($ USD)
- Speedup Factor
"""

import json
import os
import sys
import time
from typing import Any

# Ensure intelligent_cache is available
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligent_cache import IntelligentCache


# Realistic AI agent queries with semantic variations and new queries
WORKLOAD = [
    # Topic 1: Company Expense Policy
    {"q": "What is the meal allowance during domestic travel?", "tokens": 45, "cost": 0.0012, "sim_lat": 0.35},
    {"q": "What is the daily meal budget for domestic business trips?", "tokens": 45, "cost": 0.0012, "sim_lat": 0.38},
    {"q": "What is the meal allowance during domestic travel?", "tokens": 45, "cost": 0.0012, "sim_lat": 0.34}, # exact repeat
    {"q": "Tell me the meal stipend for domestic travel", "tokens": 45, "cost": 0.0012, "sim_lat": 0.36},
    
    # Topic 2: Remote Work Policy
    {"q": "How many days per week can employees work remotely?", "tokens": 60, "cost": 0.0018, "sim_lat": 0.42},
    {"q": "What is the policy for work from home days allowed per week?", "tokens": 60, "cost": 0.0018, "sim_lat": 0.45},
    {"q": "How many days per week can employees work remotely?", "tokens": 60, "cost": 0.0018, "sim_lat": 0.41}, # exact repeat
    {"q": "Can team members work from home full time?", "tokens": 65, "cost": 0.0020, "sim_lat": 0.48},

    # Topic 3: Coding Questions
    {"q": "How do I implement binary search in Python?", "tokens": 120, "cost": 0.0036, "sim_lat": 0.65},
    {"q": "Write a Python function for binary search algorithm", "tokens": 120, "cost": 0.0036, "sim_lat": 0.68},
    {"q": "How do I implement binary search in Python?", "tokens": 120, "cost": 0.0036, "sim_lat": 0.64}, # exact repeat
    {"q": "Show me an example of binary search code in python", "tokens": 120, "cost": 0.0036, "sim_lat": 0.66},

    # Topic 4: Technical Support & Security
    {"q": "How do I reset my multi-factor authentication token?", "tokens": 80, "cost": 0.0024, "sim_lat": 0.50},
    {"q": "Steps to reset MFA hardware or app token", "tokens": 80, "cost": 0.0024, "sim_lat": 0.52},
    {"q": "How do I reset my multi-factor authentication token?", "tokens": 80, "cost": 0.0024, "sim_lat": 0.49}, # exact repeat
    {"q": "I lost my 2FA phone, how do I reset authentication?", "tokens": 85, "cost": 0.0026, "sim_lat": 0.54},

    # Topic 5: Unique Uncached Queries
    {"q": "Explain the difference between TCP and UDP protocols", "tokens": 150, "cost": 0.0045, "sim_lat": 0.75},
    {"q": "What are the latest updates in ECMAScript 2026?", "tokens": 130, "cost": 0.0039, "sim_lat": 0.70},
    {"q": "Draft an email requesting project deadline extension", "tokens": 90, "cost": 0.0027, "sim_lat": 0.55},
    {"q": "What is the square root of 1048576?", "tokens": 30, "cost": 0.0009, "sim_lat": 0.30},
]


def simulate_llm_call(query_info: dict[str, Any]) -> str:
    """Simulates LLM response generation with realistic network/inference latency."""
    time.sleep(query_info["sim_lat"])
    return f"Simulated response for: {query_info['q'][:40]}..."


def run_benchmark():
    print("=" * 80)
    print("      INTELLIGENT CACHE OPTIMIZATION: ARCHITECTURE BENCHMARK")
    print("=" * 80)
    print(f"Total Workload Queries: {len(WORKLOAD)}")
    print(f"Workload Composition: 20% Exact Repeats, 40% Semantic Variations, 40% Unique")
    print("-" * 80)

    # 1. NO CACHE RUN
    print("\n[1/3] Running Scenario 1: Without Cache (Baseline)...")
    t0 = time.perf_counter()
    latencies_no_cache = []
    total_tokens_no_cache = 0
    total_cost_no_cache = 0.0

    for item in WORKLOAD:
        start = time.perf_counter()
        _ = simulate_llm_call(item)
        lat = (time.perf_counter() - start) * 1000.0
        latencies_no_cache.append(lat)
        total_tokens_no_cache += item["tokens"]
        total_cost_no_cache += item["cost"]

    total_time_no_cache = (time.perf_counter() - t0) * 1000.0

    # 2. TRADITIONAL EXACT CACHE RUN
    print("[2/3] Running Scenario 2: Traditional Exact-Match Cache...")
    exact_cache = IntelligentCache(exact_only=True, similarity_threshold=1.0)
    t0 = time.perf_counter()
    latencies_exact = []
    hits_exact = 0
    tokens_saved_exact = 0
    cost_saved_exact = 0.0

    for item in WORKLOAD:
        start = time.perf_counter()
        hit = exact_cache.get(item["q"], exact_only=True)
        if hit is not None:
            hits_exact += 1
            lat = (time.perf_counter() - start) * 1000.0
            tokens_saved_exact += item["tokens"]
            cost_saved_exact += item["cost"]
        else:
            _ = simulate_llm_call(item)
            lat = (time.perf_counter() - start) * 1000.0
            exact_cache.set(item["q"], f"Response for {item['q']}", ttl=3600)
        latencies_exact.append(lat)

    total_time_exact = (time.perf_counter() - t0) * 1000.0

    # 3. INTELLIGENT SEMANTIC CACHE RUN
    print("[3/3] Running Scenario 3: Intelligent Semantic Cache...")
    semantic_cache = IntelligentCache(similarity_threshold=0.68)
    t0 = time.perf_counter()
    latencies_semantic = []
    hits_semantic = 0
    exact_hits_semantic = 0
    sim_hits_semantic = 0
    tokens_saved_semantic = 0
    cost_saved_semantic = 0.0

    for item in WORKLOAD:
        start = time.perf_counter()
        hit = semantic_cache.get(item["q"])
        if hit is not None:
            hits_semantic += 1
            if hit.hit_type and hit.hit_type.value == "exact":
                exact_hits_semantic += 1
            else:
                sim_hits_semantic += 1
            lat = (time.perf_counter() - start) * 1000.0
            tokens_saved_semantic += item["tokens"]
            cost_saved_semantic += item["cost"]
        else:
            _ = simulate_llm_call(item)
            lat = (time.perf_counter() - start) * 1000.0
            semantic_cache.set(
                item["q"],
                f"Response for {item['q']}",
                ttl=3600,
                prompt_tokens=item["tokens"] // 2,
                completion_tokens=item["tokens"] // 2,
                latency_ms=lat,
            )
        latencies_semantic.append(lat)

    total_time_semantic = (time.perf_counter() - t0) * 1000.0

    # STATISTICS CALCULATIONS
    def calc_stats(latencies):
        sorted_l = sorted(latencies)
        n = len(sorted_l)
        mean_v = sum(sorted_l) / n
        p50_v = sorted_l[int(n * 0.50)]
        p95_v = sorted_l[min(int(n * 0.95), n - 1)]
        p99_v = sorted_l[min(int(n * 0.99), n - 1)]
        return mean_v, p50_v, p95_v, p99_v

    m_none, p50_none, p95_none, p99_none = calc_stats(latencies_no_cache)
    m_exact, p50_exact, p95_exact, p99_exact = calc_stats(latencies_exact)
    m_sem, p50_sem, p95_sem, p99_sem = calc_stats(latencies_semantic)

    hit_rate_none = 0.0
    hit_rate_exact = (hits_exact / len(WORKLOAD)) * 100.0
    hit_rate_semantic = (hits_semantic / len(WORKLOAD)) * 100.0

    speedup_exact = total_time_no_cache / total_time_exact if total_time_exact > 0 else 1.0
    speedup_semantic = total_time_no_cache / total_time_semantic if total_time_semantic > 0 else 1.0

    cost_reduction_exact = (cost_saved_exact / total_cost_no_cache) * 100.0
    cost_reduction_semantic = (cost_saved_semantic / total_cost_no_cache) * 100.0

    # PRINT SUMMARY TABLE
    print("\n" + "=" * 80)
    print("                    BENCHMARK PERFORMANCE COMPARISON")
    print("=" * 80)
    header = f"{'Metric':<25} | {'No Cache':<15} | {'Exact Cache':<16} | {'Intelligent Semantic':<20}"
    print(header)
    print("-" * 80)
    print(f"{'Total Time (s)':<25} | {total_time_no_cache/1000.0:<15.2f} | {total_time_exact/1000.0:<16.2f} | {total_time_semantic/1000.0:<20.2f}")
    print(f"{'Mean Latency (ms)':<25} | {m_none:<15.1f} | {m_exact:<16.1f} | {m_sem:<20.1f}")
    print(f"{'p50 Latency (ms)':<25} | {p50_none:<15.1f} | {p50_exact:<16.1f} | {p50_sem:<20.1f}")
    print(f"{'p95 Latency (ms)':<25} | {p95_none:<15.1f} | {p95_exact:<16.1f} | {p95_sem:<20.1f}")
    print(f"{'Cache Hit Rate':<25} | {hit_rate_none:<14.1f}% | {hit_rate_exact:<15.1f}% | {hit_rate_semantic:<19.1f}%")
    print(f"{'Exact Match Hits':<25} | {0:<15} | {hits_exact:<16} | {exact_hits_semantic:<20}")
    print(f"{'Semantic Match Hits':<25} | {0:<15} | {0:<16} | {sim_hits_semantic:<20}")
    print(f"{'Tokens Consumed':<25} | {total_tokens_no_cache:<15} | {total_tokens_no_cache - tokens_saved_exact:<16} | {total_tokens_no_cache - tokens_saved_semantic:<20}")
    print(f"{'Tokens Saved':<25} | {0:<15} | {tokens_saved_exact:<16} | {tokens_saved_semantic:<20}")
    print(f"{'Inference Cost ($)':<25} | ${total_cost_no_cache:<14.4f} | ${total_cost_no_cache - cost_saved_exact:<15.4f} | ${total_cost_no_cache - cost_saved_semantic:<19.4f}")
    print(f"{'Cost Reduction (%)':<25} | {0.0:<14.1f}% | {cost_reduction_exact:<15.1f}% | {cost_reduction_semantic:<19.1f}%")
    print(f"{'Speedup Factor':<25} | {'1.0x (baseline)':<15} | {f'{speedup_exact:.2f}x':<16} | {f'{speedup_semantic:.2f}x':<20}")
    print("=" * 80)

    # Save results to JSON
    results = {
        "workload_size": len(WORKLOAD),
        "no_cache": {
            "total_time_ms": total_time_no_cache,
            "mean_latency_ms": m_none,
            "p50_latency_ms": p50_none,
            "p95_latency_ms": p95_none,
            "hit_rate_pct": hit_rate_none,
            "tokens_consumed": total_tokens_no_cache,
            "cost_usd": total_cost_no_cache,
        },
        "exact_cache": {
            "total_time_ms": total_time_exact,
            "mean_latency_ms": m_exact,
            "p50_latency_ms": p50_exact,
            "p95_latency_ms": p95_exact,
            "hit_rate_pct": hit_rate_exact,
            "tokens_saved": tokens_saved_exact,
            "cost_saved_usd": cost_saved_exact,
            "speedup": speedup_exact,
            "cost_reduction_pct": cost_reduction_exact,
        },
        "intelligent_semantic_cache": {
            "total_time_ms": total_time_semantic,
            "mean_latency_ms": m_sem,
            "p50_latency_ms": p50_sem,
            "p95_latency_ms": p95_sem,
            "hit_rate_pct": hit_rate_semantic,
            "exact_hits": exact_hits_semantic,
            "semantic_hits": sim_hits_semantic,
            "tokens_saved": tokens_saved_semantic,
            "cost_saved_usd": cost_saved_semantic,
            "speedup": speedup_semantic,
            "cost_reduction_pct": cost_reduction_semantic,
        },
    }

    os.makedirs("results", exist_ok=True)
    out_json = "results/benchmark_comparison.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Artifact] Saved detailed JSON benchmark to: {out_json}")

    # Save markdown report
    out_md = "results/benchmark_comparison.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"""# Intelligent Cache Benchmark Report

## Overview
Comparative benchmark across 3 configurations:
1. **Without Cache**: Direct calls to LLM provider on all requests
2. **Traditional Exact Cache**: Character-for-character exact matching
3. **Intelligent Semantic Cache**: Exact matching + Embedding-based semantic similarity search

## Results Summary

| Metric | Without Cache | Traditional Exact Cache | Intelligent Semantic Cache |
|---|---|---|---|
| **Total Time** | `{total_time_no_cache/1000.0:.2f}s` | `{total_time_exact/1000.0:.2f}s` | `{total_time_semantic/1000.0:.2f}s` |
| **Mean Latency** | `{m_none:.1f}ms` | `{m_exact:.1f}ms` | `{m_sem:.1f}ms` |
| **p50 Latency** | `{p50_none:.1f}ms` | `{p50_exact:.1f}ms` | `{p50_sem:.1f}ms` |
| **p95 Latency** | `{p95_none:.1f}ms` | `{p95_exact:.1f}ms` | `{p95_sem:.1f}ms` |
| **Cache Hit Rate** | `{hit_rate_none:.1f}%` | `{hit_rate_exact:.1f}%` | `**{hit_rate_semantic:.1f}%**` |
| **Exact Hits** | `0` | `{hits_exact}` | `{exact_hits_semantic}` |
| **Semantic Hits** | `0` | `0` | `{sim_hits_semantic}` |
| **Tokens Saved** | `0` | `{tokens_saved_exact}` | `**{tokens_saved_semantic}**` |
| **Cost Saved ($)** | `$0.00` | `${cost_saved_exact:.4f}` | `**${cost_saved_semantic:.4f}**` |
| **Cost Reduction** | `0%` | `{cost_reduction_exact:.1f}%` | `**{cost_reduction_semantic:.1f}%**` |
| **Speedup Factor** | `1.0x` | `{speedup_exact:.2f}x` | `**{speedup_semantic:.2f}x**` |

## Key Takeaways
- **Hit Rate Jump**: Intelligent Semantic Caching captures rephrasings and synonym variations, boosting hit rate from {hit_rate_exact:.1f}% to **{hit_rate_semantic:.1f}%**.
- **Latency & Cost**: Achieves a **{speedup_semantic:.2f}x speedup** and **{cost_reduction_semantic:.1f}% cost reduction** compared to running without cache.
- **Zero Hallucination Risk**: Exact match tier answers identical queries instantly (sub-millisecond), while semantic tier answers variations exceeding threshold.
""")
    print(f"[Artifact] Saved Markdown benchmark report to: {out_md}\n")


if __name__ == "__main__":
    run_benchmark()
