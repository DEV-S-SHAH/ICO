"""Google Gemini Integration Example.

Demonstrates wrapping Google Generative AI models with intelligent caching.
Requires: pip install intelligent-cache[gemini]
"""

from intelligent_cache import IntelligentCache, wrap_gemini

# 1. Initialize IntelligentCache
cache = IntelligentCache(
    similarity_threshold=0.80,
    default_ttl=3600,
    namespace="gemini_production",
)

print("Demonstrating Google Gemini wrapper pattern:")
print("""
import google.generativeai as genai
from intelligent_cache import wrap_gemini, IntelligentCache

# Configure Gemini
genai.configure(api_key="YOUR_GEMINI_API_KEY")

# Wrap GenerativeModel with caching
cache = IntelligentCache(similarity_threshold=0.80)
raw_model = genai.GenerativeModel("gemini-1.5-pro")
model = wrap_gemini(raw_model, cache_instance=cache)

# 1. Generate content (calls Google Gemini API)
resp1 = model.generate_content("Summarize quantum key distribution in 3 bullet points")
print(resp1.text)

# 2. Similar query (intercepted by intelligent cache!)
resp2 = model.generate_content("Summarize quantum key distribution into 3 bullet points")
print(resp2.text) # Zero latency, zero API quota consumed!

# 3. Check performance metrics
print(cache.stats().to_json())
""")
