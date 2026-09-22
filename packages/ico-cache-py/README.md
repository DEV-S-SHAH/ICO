# ico-cache

[![PyPI](https://img.shields.io/pypi/v/ico-cache.svg)](https://pypi.org/project/ico-cache/)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)](https://pypi.org/project/ico-cache/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Fast, 3-tier semantic cache for LLM applications.**

`ico-cache` saves API token costs and cuts response latency by caching model responses so repeat or rephrased prompts don't hit the LLM again.

---

## 🚀 Quick Install

```bash
pip install ico-cache
```

*Optional extras for universal document parsing (PDF, OCR, Office, ASTs) & distributed tracing:*
```bash
pip install "ico-cache[loaders,observability]"
```

---

## ⚡ 30-Second Quickstart (Zero Setup Needed)

No Docker, Redis, or external databases required. LanceDB, SQLite, and local FastEmbed embeddings run embedded out of the box:

```python
import asyncio
from ico_cache import CacheEngine

async def main():
    # 1. Initialize embedded zero-infra cache
    engine = CacheEngine.embedded()

    # 2. Your prompt
    prompt = "What does the fetch_user(id) function return?"

    # 3. Check cache before calling LLM
    hit = await engine.resolve(prompt)

    if hit["source"] == "MISS":
        # Cache MISS: call your LLM
        answer = {"text": "It returns the user record matching id, or None if not found."}
        print("Generated from LLM:", answer["text"])

        # Save to L1 (exact) and L2 (semantic) cache
        engine.set_l1(prompt, answer)
        await engine.async_write_l2(prompt, answer)
    else:
        print(f"Cache HIT via {hit['source']}:", hit["response"]["text"])

    # 4. Paraphrased query — instantly matches via L2 semantic cache!
    reworded_prompt = "what is the return value of fetch_user with an id?"
    semantic_hit = await engine.resolve(reworded_prompt)
    print(f"Reworded query hit via {semantic_hit['source']} in <20ms:", semantic_hit["response"]["text"])

asyncio.run(main())
```

---

## 💡 How It Works (The 3 Caching Tiers)

| Layer | Technique | How It Works | Speed |
| :--- | :--- | :--- | :--- |
| **L1** | **Exact** | Hashes normalized prompt + metadata fingerprint | `< 1 ms` |
| **L2** | **Semantic** | Cosine vector similarity (matches rephrased queries asking the same thing) | `15–30 ms` |
| **L3** | **Context-Aware** | Dual-vector matching for multi-turn chats & dialog context | `30–50 ms` |

### 🛡️ 0.00% False-Hit Safety
Unlike basic vector caches that confuse queries from different quarters, topics, or tenants, `ico-cache` has a built-in `hard_gate` metadata guard that prevents cross-topic and cross-entity false positives, plus a `serve_threshold` (default `0.90`) semantic gate that only serves a cached answer when the rephrased question is sufficiently similar. Recommended for RAG pipelines:

```python
engine = CacheEngine.embedded(serve_threshold=0.90, bind_context_to_l1=True)
```

---

## 📄 Ingest Documents & Text

Easily load and chunk PDFs, code, text, CSVs, Office files, and scanned images:

```python
from ico_cache import ingest

# Ingest any file by content (automatic extension sniffing + OCR fallback)
chunks = ingest(path="quarterly_report.pdf")
print(f"Extracted {len(chunks)} chunks ready for caching or RAG.")
```

---

## 🌐 Full Production Mode (Redis + Qdrant)

When scaling to distributed microservices:

```python
from ico_cache import CacheEngine
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

engine = CacheEngine(
    embedder=FastEmbedder(),
    vector_store=QdrantStore(host="localhost", port=6333),
    exact_store=RedisStore(host="localhost", port=6379, password="myredissecret"),
    adaptive_threshold=True,
)
```

---

## 🔗 Links & Resources

- **GitHub Repository**: [https://github.com/DEV-S-SHAH/ICO](https://github.com/DEV-S-SHAH/ICO)
- **Architecture & Layer Design**: [Detailed Architecture Guide](https://github.com/DEV-S-SHAH/ICO/blob/main/docs/ARCHITECTURE.md)
- **JavaScript / TypeScript SDK**: [`ico-cache-js` on npm](https://www.npmjs.com/package/ico-cache-js)
- **Issues & Contributions**: [GitHub Issues](https://github.com/DEV-S-SHAH/ICO/issues)