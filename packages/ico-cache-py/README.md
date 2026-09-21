# ico-cache

Semantic caching middleware for **LLM applications**. `ico-cache` sits between any
coding agent, RAG pipeline, or LLM-based system and the model itself, caching model
responses so repeated or reformulated prompts are never re-run through the LLM.

It uses three complementary caching techniques:

| Layer | Technique | Purpose |
| --- | --- | --- |
| **L1** | Exact | Instant hits for identical repeat queries (Redis / SQLite). |
| **L2** | Semantic | Matches paraphrased and reworded queries (Qdrant / LanceDB). |
| **L3** | Context-aware | Resolves multi-turn, context-dependent queries with dual vectors. |

Key benefits, in order: **lower API token cost** (fewer calls to the LLM), **lower
latency** (a cache hit returns in milliseconds instead of seconds), and minimal
cache read/write overhead itself. A hard metadata gate (+ a 0% false-hit baseline)
prevents near-miss cross-entity / cross-topic false positives.

A reference implementation that showcases ico-cache end-to-end (against SEC filings,
FastAPI + Streamlit) lives in `apps/financial-rag-demo` of the [repository] — it is
a demo, not the product.

## Install

Requires Python 3.11+.

```bash
pip install ico-cache
pip install "ico-cache[loaders,observability]"   # document loaders + tracing
```

## Quickstart (Zero-Infra Embedded Mode)

No external services — LanceDB (vectors), SQLite (exact), FastEmbed (local ONNX embeddings).

```python
import asyncio
from ico_cache import CacheEngine
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

async def main():
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri="./lancedb"),
        exact_store=SQLiteStore(db_path="cache.db"),
        metadata_filter_keys=["project", "topic"],
        adaptive_threshold=True,
    )

    query = "What does the fetch_user(id) function return?"
    result = await engine.resolve(query)
    if result["source"] == "MISS":
        answer = {"text": "It returns the user record matching id, or None when not found."}
        engine.set_l1(query, answer)
        await engine.async_write_l2(query, answer)
    else:
        print(f"Cache HIT via {result['source']}: {result['response']}")

asyncio.run(main())
```

See the [main repository README](https://github.com/DEV-S-SHAH/ICO) for universal
document ingestion, distributed server mode, Kubernetes deployment, testing, and
benchmarking. The JavaScript SDK is published as `ico-cache-js`.

[repository]: https://github.com/DEV-S-SHAH/ICO