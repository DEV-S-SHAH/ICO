"""Decorator usage: Sync, Async, Tools, and Embeddings.

Demonstrates:
- @cache on standard sync functions
- @cache on async functions
- @cache_tool for deterministic agent tools
- @cache_embeddings for vector generation
"""

import asyncio
import time
from intelligent_cache import cache, cache_tool, cache_embeddings

# 1. Sync LLM Function Caching
@cache(ttl=1800, similarity_threshold=0.75, namespace="sync_llm")
def call_llm(prompt: str) -> str:
    print(f"  [LLM Provider Invoked] Generating answer for: '{prompt}'...")
    time.sleep(0.3) # simulate network call
    return f"Intelligent answer for: {prompt}"

print("--- Testing Sync @cache ---")
print("Call 1:", call_llm("What is Kubernetes?"))
print("Call 2 (Exact Hit):", call_llm("What is Kubernetes?"))
print("Call 3 (Semantic Hit):", call_llm("What is kubernetes?"))


# 2. Async LLM Function Caching
@cache(ttl=3600, similarity_threshold=0.75, namespace="async_llm")
async def call_llm_async(prompt: str) -> str:
    print(f"  [Async LLM Invoked] Generating async response...")
    await asyncio.sleep(0.3)
    return f"Async response to: {prompt}"

async def main():
    print("\n--- Testing Async @cache ---")
    print("Async 1:", await call_llm_async("Explain quantum computing"))
    print("Async 2 (Exact Hit):", await call_llm_async("Explain quantum computing"))
    print("Async 3 (Semantic Hit):", await call_llm_async("Can you explain quantum computing?"))

asyncio.run(main())


# 3. Agent Tool Caching (Deterministic mathematical calculation / DB query)
@cache_tool(deterministic=True, ttl=86400, namespace="agent_tools")
def calculate_vat(amount: float, rate: float = 0.20) -> float:
    print(f"  [Tool Executing] Computing VAT on {amount} at rate {rate}...")
    return round(amount * rate, 2)

print("\n--- Testing @cache_tool ---")
print("VAT 1:", calculate_vat(150.0, rate=0.20))
print("VAT 2 (Tool Hit):", calculate_vat(150.0, rate=0.20))


# 4. Embeddings Caching
@cache_embeddings(ttl=None, model_name="text-embedding-3-small")
def get_embedding(text: str) -> list[float]:
    print(f"  [Embedding API Invoked] Computing vector for text...")
    return [0.123, 0.456, 0.789]

print("\n--- Testing @cache_embeddings ---")
v1 = get_embedding("Hello world")
v2 = get_embedding("Hello world")
print(f"Embedding cached: {v1 == v2}")
