"""Anthropic Claude Integration Example.

Demonstrates wrapping the official Anthropic client with intelligent caching.
Requires: pip install intelligent-cache[anthropic]
"""

from intelligent_cache import IntelligentCache, wrap_anthropic

# 1. Initialize IntelligentCache
cache = IntelligentCache(
    similarity_threshold=0.82,
    default_ttl=7200,
    namespace="anthropic_production",
)

# 2. Example with Anthropic client
print("Demonstrating Anthropic wrapper pattern:")
print("""
import anthropic
from intelligent_cache import wrap_anthropic, IntelligentCache

cache = IntelligentCache(similarity_threshold=0.82)
client = wrap_anthropic(anthropic.Anthropic(), cache_instance=cache)

# 1. First prompt (hits Claude API, caches response and token usage)
msg1 = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain Rust's ownership and borrowing rules."}],
)
print(msg1.content[0].text)

# 2. Semantically similar query (hits cache, returns in <2ms!)
msg2 = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "How does ownership and borrowing work in Rust?"}],
)
print(msg2.content[0].text)

# 3. View saved stats
stats = cache.stats()
print(f"Total tokens saved: {stats.total_tokens_saved}")
print(f"Total cost saved: ${stats.cost_saved_usd:.5f}")
""")
