"""LlamaIndex Integration Example.

Demonstrates wrapping LlamaIndex LLMs and query engines with intelligent semantic caching.
"""

from intelligent_cache import IntelligentCache, IntelligentCacheLlamaIndex

cache = IntelligentCache(similarity_threshold=0.85, default_ttl=3600)
adapter = IntelligentCacheLlamaIndex(cache)

print("Demonstrating LlamaIndex integration pattern:")
print("""
from llama_index.llms.openai import OpenAI
from intelligent_cache import IntelligentCache, IntelligentCacheLlamaIndex

# 1. Instantiate cache and wrap LlamaIndex LLM
cache = IntelligentCache(similarity_threshold=0.85)
raw_llm = OpenAI(model="gpt-4o")
llm = IntelligentCacheLlamaIndex(cache).wrap_llm(raw_llm)

# 2. Run completion
res1 = llm.complete("What are vector embeddings?")
print(res1)

# 3. Similar completion hits cache directly
res2 = llm.complete("Explain vector embeddings")
print(res2)
""")
