"""AI Agent Tools and Intermediate Steps Caching Example.

Demonstrates:
- Caching agent tool calls (deterministic calculations, API requests)
- Caching intermediate reasoning steps (planner steps, subtasks)
"""

import time
from intelligent_cache import AgentCache, IntelligentCache, cache_tool

cache = IntelligentCache()
agent_cache = AgentCache(cache)

# 1. Deterministic Tool Caching
@cache_tool(deterministic=True, ttl=86400, namespace="agent_tools")
def search_product_catalog(sku: str) -> dict:
    print(f"  [DB Query] Fetching catalog info for SKU: {sku}...")
    time.sleep(0.2) # simulate DB query
    return {"sku": sku, "name": "Enterprise Cloud Server", "price": 4999.00}

print("--- Testing Agent Tool Caching ---")
print("First query:", search_product_catalog("SKU-9901"))
print("Second query (Cached):", search_product_catalog("SKU-9901"))


# 2. Intermediate Reasoning Step Caching
@agent_cache.step(step_name="decompose_goal", inputs="Analyze quarterly financial report")
def decompose_goal() -> list[str]:
    print("  [Agent LLM] Decomposing complex goal into sub-steps...")
    time.sleep(0.4)
    return [
        "1. Extract revenue and profit margins",
        "2. Compare against previous quarter",
        "3. Highlight notable variances",
        "4. Synthesize executive summary",
    ]

print("\n--- Testing Intermediate Reasoning Step Caching ---")
print("First reasoning call:", decompose_goal())
print("Second reasoning call (Instant Hit):", decompose_goal())
