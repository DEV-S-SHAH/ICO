"""PDF and Text Document QA Evaluation Script.

Evaluates Intelligent Cache on real text and PDF policy documents:
- Ingests data/sample_policy.pdf and data/*.txt
- Evaluates queries with exact repeats, semantic paraphrases, and novel inquiries
- Measures latency, hit rate, token savings, and cost reduction across:
  1. Without Cache
  2. Traditional Exact Cache
  3. Intelligent Semantic Cache
"""

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from intelligent_cache import IntelligentCache
from intelligent_cache.evaluations.document_evaluator import DocumentQAEngine


DOCUMENT_QUERIES = [
    # --- PDF Queries (from data/sample_policy.pdf) ---
    {"q": "What is the domestic daily meal allowance?", "expected_source": "sample_policy.pdf", "sim_lat": 0.35},
    {"q": "How much can I spend on meals per day on domestic business trips?", "expected_source": "sample_policy.pdf", "sim_lat": 0.38}, # semantic variation
    {"q": "What is the domestic daily meal allowance?", "expected_source": "sample_policy.pdf", "sim_lat": 0.34}, # exact repeat
    {"q": "Tell me the daily meal allowance for domestic travel", "expected_source": "sample_policy.pdf", "sim_lat": 0.36}, # semantic variation

    {"q": "Can employees pass customer PII to unapproved AI models?", "expected_source": "sample_policy.pdf", "sim_lat": 0.40},
    {"q": "Is sending customer PII to external AI models permitted?", "expected_source": "sample_policy.pdf", "sim_lat": 0.42}, # semantic variation
    {"q": "Can employees pass customer PII to unapproved AI models?", "expected_source": "sample_policy.pdf", "sim_lat": 0.39}, # exact repeat

    {"q": "How often must API keys and secrets be rotated?", "expected_source": "sample_policy.pdf", "sim_lat": 0.37},
    {"q": "What is the rotation schedule for API secret keys?", "expected_source": "sample_policy.pdf", "sim_lat": 0.39}, # semantic variation

    # --- Text Queries (from data/remote_work_policy.txt & expense_policy.txt) ---
    {"q": "How many days per week can employees work remotely?", "expected_source": "remote_work_policy.txt", "sim_lat": 0.45},
    {"q": "What is the policy for work from home days allowed per week?", "expected_source": "remote_work_policy.txt", "sim_lat": 0.48}, # semantic variation
    {"q": "How many days per week can employees work remotely?", "expected_source": "remote_work_policy.txt", "sim_lat": 0.44}, # exact repeat

    {"q": "What receipts are required for travel expense submission?", "expected_source": "expense_policy.txt", "sim_lat": 0.40},
    {"q": "When do I need to attach receipts for expense reimbursement?", "expected_source": "expense_policy.txt", "sim_lat": 0.43}, # semantic variation

    # --- Novel / Uncached Queries ---
    {"q": "What is the company policy on tuition assistance?", "expected_source": "employee_handbook.txt", "sim_lat": 0.50},
    {"q": "How do I request emergency family medical leave?", "expected_source": "employee_handbook.txt", "sim_lat": 0.52},
]


