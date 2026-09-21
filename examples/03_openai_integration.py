"""OpenAI Integration Example.

Demonstrates wrapping the official OpenAI client with intelligent caching.
Requires: pip install intelligent-cache[openai]
"""

from intelligent_cache import IntelligentCache, wrap_openai

# 1. Initialize IntelligentCache
cache = IntelligentCache(
    similarity_threshold=0.82,
    default_ttl=3600,
    namespace="openai_production",
)

# 2. Example with OpenAI client
# In production: from openai import OpenAI; client = wrap_openai(OpenAI(), cache_instance=cache)
print("Demonstrating OpenAI wrapper pattern:")
print("""
from openai import OpenAI
from intelligent_cache import wrap_openai, IntelligentCache

# Instantiate cache and wrap standard client
cache = IntelligentCache(similarity_threshold=0.82)
client = wrap_openai(OpenAI(), cache_instance=cache)

# 1. First prompt (hits OpenAI API, caches response and token usage)
resp1 = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is Python's Global Interpreter Lock (GIL)?"}],
)
print(resp1.choices[0].message.content)

# 2. Rephrased prompt (hits semantic cache, saves tokens and ~$0.005 inference cost!)
resp2 = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain the Python GIL"}],
)
print(resp2.choices[0].message.content) # Returns in ~1ms!

# 3. View saved tokens & latency
stats = cache.stats()
print(f"Total tokens saved: {stats.total_tokens_saved}")
print(f"Total inference cost saved: ${stats.cost_saved_usd:.5f}")
""")
