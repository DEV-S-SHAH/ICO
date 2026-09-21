"""Quickstart: Basic usage of IntelligentCache.

Demonstrates:
1. Exact match caching (Tier 1)
2. Semantic similarity caching (Tier 2)
3. Uncached queries & graceful miss handling
4. Cache metrics & statistics
"""

import time
from intelligent_cache import IntelligentCache

# Initialize intelligent cache with custom similarity threshold
cache = IntelligentCache(
    similarity_threshold=0.75, # 75% cosine similarity required for semantic hit
    default_ttl=3600,          # 1 hour expiration
    namespace="quickstart",
)

# 1. Store an LLM response in cache
prompt = "What is the capital city of France?"
llm_answer = "The capital city of France is Paris."

print("Storing initial response in cache...")
cache.set(prompt, llm_answer)

# 2. Exact Match Lookup (sub-millisecond latency)
t0 = time.perf_counter()
hit_exact = cache.get(prompt)
exact_lat = (time.perf_counter() - t0) * 1000.0
print(f"\n[Exact Match] Found: '{hit_exact.value}'")
print(f"Hit Type: {hit_exact.hit_type} | Latency: {exact_lat:.3f}ms")

# 3. Semantic Similarity Match (paraphrased query)
paraphrase = "What's the capital of France?"
t0 = time.perf_counter()
hit_semantic = cache.get(paraphrase)
sem_lat = (time.perf_counter() - t0) * 1000.0
print(f"\n[Semantic Match] Query: '{paraphrase}'")
print(f"Hit Type: {hit_semantic.hit_type} | Similarity Score: {hit_semantic.similarity_score:.4f} | Latency: {sem_lat:.3f}ms")
print(f"Returned Cached Response: '{hit_semantic.value}'")

# 4. Unrelated query (Cache Miss)
unrelated = "How do airplanes generate lift?"
hit_miss = cache.get(unrelated)
print(f"\n[Cache Miss] Query: '{unrelated}' -> Result: {hit_miss}")

# 5. Display Analytics
stats = cache.stats()
print("\n" + "=" * 50)
print(f"Cache Requests: {stats.total_requests}")
print(f"Exact Hits:     {stats.exact_hits}")
print(f"Semantic Hits:  {stats.semantic_hits}")
print(f"Misses:         {stats.misses}")
print(f"Hit Rate:       {stats.hit_rate * 100:.1f}%")
print("=" * 50)
