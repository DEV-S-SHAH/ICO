# ICO-Cache: Generalized LLM Semantic Cache

ICO-Cache is a high-performance, multi-layered semantic caching engine for Large Language Models. It minimizes redundant LLM calls by precisely matching queries contextually and semantically, while strictly guarding against false hits through centralized entity, topic, and quarter metadata filtering.

## Quickstart (Zero-Infra Embedded Mode)

```python
from ico_cache import ICOCache, ICOConfig
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

# Initialize with embedded databases
engine = ICOCache(
    embedder=FastEmbedder(),
    vector_store=LanceDBStore(uri="./lancedb"),
    exact_store=SQLiteStore(db_path="cache.db")
)

# Resolve query
result = await engine.resolve("What is Apple's revenue?", meta={"entity": "AAPL", "topic": "revenue"})
if result["source"] == "MISS":
    # Generate and ingest...
```

## Performance & Reliability (Actual Measured Benchmarks)

Results from the `verify_all_5` suite run:

| Metric | Result | Detail |
|--------|--------|--------|
| **False-Hit Rate** | **0%** (0 / 100) | Tested on challenging near-miss negatives (entity/quarter/topic swaps). |
| **True-Hit Rate (L3)** | **100%** (10 / 10) | Correctly fires on same-context paraphrased queries. |
| **Hit Latency** | **~46ms** | 100 isolated pairs evaluated in 4.6s. |
| **Concurrency Guard** | **0 dupes** | Tested at 20, 50, and 100 concurrent identical queries (0 lock errors, max 1 generation). |

## Architecture: Embedded vs Server Mode

| Feature | Embedded Mode | Server Mode |
|---------|---------------|-------------|
| **Vector Store** | LanceDB (Local) | Qdrant (Docker) |
| **Exact Store** | SQLite (Local) | Redis (Docker) |
| **Setup Complexity** | Zero (just `pip install`) | Requires Docker/Compose |
| **Best For** | Prototyping, small scripts, CLI apps | Production, multi-tenant APIs, heavy concurrency |

For Server Mode, see `docker-compose.yml` and `api/server.py`.
