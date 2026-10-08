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

Run an entire semantic cache locally in 30 seconds with **zero external services** (LanceDB, SQLite, and local FastEmbed embeddings run embedded out of the box):

```python
import asyncio
from ico_cache import CacheEngine

async def main():
    # Initialize zero-infra cache (LanceDB + SQLite + FastEmbed)
    engine = CacheEngine.embedded()

    # Query 1: Initial user question
    query = "What does the fetch_user(id) function return?"
    result = await engine.resolve(query)

    if result["source"] == "MISS":
        print("Cache MISS. Calling model...")
        answer = {"text": "It returns the user record matching id, or None if not found."}
        # Save to exact (L1) and semantic (L2) cache
        engine.set_l1(query, answer)
        await engine.async_write_l2(query, answer)
    else:
        print(f"Cache HIT via {result['source']}: {result['response']}")

    # Query 2: Paraphrased query — instantly matches via L2 semantic cache!
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

---

## Architecture: The Multi-Tiered Cache Cascade

```text
Real Documents (PDFs / Docs / AST)
               ↓
    LangGraph RAG Workflow
               ↓
       ICO-Cache Cascade
┌────────────────────────────────────────────────────────┐
│ L0a: Deterministic Function / Math / Health Cache      │
│ L0b: FastEmbed Embedding Vector Cache                  │
│ L1 : Exact Prompt Match (SHA-256 Normalized Hash)      │
│ L2 : Semantic Vector Cosine Similarity (LanceDB/Qdrant)│
│ L3 : Context-Aware Multi-Turn Dialogue Matching        │
│ L4 : RAG Document Retrieval Chunk Set Cache            │
│ L5 : Assembled Context Token Prompt Cache              │
└────────────────────────────────────────────────────────┘
               ↓
   LLM / Local Grounded Synthesis
               ↓
  Cost / Token / Latency Accounting & Decision Trace
               ↓
  Live Real-Time Dashboard (WebSocket Sync on :3000)
```

---

## Quickstart: Run From Anywhere in 2 Minutes

### Prerequisites
- **Python 3.11+**
- **Node.js 20+**
- (Optional) Redis and Qdrant via Docker, or embedded mode with SQLite & LanceDB (runs out of the box).

---

### Step 1: Clone & Install Dependencies

```bash
git clone https://github.com/DEV-S-SHAH/ICO.git
cd ICO

# 1. Install Python core library in editable mode
pip install -e packages/ico-cache-py

# 2. Install demo requirements
pip install -r examples/real-rag-demo/requirements.txt
```

---

### Step 2: Start the Backend & RAG Cache Engine

```bash
# Starts the FastAPI RAG engine, Ingestion pipeline, and WebSocket server on http://localhost:8000
python examples/real-rag-demo/src/main.py --host 0.0.0.0 --port 8000
```

- **Health Probe**: `http://localhost:8000/v1/health`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **RAG Endpoint**: `POST http://localhost:8000/rag/query`
- **Live Metrics**: `http://localhost:8000/v1/metrics/overview`

---

### Step 3: Start the Live Telemetry Dashboard

In a new terminal window:

```bash
cd apps/dashboard
npm install
npm run dev
```

Open **[http://localhost:3000](http://localhost:3000)** in your browser:
- **Real-Time WebSocket Sync**: Connects to `ws://localhost:8000/ws`.
- **Live Request Stream**: Top ticker and pulsing feed show each request entering and exiting in real time.
- **Cache Analysis**: Inspect hit rates, stored entries, and token savings across L0–L5.
- **Permanent Navigation**: Full access to Requests, Cache, Models, Providers, Costs, Analytics, Playground, and System Settings.

---

### Step 4: Run the 50-Query Multi-Tier Showcase

Observe guaranteed hits across **L0a, L1, L2, and L3 Context-Aware** tiers:

```bash
python scripts/showcase_live_queries.py
```

Expected output:
```text
===============================================================================================
  SYNAPSE / ICO-CACHE: 50 CHALLENGING MULTI-TURN & CONTEXT-AWARE (L3) SHOWCASE
  Streaming live to Dashboard at http://localhost:3000
===============================================================================================
[01/50] [L0a HIT]                 calc: 1024 * 768                              |   4.8ms | saved   8 toks
[02/50] [L0a HIT]                 calc: (4500000 - 3200000) / 4500000           |   1.0ms | saved  15 toks
[03/50] [L0a HIT]                 ping                                          |   2.1ms | saved   2 toks
[06/50] [MISS]              [CTX] What are the specific debt service coverage c |  85.0ms | saved   0 toks
[07/50] [L3 HIT (sim=0.946)] [CTX] Can you summarize the debt service constraint |  23.1ms | saved 147 toks
[10/50] [L3 HIT (sim=0.975)] [CTX] Detail the amortized inference cost limits an |  22.2ms | saved 143 toks
[23/50] [L1 HIT]                  Enumerate the aggregate capital expenditure a |   2.3ms | saved 132 toks
[28/50] [L2 HIT (sim=0.916)]       How did consolidated operating profitability  |  22.6ms | saved 105 toks
===============================================================================================
 Cache Hits: 68.8% - 100% across all tiers | Sub-millisecond to 15ms latency
===============================================================================================
```

---

## CLI & TypeScript SDK

The TypeScript SDK and `ico-cache` CLI can be executed directly:

```bash
# Build the TypeScript SDK
cd packages/ico-cache-js
npm install
npm run build

# Run the CLI
npx ./dist/cli.js status
npx ./dist/cli.js stats
npx ./dist/cli.js query "What is the annual revenue of Acmo Corp in 2024?"
```

---

## Docker Compose Deployment

To run the entire distributed stack (Qdrant, Redis, RAG API, and Dashboard) in Docker:

```bash
docker compose -f docker/docker-compose.yml up -d
```

---

## Testing & Quality Assurance

All test fixtures are generated deterministically at runtime with zero external dataset downloads:

```bash
# 1. Python core package tests (565 tests)
python -m pytest packages/ico-cache-py/tests/ -q

# 2. Real RAG demo integration tests
python -m pytest examples/real-rag-demo/tests/ -q

# 3. TypeScript SDK tests
cd packages/ico-cache-js && npm test
```

---

## Repository Layout

```text
.
├── packages/
│   ├── ico-cache-py/          # Python library ('ico-cache' on PyPI)
│   └── ico-cache-js/          # TypeScript SDK & CLI ('ico-cache-js')
├── apps/
│   ├── dashboard/             # Real-time React + Vite + Tailwind live telemetry dashboard
│   └── financial-rag-demo/    # Reference FastAPI + Streamlit application
├── examples/
│   └── real-rag-demo/         # End-to-end PDF RAG with LangGraph, FastEmbed, LanceDB, and Qdrant
├── scripts/
│   ├── showcase_live_queries.py # 50-query live showcase across L0a, L1, L2, L3
│   └── validate_real_rag.py   # Comprehensive validation gatekeeper
├── docker/                    # Docker Compose production definitions
├── deploy/                    # Kubernetes Helm charts & manifests
└── docs/                      # Architectural specifications & decision records
```

---

## License

Distributed under the [MIT License](LICENSE).