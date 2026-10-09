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
| **False-Hit Rate** | Prone to false positives in naïve vector caches | **0.00% false-hit baseline** enforced by `hard_gate` metadata validation + `serve_threshold` semantic gate |
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

## Serving Guardrails & Recommended Configuration

In production, gate semantic serves so a cached answer is only returned for sufficiently similar questions — this prevents wrong answers on near-identical but differently-worded queries:

```python
engine = CacheEngine.embedded(serve_threshold=0.90, bind_context_to_l1=True)
```

- **`serve_threshold`** (default `0.90`) — cosine similarity a rephrased query must reach to serve a cached L2/L3 answer. Lower = more hits but more risk.
- **`bind_context_to_l1=True`** — keep context-awareness on exact (L1) traffic only; recommended for RAG pipelines.
- **`l2_l3_ttl`** (default `3600`) — expiry (seconds) for L2/L3 re-serves.
- **`paraphrase_threshold` / `evidence_overlap_threshold`** (off by default) — optional evidence-grounding band for paraphrase hits; keep off on small corpora.

Measured across 11 corpora (warm cache): **74–100% of LLM calls eliminated with 0 additional incorrect answers**. Finance/contract-style corpora should raise `serve_threshold` to ~0.95.

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

# 5. 200-query all-layer live trial (L0a, L0b, L1-L5) against the demo
python scripts/trial_200_all_layers.py

# 6. Security and vulnerability audit
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

### Step 4: Run the 200-Query All-Layer Trial

`scripts/trial_200_all_layers.py` fires exactly **200 requests** through the **entire**
cascade — **L0a, L0b, L1, L2, L3, L4, and L5** — using deliberately difficult,
domain-grounded questions drawn from the demo corpus (Transformer attention,
ICO-Cache architecture, and RAG). It exercises exact match, semantic paraphrase,
context-aware multi-turn dialogue, embedding caching, retrieval caching, and
assembled-context caching in a single pass.

```bash
python scripts/trial_200_all_layers.py
```

Representative output:
```text
====================================================================================================
  ICO-CACHE: 200-QUERY ALL-LAYER TRIAL (L0a / L0b / L1 / L2 / L3 / L4 / L5)
  Target: http://127.0.0.1:8000   Model: gemini-1.5-flash
====================================================================================================
[001/200] L0a    [L0a HIT]                 calc: (12873 * 47 - 2934) / 7                  0.6ms saved   14
[003/200] L0a    [L0a HIT]                 calc: round(1234567.891 * 3.14159, 2)          0.7ms saved   20
[055/200] L1     [L1 HIT]                  What are the tradeoffs between dense and sparse 0.7ms saved  154
[057/200] L1     [L2 HIT]       sim=0.857  How does chunking granularity affect retrieval 3.8ms saved  113
[083/200] L2     [L2 HIT]       sim=0.987  What makes source provenance and citation trac 6.3ms saved  168
[086/200] L2     [L2 HIT]       sim=0.966  Describe scaled dot-product attention and the  4.5ms saved  143
[131/200] L3-base [L3 HIT]      sim=0.890  How should provenance metadata be structured to 6.0ms saved  139
[134/200] L3     [L3 HIT]       sim=0.888  Why does citation tracking matter for regulated 12.6ms saved 136
====================================================================================================
  200-QUERY ALL-LAYER TRIAL SUMMARY
====================================================================================================
  Total requests       : 200
  Cache hits           : 116 (58.0%)
  Cache misses (LLM)   : 84
  Tokens saved         : 11336
  Avg hit latency      : 2.1 ms
  Avg miss latency     : 154.9 ms
  Winning-layer hits:
    - L0a : 40
    - L1  : 43
    - L2  : 15
    - L3  : 18
  Internal cascade metrics (cumulative):
    - L0b : 360 reqs, hitRate 1.000, latencySaved 8941.8 ms
    - L4  : 84 reqs, hitRate 0.179, latencySaved 386.2 ms
    - L5  : 200 reqs, hitRate 0.420, latencySaved 0.0 ms
====================================================================================================
```

Measured per block (fresh cache state):

| Block | Requests | Cache hits | Winning tiers | Tokens saved |
| :--- | ---: | ---: | :--- | ---: |
| L0a deterministic | 30 | 30 (100%) | L0a ×30 | 377 |
| L1 exact match | 30 | 16 (53%) | L1 ×14, L2 ×2 | 2,270 |
| L2 semantic paraphrase | 30 | 24 (80%) | L2 ×13, L1 ×11 | 3,491 |
| L3 context-aware dialogue | 50 | 16 (32%) | L3 ×16 | 2,296 |
| L4/L5 bypass retrieval | 30 | 0* | internal L4/L5 | 0 |
| Mixed verification | 30 | 30 (100%) | L0a ×10, L1 ×18, L3 ×2 | 2,902 |
| **Total** | **200** | **116 (58.0%)** | | **11,336** |

- **All seven cache types verified hitting in one run**: L0a (40 top-level), L0b (100%
  embedding-cache hit rate, 8.9 s latency saved), L1 (43), L2 (15), L3 (18), L4 (17.9%),
  L5 (42.0%).
- **58.0%** overall hit rate on deliberately hard paraphrases/dialogues; hit latency
  **2.1 ms** vs miss latency **154.9 ms** (≈74× faster).
- The L4/L5 row marks `*` because that block intentionally sends `bypass_cache: true`, so
  requests reach the RAG path directly and exercise the **internal** L4 retrieval cache
  (15 hits) and **L5** assembled-context cache (84 hits); top-level hits are 0 by design.

> For a shorter, dashboard-streamed run, `python scripts/showcase_live_queries.py` runs a
> 50-query multi-turn showcase across L0a, L1, L2, and L3.

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
│   ├── trial_200_all_layers.py  # 200-query all-layer trial across L0a, L0b, L1-L5
│   ├── showcase_live_queries.py # 50-query live showcase across L0a, L1, L2, L3
│   └── validate_real_rag.py   # Comprehensive validation gatekeeper
├── docker/                    # Docker Compose production definitions
├── deploy/                    # Kubernetes Helm charts & manifests
└── docs/                      # Architectural specifications & decision records
```

---

## License

Distributed under the [MIT License](LICENSE).