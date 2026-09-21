"""Benchmark script to demonstrate LangGraph RAG with vs without intelligent cache."""

import time
import sys
from rag_graph import query_rag, intelligent_cache_instance


def run_benchmark():
    print("=" * 80)
    print("  LANGGRAPH RAG BENCHMARK: WITH vs WITHOUT CACHING")
    print("  Model: Google Gemini (gemini-3.6-flash)")
    print("  Caching Layer: intelligent-cache (Exact + Semantic Multi-Level Cache)")
    print("=" * 80)

    test_queries = [
        # Query 1: Initial query
        {
            "category": "Query 1 (Initial Call)",
            "query": "What is Retrieval-Augmented Generation?",
        },
        # Query 2: Exact repeated query
        {
            "category": "Query 2 (Exact Duplicate)",
            "query": "What is Retrieval-Augmented Generation?",
        },
        # Query 3: Semantically similar query (different phrasing)
        {
            "category": "Query 3 (Semantic Equivalent)",
            "query": "Can you explain what Retrieval-Augmented Generation is?",
        },
        # Query 4: New query on Quantum Computing
        {
            "category": "Query 4 (New Domain Topic)",
            "query": "What is Quantum Computing?",
        },
    ]

    print("\n--- PHASE 1: RUNNING WITHOUT CACHE (Every call hits Google Gemini API) ---")
    without_cache_results = []
    for item in test_queries:
        q = item["query"]
        cat = item["category"]
        print(f"\n[NO-CACHE] Executing: {cat}")
        print(f"  Query: '{q}'")
        res = query_rag(q, use_cache=False)
        print(f"  Latency: {res['latency_ms']:.1f} ms | From Cache: {res['from_cache']}")
        print(f"  Answer Snippet: {res['answer'][:90]}...")
        without_cache_results.append(res["latency_ms"])

    print("\n" + "=" * 80)
    print("--- PHASE 2: RUNNING WITH CACHE (Exact & Semantic Reuse) ---")
    with_cache_results = []
    for item in test_queries:
        q = item["query"]
        cat = item["category"]
        print(f"\n[WITH-CACHE] Executing: {cat}")
        print(f"  Query: '{q}'")
        res = query_rag(q, use_cache=True)
        print(f"  Latency: {res['latency_ms']:.1f} ms | From Cache: {res['from_cache']}")
        print(f"  Answer Snippet: {res['answer'][:90]}...")
        with_cache_results.append(res["latency_ms"])

    print("\n" + "=" * 80)
    print("  COMPARISON SUMMARY & METRICS")
    print("=" * 80)
    print(f"{'Test Case':<32} | {'Without Cache':<15} | {'With Cache':<15} | {'Speedup'}")
    print("-" * 80)
    for i, item in enumerate(test_queries):
        no_c = without_cache_results[i]
        with_c = with_cache_results[i]
        speedup = f"{no_c / max(with_c, 0.001):.1f}x" if with_c < no_c else "1.0x"
        print(f"{item['category']:<32} | {no_c:>11.1f} ms | {with_c:>11.1f} ms | {speedup:>10}")

    print("\nIntelligent Cache Collector Stats:")
    print(intelligent_cache_instance.stats().to_json())


if __name__ == "__main__":
    run_benchmark()
