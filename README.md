# ICO-Cache: Generalized LLM Semantic Cache

[![CI](https://github.com/ico-cache/ico-cache/actions/workflows/ci.yml/badge.svg)](https://github.com/ico-cache/ico-cache/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![npm](https://img.shields.io/badge/npm-0.1.0-red.svg)](https://www.npmjs.com/)

ICO-Cache is a high-performance, 3-tier semantic caching engine for Large Language Models. It slashes repetitive LLM generation latency from seconds to tens of milliseconds and cuts operational costs while enforcing **0% false-hit rates** via hard metadata gating.

Read the [Detailed Cache Architecture & Layer Design Guide](docs/ARCHITECTURE.md).

---

## Repository Structure

```text
.
├── packages/
│   ├── ico-cache-py/              # Core Python library (pip package)
│   │   ├── pyproject.toml
│   │   ├── src/ico_cache/         # Engine, metadata guard, vector/exact backends
│   │   └── tests/                 # Verification suite
│   └── ico-cache-js/              # TypeScript / JavaScript client SDK (npm package)
│       ├── package.json
│       └── src/index.ts
├── apps/
│   └── financial-rag-demo/        # Financial RAG demo application
│       ├── api/                   # Hardened FastAPI service (/v1/ routes, rate limiting, health)
│       ├── ui/                    # Streamlit interactive query interface
│       └── docker/                # docker-compose.yml and container definitions
├── examples/
│   └── sec-filings-corpus/        # SEC EDGAR 10-K/10-Q dataset and ingestion scripts
├── docs/
│   └── ARCHITECTURE.md            # In-depth architectural documentation
├── .github/workflows/ci.yml       # Ruff linting, Mypy, and test suite automation
├── .env.example                   # Environment configuration template
├── LICENSE                        # MIT License
└── CHANGELOG.md                   # Version release notes
```

---

## Installation

### Python Package (Pip)

Install the reusable core engine locally:
```bash
# In development mode from monorepo root
pip install -e packages/ico-cache-py

# Or via pip once published
pip install ico-cache
```

### TypeScript / JavaScript SDK (NPM)

Install the JavaScript client SDK:
```bash
# From packages/ico-cache-js
cd packages/ico-cache-js
npm install
npm run build

# Or install from npm once published
npm install ico-cache-js
```

---

## Quickstart: Zero-Infra Embedded Mode

Run ICO-Cache locally in Python with **zero external services or Docker containers**. LanceDB handles local embedded vectors, SQLite handles exact key storage, and FastEmbed runs ONNX embeddings locally:

```python
import asyncio
from ico_cache import CacheEngine
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

async def main():
    # 1. Initialize embedded engine (no Docker or external services required)
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri="./lancedb"),
        exact_store=SQLiteStore(db_path="cache.db"),
        metadata_filter_keys=["entity", "quarter", "topic"],
        adaptive_threshold=True,
    )

    query = "What was Apple's total revenue in Q1?"

    # 2. Resolve query through L1 -> L2 -> L3 cache
    result = await engine.resolve(query)
    
    if result["source"] == "MISS":
        print("Cache MISS. Generating fresh response...")
        # Simulate LLM generation
        answer = {"text": "$119.58 billion as reported in Apple Q1 10-Q."}
        
        # Write back to L1 (exact) and L2 (semantic)
        engine.set_l1(query, answer)
        await engine.async_write_l2(query, answer)
    else:
        print(f"Cache HIT via {result['source']}: {result['response']}")

    # 3. Subsequent paraphrased query hits L2 semantic cache
    paraphrased = "Apple Q1 revenue total"
    hit = await engine.resolve(paraphrased)
    print(f"Paraphrased query hit: {hit['source']} -> {hit['response']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## JavaScript / TypeScript Client Quickstart

```typescript
import { icoCache } from "ico-cache-js";

const cache = icoCache({ baseUrl: "http://localhost:8000" });

async function getAnswer() {
  const query = "What are Apple's main risk factors?";
  
  const response = await cache.resolve(query, null, async () => {
    // LLM fallback invocation on cache MISS
    const res = await fetch("https://api.openai.com/v1/chat/completions", { /* ... */ });
    return await res.json();
  });

  console.log("Answer:", response);
}
```

---

## Distributed Server Mode (Docker Stack)

For multi-tenant APIs, high concurrency, and distributed setups:

```bash
# Copy environment configuration
cp .env.example .env

# Launch Redis, Qdrant, Langfuse, FastAPI, and Streamlit
cd apps/financial-rag-demo/docker
docker compose up -d
```

- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **API Health Check**: [http://localhost:8000/v1/health](http://localhost:8000/v1/health)
- **Streamlit Demo UI**: [http://localhost:8501](http://localhost:8501)
- **Qdrant Dashboard**: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

> [!WARNING]
> **Demo API Keys vs Production Security**: The preset API keys (`dev-key-default`, `key-tenant-a`, `key-tenant-b`) bundled in `.env.example` and the Streamlit UI selector are **insecure local development/demo fixtures only**. For production deployments, always configure cryptographically secure tenant keys via the `API_KEYS` environment variable.

---

## Architecture Summary

| Layer | Technology | Typical Latency | Purpose |
| :--- | :--- | :--- | :--- |
| **L1 Exact** | Redis / SQLite | `< 1ms` | Instant hits for identical repeat queries with metadata fingerprinting. |
| **L2 Semantic** | Qdrant / LanceDB | `~15–30ms` | Matches reworded and paraphrased queries asking the same question. |
| **L3 Dual-Context** | Qdrant / LanceDB | `~30–50ms` | Resolves multi-turn conversation and context-dependent queries. |
| **Guardrail** | `MetadataGuard` | `< 0.1ms` | Hard-blocks near-miss cross-entity and cross-quarter false hits. |

For detailed information on the multi-vector schema, threshold tuning, and metadata gating rules, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Testing & Quality Assurance

Run the test suite and verify false-hit regression baselines:

```bash
# 1. Lint and type-check
ruff check packages/ico-cache-py/src
mypy packages/ico-cache-py/src

# 2. Pytest unit & layer verification
PYTHONPATH=packages/ico-cache-py/src pytest packages/ico-cache-py/tests/

# 3. 0% False-hit evaluation harness
PYTHONPATH=packages/ico-cache-py/src python3 eval_harness.py

# 4. Concurrency stress test
python3 test_concurrency.py
```
