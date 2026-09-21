# ICO-Cache: Semantic Caching Middleware for LLM Applications

[![CI](https://github.com/DEV-S-SHAH/ICO/actions/workflows/ci.yml/badge.svg)](https://github.com/DEV-S-SHAH/ICO/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ico-cache.svg)](https://pypi.org/project/ico-cache/)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)](https://pypi.org/project/ico-cache/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

ICO-Cache is a high-performance, cross-platform semantic caching middleware designed for **LLM applications, coding agents, and RAG pipelines**. It sits directly between your application and model APIs, caching responses so repeated or semantically equivalent queries never re-run through the LLM.

It is available as both a Python library ([`ico-cache`](https://pypi.org/project/ico-cache/)) and a TypeScript/JavaScript SDK (`ico-cache-js`).

```bash
pip install ico-cache
```

---

## Why ICO-Cache?

| Metric | Without Cache | With ICO-Cache (`pip install ico-cache`) |
| :--- | :--- | :--- |
| **API Token Cost** | 100% cost on every repeated/reworded prompt | **Drastically reduced** via L1 exact & L2/L3 semantic hits |
| **Response Latency** | Seconds (2,000ms – 10,000ms+) | **Sub-millisecond** (L1) or **15–30ms** (L2/L3) |
| **False-Hit Rate** | Prone to false positives in naïve vector caches | **0.00% false-hit baseline** enforced by `hard_gate` metadata validation |
| **Cross-Platform** | Fragile file locking / signal handling | **Fully supported** across Linux, Windows, and macOS |

> **Reference Demo:** `apps/financial-rag-demo` provides a reference implementation running against SEC filings with FastAPI + Streamlit to illustrate real-world usage.

For full setup options, see [Installation & Extras](#installation) or the [Architecture Documentation](docs/ARCHITECTURE.md).

---

## Core Capabilities

- **3-Tier Semantic Hierarchy**:
  - **L1 (Exact)**: Sub-millisecond direct key lookup (Redis / SQLite) with metadata fingerprinting.
  - **L2 (Semantic)**: Vector cosine similarity matching for rephrased queries (Qdrant / LanceDB).
  - **L3 (Context-Aware)**: Multi-vector representation accounting for session and dialogue context.
- **Blast-Radius Guardrails**: Strict `hard_gate` schema checks prevent cross-entity, cross-quarter, or cross-tenant cache bleed.
- **Single-Flight Coalescing**: Concurrent identical cache misses collapse into a single LLM request.
- **Universal Ingestion**: Content-sniffed loaders (PDF, Office DOCX/XLSX/PPTX, ODF ODT/ODS, TXT, CSV, JSON/JSONL, HTML, Code AST, Images with OCR).
- **Multi-Tenancy**: Isolated partitions via dedicated collections or timing-safe authenticated payload filters.
- **Production Observability**: Built-in Prometheus metrics (`/metrics`), OpenTelemetry tracing, structured JSON logs, and `/v1/ready` health probes.
- **Zero-Infra Mode**: Runs out of the box with embedded SQLite + LanceDB + FastEmbed without Docker dependencies.

---

## Installation

Requires **Python 3.11+**. Fully compatible with Linux, Windows, and macOS.

```bash
# Core package from PyPI
pip install ico-cache

# With document loaders (PDF, OCR, Office, AST parsers) and tracing
pip install "ico-cache[loaders,observability]"
```

### TypeScript / JavaScript SDK

```bash
cd packages/ico-cache-js
npm install
npm run build
```

---

## Quickstart: Zero-Infra Embedded Mode

Run an entire semantic cache locally without starting Redis or Qdrant:

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
        print("Cache MISS. Calling model...")
        answer = {"text": "It returns the user record matching id, or None if not found."}
        engine.set_l1(query, answer)
        await engine.async_write_l2(query, answer)
    else:
        print(f"Cache HIT via {result['source']}: {result['response']}")

    # Paraphrased query hits L2 semantic cache
    paraphrased = "what is the return value of fetch_user with an id?"
    hit = await engine.resolve(paraphrased)
    print(f"Paraphrased query hit: {hit['source']} -> {hit['response']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Universal Document Ingestion

ICO-Cache sniffs content headers directly (extension-agnostic) with automatic OCR fallback for scanned pages and images:

```python
from ico_cache.loaders import AutoLoader, configure_ocr
from examples.universal_schema import universal_schema

# Optional OCR configuration
configure_ocr(enabled=True, languages="eng")

loader = AutoLoader(schema=universal_schema)
chunks = loader.load("quarterly_report.pdf")

for chunk in chunks:
    print(f"[{chunk.page_or_section}] {chunk.text[:100]}... (Metadata: {chunk.metadata})")
```

---

## Distributed Production Deployment

### Docker Compose Stack

Launch the production API, Streamlit UI, Qdrant, and Redis:

```bash
cp .env.example .env
cd apps/financial-rag-demo/docker
docker compose up -d
```

- **API Documentation**: `http://localhost:8000/docs`
- **Health / Readiness**: `http://localhost:8000/v1/health` | `http://localhost:8000/v1/ready`
- **Prometheus Metrics**: `http://localhost:8000/v1/metrics`
- **Interactive UI**: `http://localhost:8501`

### Kubernetes (Helm)

```bash
helm install ico-cache deploy/helm/ico-cache \
  --set secrets.geminiApiKey='<your-key>' \
  --set externalSecrets.enabled=false
```

---

## Testing & Quality Assurance

All test fixtures are deterministically generated at runtime (**no external datasets to download**):

```bash
# 1. Lint and type-check
python -m ruff check packages/ico-cache-py/src apps/financial-rag-demo
python -m mypy packages/ico-cache-py/src

# 2. Pytest test suite
python -m pytest packages/ico-cache-py/tests/ -v

# 3. 0% false-hit baseline verification
python eval_harness.py
python eval_harness.py --eval-adversarial

# 4. 5-Dataset benchmark harness
python benchmark.py --dataset all

# 5. Security and vulnerability audit
python audit.py --all
```

---

## Repository Layout

```text
.
├── packages/
│   ├── ico-cache-py/          # Python library ('ico-cache' on PyPI)
│   └── ico-cache-js/          # TypeScript SDK ('ico-cache-js')
├── apps/
│   └── financial-rag-demo/    # Reference FastAPI + Streamlit application
├── deploy/helm/ico-cache/     # Production Kubernetes Helm chart
├── examples/                  # Ingestion scripts & schema definitions
├── docs/                      # In-depth architectural specifications
├── benchmark.py               # 5-dataset benchmark harness
├── audit.py                   # SAST, dependency, and AST security audit suite
├── eval_harness.py            # False-hit gatekeeper evaluation
└── CHANGELOG.md               # Version history and release notes
```

---

## License

Distributed under the [MIT License](LICENSE).