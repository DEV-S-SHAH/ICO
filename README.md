# Intelligent Cache (`intelligent-cache`)

[![Python Versions](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://pypi.org/project/intelligent-cache/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-75%2F75%20passing-brightgreen.svg)]()
[![Type Checked](https://img.shields.io/badge/types-py.typed-blue.svg)]()
[![Code style](https://img.shields.io/badge/code%20style-production--ready-black.svg)]()

**Intelligent Cache** is a production-ready, model-agnostic intelligent cache optimization library designed as a high-performance application layer between **LLMs / AI Agents and underlying tools, APIs, or codebases**.

It intelligently caches and reuses:
* **LLM Responses** (Exact matching + Semantic similarity)
* **Vector Embeddings** (Input text hash caching)
* **Agent Tool & API Calls** (Deterministic parameter matching)
* **Agent Intermediate Reasoning Steps** (Plan generation, decomposition, subtasks)
* **Semantically Equivalent Queries** (Synonyms, rephrasings, and query variations)

Built to be **lightweight and zero-friction**, it works immediately with **zero external services required** (in-memory & SQLite persistent), while supporting enterprise deployments with **Redis** and **PostgreSQL / pgvector**.

---

## Architecture & Request Flow

```mermaid
graph TD
    A[User / AI Agent Query] --> B[Intelligent Cache Application Layer]
    B --> C{Tier 1: Exact Match HIT?}
    C -->|YES - O 1 | D[Return Cached Result (~0.1ms)]
    C -->|NO| E{Tier 2: Semantic Similarity HIT?}
    E -->|YES - Sim >= Threshold| D
    E -->|NO| F{Tier 3: Tool / Intermediate HIT?}
    F -->|YES| D
    F -->|NO| G[Invoke LLM Provider / Agent Tool]
    G --> H[Intelligent Policy Scorer]
    H -->|CACHE_LONG_TTL| I[Store with Adaptive TTL]
    H -->|CACHE_DEFAULT_TTL| I
    H -->|DO_NOT_CACHE| J[Discard Ephemeral / Noisy Data]
    I --> K[Return Fresh Response to Client]
    J --> K
```

---

## Key Highlights

- **Model & Framework Agnostic**: Native drop-in adapters for **OpenAI**, **Anthropic Claude**, **Google Gemini**, **LangChain**, **LlamaIndex**, **Ollama**, and arbitrary Python functions.
- **Multi-Level Caching**:
  - **Tier 1 (Exact Match)**: Sub-millisecond deterministic SHA-256 key lookup.
  - **Tier 2 (Semantic Similarity)**: Dense embedding cosine similarity matching for paraphrased queries.
  - **Tier 3 (Tool & API Cache)**: Mathematical and deterministic function caching with argument hashing.
  - **Tier 4 (Intermediate Steps)**: Agent planning, chain-of-thought, and sub-task caching.
- **Pluggable Storage Backends**:
  - `MemoryBackend`: High-throughput, thread-safe (`RLock`), LRU/LFU/FIFO eviction.
  - `SQLiteBackend`: Zero-setup, single-file disk persistence with WAL mode.
  - `DiskBackend`: Directory-based JSON persistent cache.
  - `RedisBackend`: Distributed caching with native TTL and connection resilience.
  - `PostgresBackend`: Enterprise PostgreSQL backend with pgvector integration.
- **Embedding Flexibility**:
  - `DefaultEmbedder`: High-performance, zero-dependency subword hashing embedder with stemming and stopword down-weighting (runs in ~0.05ms without PyTorch!).
  - `SentenceTransformerEmbedder`: Local HuggingFace / SentenceTransformers models.
  - `OpenAIEmbedder`: OpenAI `text-embedding-3-small` / `ada-002`.
  - `GeminiEmbedder`: Google Gemini embedding models.
  - `CustomEmbedder`: Plug in any callable `(text) -> list[float]`.
- **Intelligent Policy & Scoring**: Explainable multi-factor scoring (frequency, token cost, execution latency, response size, recency) to optimize TTL and prevent cache pollution.
- **Multi-Tenant Namespaces**: Complete tenant, agent, and model isolation.
- **5-Dimensional Invalidation**: Invalidate by key, query, namespace, tag, or semantic radius (`radius=0.85`).
- **Comprehensive Monitoring**: Real-time hit rate, latency saved, tokens saved, USD cost saved, and Prometheus scraper exposition.
- **Graceful Fallback**: Cache backend errors or disconnects will never crash your application; the library logs a warning and transparently falls back to the underlying LLM.

---

## Installation

```bash
# Core lightweight installation (minimal dependencies: numpy, pydantic)
pip install intelligent-cache

# With Redis support
pip install intelligent-cache[redis]

# With PostgreSQL + pgvector support
pip install intelligent-cache[postgres]

# With Sentence Transformers
pip install intelligent-cache[sentence-transformers]

# With LLM provider SDKs
pip install intelligent-cache[openai]
pip install intelligent-cache[anthropic]
pip install intelligent-cache[gemini]
pip install intelligent-cache[langchain]

# Install all features
pip install intelligent-cache[all]
```

---

## 30-Second Quickstart

```python
from intelligent_cache import IntelligentCache

# Initialize cache (defaults to fast in-memory storage)
cache = IntelligentCache(similarity_threshold=0.80, default_ttl=3600)

# Store an answer
prompt = "What is the capital city of France?"
cache.set(prompt, "The capital city of France is Paris.")

# 1. Exact Match Lookup (~0.1ms)
result = cache.get("What is the capital city of France?")
print(result.value)  # "The capital city of France is Paris."
print(result.hit_type)  # CacheHitType.EXACT

# 2. Semantic Similarity Lookup (~0.2ms)
# Detects paraphrasing, typos, and phrasing variations
result2 = cache.get("What's the capital of France?")
print(result2.value)  # "The capital city of France is Paris."
print(result2.similarity_score)  # 0.9582
print(result2.hit_type)  # CacheHitType.SEMANTIC
```

---

## Universal Decorator (`@cache`)

Add intelligent caching to any synchronous or asynchronous Python function with a single decorator:

```python
from intelligent_cache import cache

# Synchronous function
@cache(ttl=1800, similarity_threshold=0.80, namespace="customer_service")
def ask_assistant(question: str) -> str:
    # Expensive LLM or API call
    return call_llm(question)

# Asynchronous function
@cache(ttl=3600, namespace="research_agent")
async def ask_assistant_async(question: str) -> str:
    return await call_llm_async(question)

# Runtime cache bypass
result = ask_assistant("What are your refund terms?", bypass_cache=True)
```

### Deterministic Agent Tools (`@cache_tool`)

```python
from intelligent_cache import cache_tool

@cache_tool(deterministic=True, ttl=86400, namespace="finance_tools")
def calculate_compound_interest(principal: float, rate: float, years: int) -> float:
    return principal * ((1 + rate) ** years)
```

### Embedding Vector Caching (`@cache_embeddings`)

Eliminates redundant embedding API calls and saves API quota:

```python
from intelligent_cache import cache_embeddings

@cache_embeddings(ttl=None, model_name="text-embedding-3-small")
def get_vector(text: str) -> list[float]:
    return openai_client.embeddings.create(input=text, model="text-embedding-3-small").data[0].embedding
```

---

## LLM & Framework Integrations

### 1. OpenAI (Sync & Async)

```python
from openai import OpenAI
from intelligent_cache import wrap_openai, IntelligentCache

cache = IntelligentCache(similarity_threshold=0.80)
client = wrap_openai(OpenAI(), cache_instance=cache)

# Automatically caches chat completions and tracks token/cost savings
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum computing simply."}],
)
```

### 2. Anthropic Claude (Sync & Async)

```python
import anthropic
from intelligent_cache import wrap_anthropic, IntelligentCache

client = wrap_anthropic(anthropic.Anthropic(), cache_instance=IntelligentCache())

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1000,
    messages=[{"role": "user", "content": "How does Raft consensus work?"}],
)
```

### 3. Google Gemini

```python
import google.generativeai as genai
from intelligent_cache import wrap_gemini, IntelligentCache

genai.configure(api_key="GEMINI_API_KEY")
model = wrap_gemini(genai.GenerativeModel("gemini-1.5-pro"), cache_instance=IntelligentCache())

response = model.generate_content("Summarize distributed systems.")
```

### 4. LangChain

```python
from langchain.globals import set_llm_cache
from langchain_openai import ChatOpenAI
from intelligent_cache import IntelligentCache, IntelligentCacheLangChain

# Plug directly into LangChain's global LLM cache
cache = IntelligentCache(similarity_threshold=0.80)
set_llm_cache(IntelligentCacheLangChain(cache))

llm = ChatOpenAI(model="gpt-4o")
# Identical and semantically similar prompts hit IntelligentCache!
response = llm.invoke("What is RAG?")
```

### 5. LlamaIndex

```python
from llama_index.llms.openai import OpenAI
from intelligent_cache import IntelligentCache, IntelligentCacheLlamaIndex

cache = IntelligentCache()
llm = IntelligentCacheLlamaIndex(cache).wrap_llm(OpenAI(model="gpt-4o"))
response = llm.complete("Explain vector indices")
```

### 6. AI Agent Intermediate Step Caching

```python
from intelligent_cache import AgentCache, IntelligentCache

agent_cache = AgentCache(IntelligentCache())

@agent_cache.step(step_name="plan_generation", inputs="Analyze competitor Q3 filings")
def generate_execution_plan():
    # Long multi-step agent reasoning
    return ["1. Gather data", "2. Compare revenue", "3. Synthesize findings"]
```

---

## Pluggable Storage Backends

Switch backends with a single parameter or environment variable:

```python
# In-Memory (LRU / LFU / FIFO)
cache = IntelligentCache(backend="memory", max_entries=50000, eviction_policy="lru")

# SQLite (Persistent local disk, zero external dependencies)
cache = IntelligentCache(backend="sqlite", sqlite_path=".cache/agent_cache.db")

# Filesystem Directory (JSON file storage)
cache = IntelligentCache(backend="disk", disk_dir=".cache/storage")

# Redis (Distributed multi-node)
cache = IntelligentCache(backend="redis", redis_url="redis://localhost:6379/0")

# PostgreSQL with pgvector
cache = IntelligentCache(backend="postgres", database_url="postgresql://user:pass@localhost:5432/cachedb")
```

---

## Cache Invalidation Engine

Intelligent Cache supports **5 distinct invalidation dimensions**:

```python
# 1. Invalidate by exact query
cache.invalidate(query="What is your return policy?")

# 2. Invalidate entire tenant / model namespace
cache.invalidate(namespace="tenant_acme")

# 3. Invalidate by group tag
cache.invalidate(tag="legal_docs_v2")

# 4. Invalidate by Semantic Radius
# Invalidates all cached entries semantically similar to the topic within radius
cache.invalidate(semantic_query="Return and exchange policy", radius=0.80)

# 5. Clear all entries
cache.clear()
```

---

## Analytics, Monitoring & Prometheus

Track resource savings, monetary value, and latency reduction in real time:

```python
stats = cache.stats()

print(f"Total Requests:      {stats.total_requests}")
print(f"Exact Hits:          {stats.exact_hits}")
print(f"Semantic Hits:       {stats.semantic_hits}")
print(f"Overall Hit Rate:    {stats.hit_rate * 100:.1f}%")
print(f"Latency Saved:       {stats.latency_saved_ms:.1f}ms")
print(f"Tokens Saved:        {stats.total_tokens_saved}")
print(f"Est. Cost Saved:     ${stats.cost_saved_usd:.5f}")

# Export Prometheus metrics endpoint
prometheus_metrics = cache.metrics.to_prometheus()
```

Sample Prometheus exposition output:
```text
# HELP intelligent_cache_requests_total Total cache requests
# TYPE intelligent_cache_requests_total counter
intelligent_cache_requests_total 1250
# HELP intelligent_cache_hits_total Total cache hits
# TYPE intelligent_cache_hits_total counter
intelligent_cache_hits_total{type="exact"} 380
intelligent_cache_hits_total{type="semantic"} 490
intelligent_cache_hits_total{type="tool"} 120
# HELP intelligent_cache_hit_rate Overall cache hit rate
# TYPE intelligent_cache_hit_rate gauge
intelligent_cache_hit_rate 0.792
# HELP intelligent_cache_tokens_saved Total LLM tokens saved
# TYPE intelligent_cache_tokens_saved counter
intelligent_cache_tokens_saved 345200
# HELP intelligent_cache_cost_saved_usd Total inference cost saved in USD
# TYPE intelligent_cache_cost_saved_usd counter
intelligent_cache_cost_saved_usd 4.285
```

---

## Empirical Benchmark Results

Evaluated on realistic diverse AI workloads (20% exact repeats, 40% semantic rephrasings, 40% novel queries):

| Metric | Without Cache | Traditional Exact Cache | Intelligent Semantic Cache |
|---|---|---|---|
| **Total Workload Time** | `10.23s` | `8.35s` | **`5.64s`** |
| **Mean Latency** | `511.6ms` | `417.1ms` | **`282.1ms`** |
| **p50 Latency** | `505.0ms` | `485.0ms` | **`354.2ms`** |
| **Cache Hit Rate** | `0.0%` | `20.0%` | **`45.0%`** |
| **Exact Match Hits** | `0` | `4` | `4` |
| **Semantic Match Hits** | `0` | `0` | **`5`** |
| **Tokens Saved** | `0` | `305` | **`735`** |
| **Inference Cost Saved** | `$0.00` | `$0.0090` | **`$0.0218`** |
| **Cost Reduction (%)** | `0.0%` | `18.6%` | **`45.0%`** |
| **Speedup Factor** | `1.0x (baseline)` | `1.23x` | **`1.81x`** |

> **Reproduce benchmark:**
> ```bash
> python scripts/benchmark_comparison.py
> ```

---

## Configuration Reference

All settings can be configured via Python kwargs or environment variables:

| Setting | Environment Variable | Default | Description |
|---|---|---|---|
| `backend` | `INTELLIGENT_CACHE_BACKEND` | `"memory"` | Storage backend (`memory`, `sqlite`, `disk`, `redis`, `postgres`) |
| `similarity_threshold` | `INTELLIGENT_CACHE_SIMILARITY_THRESHOLD` | `0.85` | Cosine similarity threshold for semantic hits (0.0 - 1.0) |
| `default_ttl` | `INTELLIGENT_CACHE_TTL` | `3600` | Default time to live in seconds |
| `namespace` | `INTELLIGENT_CACHE_NAMESPACE` | `"default"` | Default namespace partition |
| `embedder` | `INTELLIGENT_CACHE_EMBEDDER` | `"default"` | Embedder (`default`, `sentence-transformers`, `openai`, `gemini`) |
| `max_entries` | `INTELLIGENT_CACHE_MAX_ENTRIES` | `10000` | Max entries before eviction |
| `eviction_policy` | `INTELLIGENT_CACHE_EVICTION` | `"lru"` | Eviction strategy (`lru`, `lfu`, `fifo`) |
| `sqlite_path` | `INTELLIGENT_CACHE_SQLITE_PATH` | `".cache/intelligent_cache.db"` | Path to SQLite file |
| `redis_url` | `INTELLIGENT_CACHE_REDIS_URL` | `"redis://localhost:6379/0"` | Redis connection URL |
| `database_url` | `INTELLIGENT_CACHE_DATABASE_URL` | `None` | PostgreSQL connection URL |
| `graceful_fallback` | `INTELLIGENT_CACHE_GRACEFUL_FALLBACK` | `True` | Never crash app if backend fails |

---

## Running Tests

The test suite provides 100% verification across core caching, backends, decorators, adapters, and metrics:

```bash
pytest tests/ -v
```

Output:
```text
tests/test_api.py ......                                                 [  8%]
tests/test_core.py .......                                               [ 17%]
tests/test_intelligent_cache_adapters.py .......                         [ 26%]
tests/test_intelligent_cache_backends.py ......                          [ 34%]
tests/test_intelligent_cache_core.py ...........                         [ 49%]
tests/test_intelligent_cache_decorators.py ......                        [ 57%]
tests/test_intelligent_cache_metrics.py ...                              [ 61%]
tests/test_units.py .............................                        [100%]
======================= 75 passed in 1.57s ========================
```

---

## License

MIT License. Developed for high-performance AI agent architectures and production LLM optimization.