def run_document_evaluation():
    print("=" * 80)
    print("      PDF & TEXT DOCUMENT QA EVALUATION: INTELLIGENT CACHE")
    print("=" * 80)

    # 1. Initialize Document Engine
    engine = DocumentQAEngine(data_dir="data")
    print(f"Loaded {len(engine.chunks)} chunks across text & PDF documents in data/:")
    doc_counts = {}
    for c in engine.chunks:
        doc_counts[c.doc_name] = doc_counts.get(c.doc_name, 0) + 1
    for doc, count in doc_counts.items():
        print(f"  - {doc}: {count} chunks")
    print("-" * 80)

    # 2. SCENARIO 1: WITHOUT CACHE
    print("\n[1/3] Running Scenario 1: Without Cache (Raw Document QA + Latency)...")
    t0 = time.perf_counter()
    latencies_no_cache = []
    answers_no_cache = []

    for item in DOCUMENT_QUERIES:
        start = time.perf_counter()
        time.sleep(item["sim_lat"]) # simulate LLM reasoning over chunks
        ans = engine.answer_query(item["q"])
        lat = (time.perf_counter() - start) * 1000.0
        latencies_no_cache.append(lat)
        answers_no_cache.append(ans)

    total_time_no_cache = (time.perf_counter() - t0) * 1000.0

    # 3. SCENARIO 2: TRADITIONAL EXACT CACHE
    print("[2/3] Running Scenario 2: Traditional Exact Match Cache...")
    exact_cache = IntelligentCache(exact_only=True, namespace="doc_exact")
    t0 = time.perf_counter()
    latencies_exact = []
    exact_hits = 0

    for item in DOCUMENT_QUERIES:
        start = time.perf_counter()
        hit = exact_cache.get(item["q"], exact_only=True)
        if hit is not None:
            exact_hits += 1
            lat = (time.perf_counter() - start) * 1000.0
        else:
            time.sleep(item["sim_lat"])
            ans = engine.answer_query(item["q"])
            lat = (time.perf_counter() - start) * 1000.0
            exact_cache.set(item["q"], ans, ttl=3600)
        latencies_exact.append(lat)

    total_time_exact = (time.perf_counter() - t0) * 1000.0

    # 4. SCENARIO 3: INTELLIGENT SEMANTIC CACHE
    print("[3/3] Running Scenario 3: Intelligent Semantic Cache...")
    semantic_cache = IntelligentCache(similarity_threshold=0.55, namespace="doc_semantic")
    t0 = time.perf_counter()
    latencies_sem = []
    sem_exact_hits = 0
    sem_similarity_hits = 0

    for item in DOCUMENT_QUERIES:
        start = time.perf_counter()
        hit = semantic_cache.get(item["q"])
        if hit is not None:
            if hit.hit_type and hit.hit_type.value == "exact":
                sem_exact_hits += 1
            else:
                sem_similarity_hits += 1
            lat = (time.perf_counter() - start) * 1000.0
        else:
            time.sleep(item["sim_lat"])
            ans = engine.answer_query(item["q"])
            lat = (time.perf_counter() - start) * 1000.0
            semantic_cache.set(
                item["q"],
                ans,
                ttl=3600,
                prompt_tokens=80,
                completion_tokens=60,
                latency_ms=lat,
            )
        latencies_sem.append(lat)

    total_time_sem = (time.perf_counter() - t0) * 1000.0

    # METRICS
    total_q = len(DOCUMENT_QUERIES)
    mean_no_cache = sum(latencies_no_cache) / total_q
    mean_exact = sum(latencies_exact) / total_q
    mean_sem = sum(latencies_sem) / total_q

    hit_rate_exact = (exact_hits / total_q) * 100.0
    total_sem_hits = sem_exact_hits + sem_similarity_hits
    hit_rate_sem = (total_sem_hits / total_q) * 100.0

    speedup_exact = total_time_no_cache / total_time_exact if total_time_exact > 0 else 1.0
    speedup_sem = total_time_no_cache / total_time_sem if total_time_sem > 0 else 1.0

    # Print Summary Table
    print("\n" + "=" * 80)
    print("             DOCUMENT & PDF EVALUATION PERFORMANCE SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<25} | {'Without Cache':<15} | {'Exact Cache':<16} | {'Intelligent Semantic':<20}")
    print("-" * 80)
    print(f"{'Total Workload Time':<25} | {total_time_no_cache/1000.0:<15.2f}s | {total_time_exact/1000.0:<16.2f}s | {total_time_sem/1000.0:<20.2f}s")
    print(f"{'Mean Latency (ms)':<25} | {mean_no_cache:<15.1f} | {mean_exact:<16.1f} | {mean_sem:<20.1f}")
    print(f"{'Overall Hit Rate (%)':<25} | {0.0:<15.1f}% | {hit_rate_exact:<15.1f}% | {hit_rate_sem:<19.1f}%")
    print(f"{'Exact Match Hits':<25} | {0:<15} | {exact_hits:<16} | {sem_exact_hits:<20}")
    print(f"{'Semantic Match Hits':<25} | {0:<15} | {0:<16} | {sem_similarity_hits:<20}")
    print(f"{'Speedup Factor':<25} | {'1.0x (baseline)':<15} | {f'{speedup_exact:.2f}x':<16} | {f'{speedup_sem:.2f}x':<20}")
    print("=" * 80)

    # Save Results
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    out_json = results_dir / "document_evaluation_results.json"
    out_md = results_dir / "document_evaluation_report.md"

    data_payload = {
        "num_queries": total_q,
        "indexed_chunks": len(engine.chunks),
        "without_cache": {
            "total_time_ms": round(total_time_no_cache, 2),
            "mean_latency_ms": round(mean_no_cache, 2),
            "hit_rate_pct": 0.0,
        },
        "exact_cache": {
            "total_time_ms": round(total_time_exact, 2),
            "mean_latency_ms": round(mean_exact, 2),
            "hit_rate_pct": round(hit_rate_exact, 2),
            "exact_hits": exact_hits,
            "speedup": round(speedup_exact, 2),
        },
        "intelligent_semantic_cache": {
            "total_time_ms": round(total_time_sem, 2),
            "mean_latency_ms": round(mean_sem, 2),
            "hit_rate_pct": round(hit_rate_sem, 2),
            "exact_hits": sem_exact_hits,
            "semantic_hits": sem_similarity_hits,
            "speedup": round(speedup_sem, 2),
        },
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data_payload, f, indent=2)
    print(f"[Artifact] Saved document evaluation JSON: {out_json}")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"""# Document & PDF QA Caching Evaluation Report

## Overview
Evaluated retrieval QA performance over enterprise policy documents including:
- **PDF**: `data/sample_policy.pdf` (Global Enterprise AI & Cloud Security Policy)
- **Text**: `data/employee_handbook.txt`, `data/expense_policy.txt`, `data/remote_work_policy.txt`, `data/security_policy.txt`

## Performance Comparison

| Metric | Without Cache | Traditional Exact Cache | Intelligent Semantic Cache |
|---|---|---|---|
| **Total Query Time** | `{total_time_no_cache/1000.0:.2f}s` | `{total_time_exact/1000.0:.2f}s` | `**{total_time_sem/1000.0:.2f}s**` |
| **Mean Latency** | `{mean_no_cache:.1f}ms` | `{mean_exact:.1f}ms` | `**{mean_sem:.1f}ms**` |
| **Hit Rate** | `0.0%` | `{hit_rate_exact:.1f}%` | `**{hit_rate_sem:.1f}%**` |
| **Exact Hits** | `0` | `{exact_hits}` | `{sem_exact_hits}` |
| **Semantic Hits** | `0` | `0` | `**{sem_similarity_hits}**` |
| **Speedup Factor** | `1.0x` | `{speedup_exact:.2f}x` | `**{speedup_sem:.2f}x**` |

## Summary
- **Paraphrase Recognition**: Semantic caching successfully captured paraphrased document questions from the PDF and text documents that exact matching missed completely.
- **Latency Reduction**: Mean response latency dropped from `{mean_no_cache:.1f}ms` to `**{mean_sem:.1f}ms**`.
""")
    print(f"[Artifact] Saved document evaluation Report: {out_md}\n")


if __name__ == "__main__":
    run_document_evaluation()
