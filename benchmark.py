"""Comprehensive 50-Query Evaluation and Cost Analysis for LangGraph RAG."""

import os
import time
import json
import random
from typing import List, Dict, TypedDict, Optional
import google.generativeai as genai
from langgraph.graph import StateGraph, START, END

from intelligent_cache import IntelligentCache
from intelligent_cache.core.entry import CacheHitType
from src.retriever import ComplexRetriever

# 1. API Pricing Configuration
# Gemini 3.1 Flash Lite / 2.5 Flash pricing:
# Input: $0.075 per 1 million tokens ($0.000075 / 1k)
# Output: $0.30 per 1 million tokens ($0.00030 / 1k)
COST_PER_1K_PROMPT = 0.000075
COST_PER_1K_COMPLETION = 0.00030

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", 
    "AQ.Ab8RN6I7YbIFGTAbO1W-legybOb3gaJl81P0mKU5s3M7Rp1ofA"
)
genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel("gemini-3.1-flash-lite")

retriever = ComplexRetriever()


def _estimate_tokens(text: str) -> int:
    """Accurate token estimation (~4 characters per token)."""
    return max(1, len(text) // 4)


class RAGState(TypedDict):
    question: str
    documents: List[Dict[str, str]]
    prompt: str
    answer: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    hit_type: str  # 'NONE', 'EXACT', 'SEMANTIC'


# Define 50 realistic queries with intentional repeats and semantic paraphrases
# To simulate real enterprise / user query traffic
BASE_QUESTIONS = [
    # PDF (Attention Is All You Need) questions
    "What is the Transformer network architecture based on?",
    "How does self-attention work in neural machine translation?",
    "Why does the Transformer dispense with recurrence and convolutions?",
    "What is Multi-Head Attention in the Transformer paper?",
    "What dataset was used for training the original Transformer?",
    
    # TXT (Retrieval-Augmented Generation) questions
    "What is Retrieval-Augmented Generation (RAG)?",
    "How does RAG reduce hallucinations in large language models?",
    "What components are required to build a RAG application?",
    
    # TXT (Deep Learning / ML / Quantum) questions
    "What is the difference between deep learning and machine learning?",
    "How do quantum computers represent information compared to classical computers?",
]

PARAPHRASES = {
    "What is the Transformer network architecture based on?": [
        "Explain the architecture of the Transformer model.",
        "What is the Transformer model based upon according to the paper?",
        "Describe the Transformer architecture.",
        "What foundations does the Transformer architecture rely on?",
    ],
    "How does self-attention work in neural machine translation?": [
        "How is self-attention utilized in machine translation?",
        "Can you describe how self attention functions in translation tasks?",
        "Explain self-attention in neural translation models.",
    ],
    "Why does the Transformer dispense with recurrence and convolutions?": [
        "Why does the Transformer model avoid recurrence and convolutional layers?",
        "Explain why recurrence is removed from the Transformer architecture.",
    ],
    "What is Multi-Head Attention in the Transformer paper?": [
        "Explain Multi-Head Attention from the Attention Is All You Need paper.",
        "How does Multi-Head Attention operate?",
        "What does Multi-Head Attention do in Transformers?",
    ],
    "What is Retrieval-Augmented Generation (RAG)?": [
        "Can you explain what Retrieval-Augmented Generation is?",
        "Define Retrieval Augmented Generation (RAG).",
        "What does RAG mean in the context of LLMs?",
        "Provide an explanation of retrieval augmented generation.",
    ],
    "How does RAG reduce hallucinations in large language models?": [
        "How does retrieval-augmented generation prevent LLM hallucination?",
        "Why does RAG help reduce factual errors in language models?",
    ],
    "What is the difference between deep learning and machine learning?": [
        "Compare deep learning and traditional machine learning.",
        "How does deep learning differ from machine learning?",
        "What separates deep learning from standard machine learning?",
    ],
    "How do quantum computers represent information compared to classical computers?": [
        "How do quantum bits compare to classical bits?",
        "Explain information representation in quantum vs classical computing.",
    ],
}


def generate_50_queries() -> List[Dict[str, str]]:
    """Build a distribution of 50 queries: 20 unique, 15 exact duplicates, 15 semantic variations."""
    queries = []
    
    # 1. Base unique queries (10)
    for q in BASE_QUESTIONS:
        queries.append({"type": "unique_base", "query": q})
        
    # 2. Semantic variants (15)
    for q, variants in PARAPHRASES.items():
        for v in variants[:2]:
            if len(queries) < 25:
                queries.append({"type": "semantic_variant", "query": v, "base": q})

    # 3. Exact duplicates of earlier queries (15)
    for q in BASE_QUESTIONS[:5]:
        queries.append({"type": "exact_duplicate", "query": q})
        queries.append({"type": "exact_duplicate", "query": q})
        queries.append({"type": "exact_duplicate", "query": q})

    # 4. Fill remaining to 50
    remaining = 50 - len(queries)
    extras = [
        "What are large language models used for?",
        "Explain natural language processing applications.",
        "What is supervised machine learning?",
        "How do neural networks learn from data?",
        "What is the role of embeddings in vector databases?",
    ]
    for i in range(remaining):
        queries.append({"type": "supplementary", "query": extras[i % len(extras)]})

    return queries[:50]


def _invoke_gemini_with_retry(prompt: str, max_retries: int = 6) -> str:
    """Call Google Gemini API with exponential backoff on 429 quota throttle."""
    delay = 3.0
    for attempt in range(max_retries):
        try:
            resp = _gemini_model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def run_single_rag(
    question: str,
    cache_layer: Optional[IntelligentCache] = None,
) -> Dict:
    """Execute RAG pipeline with high-precision question-scoped caching."""
    # 1. Retrieve
    docs = retriever.retrieve(question, top_k=2)
    doc_ids = ",".join(sorted([d["doc_id"] for d in docs]))
    context_str = "\n\n".join([f"[{d['source_type'].upper()} - {d['title']}]: {d['content']}" for d in docs])
    
    prompt = (
        "Answer the question concisely using the provided context.\n\n"
        f"Context:\n{context_str}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )

    t0 = time.perf_counter()
    hit_type = "NONE"
    prompt_tokens = _estimate_tokens(prompt)

    # Scoped namespace ensures cache matches questions within the same retrieved context
    namespace = f"rag:{doc_ids}"

    if cache_layer is not None:
        # High precision threshold 0.88 on the QUESTION intent rather than document context
        cache_res = cache_layer.get(question.strip().lower(), namespace=namespace, threshold=0.88)
        if cache_res is not None:
            latency = (time.perf_counter() - t0) * 1000.0
            hit_type = "EXACT" if cache_res.hit_type == CacheHitType.EXACT else "SEMANTIC"
            ans = cache_res.value
            comp_tokens = _estimate_tokens(ans)
            return {
                "question": question,
                "answer": ans,
                "latency_ms": latency,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": comp_tokens,
                "cost_usd": 0.0,  # Cache hit costs $0 in API fees
                "hit_type": hit_type,
            }

    # 2. If no cache or cache miss, invoke Gemini with exponential backoff
    ans = _invoke_gemini_with_retry(prompt)

    latency = (time.perf_counter() - t0) * 1000.0
    comp_tokens = _estimate_tokens(ans)
    cost = (prompt_tokens / 1000.0 * COST_PER_1K_PROMPT) + (comp_tokens / 1000.0 * COST_PER_1K_COMPLETION)

    # 3. Store genuine response in cache using the question key and doc namespace
    if cache_layer is not None:
        cache_layer.set(
            query=question.strip().lower(),
            value=ans,
            namespace=namespace,
            ttl=3600,
            latency_ms=latency,
            prompt_tokens=prompt_tokens,
            completion_tokens=comp_tokens,
            apply_policy=False,  # Store reliably for benchmark
        )

    return {
        "question": question,
        "answer": ans,
        "latency_ms": latency,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": comp_tokens,
        "cost_usd": cost,
        "hit_type": hit_type,
    }


def run_50_queries_benchmark():
    query_set = generate_50_queries()
    print("=" * 85)
    print(f"  50-QUERY COMPREHENSIVE RAG BENCHMARK & COST ANALYSIS")
    print(f"  Dataset: Complex Multi-Format (ArXiv Attention PDF + Wikipedia TXT)")
    print(f"  Model: Google Gemini 3.1 Flash Lite | Cache: intelligent-cache")
    print("=" * 85)

    print(f"\nGenerated workload of {len(query_set)} queries representing real user traffic patterns:")
    types_count = {}
    for q in query_set:
        types_count[q["type"]] = types_count.get(q["type"], 0) + 1
    for k, v in types_count.items():
        print(f"  - {k:<20}: {v} queries")

    # PHASE 1: WITHOUT CACHE
    print("\n" + "-" * 85)
    print(">>> RUNNING 50 QUERIES WITHOUT CACHE (Calling Google Gemini API directly)...")
    print("-" * 85)
    no_cache_results = []
    t_start = time.time()
    for idx, item in enumerate(query_set):
        res = run_single_rag(item["query"], cache_layer=None)
        no_cache_results.append(res)
        print(f"  [No-Cache] #{idx + 1:02d}/50 | Latency: {res['latency_ms']:.1f}ms | Cost: ${res['cost_usd']:.6f} | Query: {item['query'][:45]}...")
        # Pace requests to respect Gemini free-tier quota (15 req/min -> 4.2s delay)
        time.sleep(4.2)
    t_no_cache_total = time.time() - t_start

    # PHASE 2: WITH CACHE
    print("\n" + "-" * 85)
    print(">>> RUNNING 50 QUERIES WITH INTELLIGENT CACHE (Exact + Semantic Reuse)...")
    print("-" * 85)
    cache_inst = IntelligentCache(
        similarity_threshold=0.88,
        default_ttl=3600,
        cost_per_1k_prompt_tokens=COST_PER_1K_PROMPT,
        cost_per_1k_completion_tokens=COST_PER_1K_COMPLETION,
    )
    with_cache_results = []
    t_start = time.time()
    for idx, item in enumerate(query_set):
        res = run_single_rag(item["query"], cache_layer=cache_inst)
        with_cache_results.append(res)
        print(f"  [With-Cache] #{idx + 1:02d}/50 | Hit: {res['hit_type']:<8} | Latency: {res['latency_ms']:.2f}ms | Cost: ${res['cost_usd']:.6f}")
        # Only sleep if it was a cache miss (i.e. called Gemini API)
        if res["hit_type"] == "NONE":
            time.sleep(4.2)
    t_with_cache_total = time.time() - t_start

    # AGGREGATION & METRICS
    no_cache_cost = sum(r["cost_usd"] for r in no_cache_results)
    with_cache_cost = sum(r["cost_usd"] for r in with_cache_results)
    cost_savings = no_cache_cost - with_cache_cost
    pct_cost_saved = (cost_savings / max(no_cache_cost, 1e-9)) * 100.0

    no_cache_tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in no_cache_results)
    with_cache_tokens = sum(
        (r["prompt_tokens"] + r["completion_tokens"]) for r in with_cache_results if r["hit_type"] == "NONE"
    )
    tokens_saved = no_cache_tokens - with_cache_tokens

    exact_hits = sum(1 for r in with_cache_results if r["hit_type"] == "EXACT")
    semantic_hits = sum(1 for r in with_cache_results if r["hit_type"] == "SEMANTIC")
    misses = sum(1 for r in with_cache_results if r["hit_type"] == "NONE")
    total_hits = exact_hits + semantic_hits

    avg_lat_no_cache = sum(r["latency_ms"] for r in no_cache_results) / len(no_cache_results)
    avg_lat_with_cache = sum(r["latency_ms"] for r in with_cache_results) / len(with_cache_results)

    print("\n" + "=" * 85)
    print("  EXECUTIVE SUMMARY: WITH VS WITHOUT CACHE (50 QUERIES)")
    print("=" * 85)
    print(f"{'Metric':<35} | {'Without Cache':<20} | {'With Cache':<20}")
    print("-" * 85)
    print(f"{'Total Wall Clock Time':<35} | {t_no_cache_total:>18.2f} s | {t_with_cache_total:>18.2f} s")
    print(f"{'Average Query Latency':<35} | {avg_lat_no_cache:>16.1f} ms | {avg_lat_with_cache:>16.1f} ms")
    print(f"{'Total Tokens Sent to LLM':<35} | {no_cache_tokens:>20,d} | {with_cache_tokens:>20,d}")
    print(f"{'Tokens Saved via Cache':<35} | {'0 (0%)':>20} | {tokens_saved:>13,d} ({tokens_saved/no_cache_tokens*100:.1f}%)")
    print(f"{'Total LLM API Cost (USD)':<35} | ${no_cache_cost:>18.5f} | ${with_cache_cost:>18.5f}")
    print(f"{'Cost Savings ($ and %)':<35} | {'$0.00000 (0%)':>20} | ${cost_savings:>10.5f} ({pct_cost_saved:.1f}%)")
    print(f"{'Cache Hits Breakdown':<35} | {'N/A':>20} | {f'{total_hits}/50 ({total_hits/50*100:.0f}%)':>20}")
    print(f"  - Exact Hash Hits: {exact_hits}")
    print(f"  - Semantic Similarity Hits: {semantic_hits}")
    print(f"  - Cold Misses (New Topics): {misses}")

    # SAMPLE RESPONSES CHECK & DIFF ANALYSIS
    from src.diff import compare_responses, format_side_by_side_diff

    print("\n" + "=" * 85)
    print("  RESPONSE DIFFERENCE & QUALITY ANALYSIS (With vs Without Cache)")
    print("=" * 85)
    
    samples_idx = [0, 4, 11, 20, 39]
    for s_i in samples_idx:
        q_item = query_set[s_i]
        r_no = no_cache_results[s_i]
        r_with = with_cache_results[s_i]
        diff_info = compare_responses(
            query=q_item["query"],
            response_no_cache=r_no["answer"],
            response_with_cache=r_with["answer"],
            hit_type=r_with["hit_type"],
        )
        print(f"\n[Query #{s_i + 1}] Category: {q_item['type']}")
        print(f"  Question:            {q_item['query']}")
        print(f"  Cache Behavior:      {diff_info['diff_nature']}")
        print(f"  Sequence Similarity: {diff_info['sequence_similarity'] * 100:.1f}%")
        print(f"  Word Overlap:        {diff_info['jaccard_similarity'] * 100:.1f}%")
        print(f"  Length Comparison:   Without Cache: {diff_info['words_no_cache']} words | With Cache: {diff_info['words_with_cache']} words")
        print("  Side-by-Side Response Snippet:")
        print(format_side_by_side_diff(r_no["answer"], r_with["answer"], max_width=40))

    # SAVE ALL 50 RESPONSES TO JSON AND CSV
    import csv
    output_dir = "benchmark_results"
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "responses_50_queries.json")
    csv_path = os.path.join(output_dir, "responses_50_queries.csv")

    records = []
    for idx, (q_item, r_no, r_with) in enumerate(zip(query_set, no_cache_results, with_cache_results)):
        diff_info = compare_responses(
            query=q_item["query"],
            response_no_cache=r_no["answer"],
            response_with_cache=r_with["answer"],
            hit_type=r_with["hit_type"],
        )
        rec = {
            "query_id": idx + 1,
            "category": q_item["type"],
            "query": q_item["query"].strip(),
            "response_without_cache": " ".join(r_no["answer"].split()),
            "latency_no_cache_ms": f"{r_no['latency_ms']:.1f}",
            "cost_no_cache_usd": f"{r_no['cost_usd']:.6f}",
            "response_with_cache": " ".join(r_with["answer"].split()),
            "hit_type": r_with["hit_type"],
            "latency_with_cache_ms": f"{r_with['latency_ms']:.2f}",
            "cost_with_cache_usd": f"{r_with['cost_usd']:.6f}",
            "speedup_ratio": f"{round(r_no['latency_ms'] / max(r_with['latency_ms'], 0.001), 1):.1f}x",
            "is_exact_match": diff_info["is_exact_match"],
            "sequence_similarity": f"{diff_info['sequence_similarity'] * 100:.1f}%",
            "word_overlap_jaccard": f"{diff_info['jaccard_similarity'] * 100:.1f}%",
        }
        records.append(rec)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        import csv
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(records)

    print("\n" + "=" * 85)
    print(f"  [SAVED] All 50 query responses successfully saved to:")
    print(f"    - JSON: {json_path}")
    print(f"    - CSV:  {csv_path}")
    print("=" * 85)


if __name__ == "__main__":
    run_50_queries_benchmark()

