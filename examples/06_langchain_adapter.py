"""LangChain Integration Example.

Demonstrates plugging IntelligentCache into LangChain as a global LLM cache.
Requires: pip install intelligent-cache[langchain]
"""

from intelligent_cache import IntelligentCache, IntelligentCacheLangChain

# 1. Initialize IntelligentCache
cache = IntelligentCache(similarity_threshold=0.85, default_ttl=3600)

print("Demonstrating LangChain integration pattern:")
print("""
from langchain.globals import set_llm_cache
from langchain_openai import ChatOpenAI
from intelligent_cache import IntelligentCache, IntelligentCacheLangChain

# 1. Plug IntelligentCache into LangChain's global LLM cache
cache = IntelligentCache(similarity_threshold=0.85)
set_llm_cache(IntelligentCacheLangChain(cache))

# 2. Invoke any LangChain model or chain
llm = ChatOpenAI(model="gpt-4o")

# First run: invokes OpenAI API
response1 = llm.invoke("What is Retrieval-Augmented Generation?")
print(response1.content)

# Second run with similar prompt: hits intelligent semantic cache!
response2 = llm.invoke("Explain Retrieval-Augmented Generation")
print(response2.content)

# View savings
print(cache.stats().to_json())
""")
