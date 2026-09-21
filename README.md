# ICO-Cache: Generalized LLM Semantic Cache & Universal Document RAG

[![CI](https://github.com/DEV-S-SHAH/ICO/actions/workflows/ci.yml/badge.svg)](https://github.com/DEV-S-SHAH/ICO/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/badge/pypi-ico--cache-blue.svg)](https://pypi.org/project/ico-cache/)
[![npm](https://img.shields.io/badge/npm-ico--cache--js-red.svg)](https://www.npmjs.com/)

ICO-Cache is a production-grade, installable 3-tier semantic caching and retrieval engine for LLMs. It turns repetitive LLM generation from seconds into tens of milliseconds, cuts inference cost, and enforces a **0% false-hit rate** through hard metadata gating.

It ships with a **universal ingestion layer**: CSV, TXT, JSON/JSONL, HTML, PDF (text-layer and scanned/OCR), OpenDocument (ODT/ODS), Microsoft Office (DOCX/XLSX/PPTX), images, and source code are all auto-detected **by content, not file extension** — so you can feed it any document and it just works. **No datasets are bundled**; you bring your own documents.

Read the [Detailed Cache Architecture & Layer Design Guide](docs/ARCHITECTURE.md).

---

## Features

- **3-tier cache** — L1 exact (Redis/SQLite), L2 semantic (Qdrant/LanceDB), L3 dual-context (multi-vector) with an adaptive threshold.
- **Blast-radius safety** — `hard_gate` metadata guard guarantees zero cross-entity / cross-quarter / cross-topic false hits.
- **Multi-tenant** — collection or payload isolation; authenticated per-tenant API keys (timing-safe).
- **Universal ingestion** — content-sniffing loaders + OCR fallback for any document, no matter the extension.
- **Single-flight dedup** — 20+ concurrent identical queries trigger exactly one LLM generation.
- **Observable** — Prometheus `/metrics`, OTLP/Langfuse tracing, structured JSON logs, `/v1/ready` (fails closed when a dependency is down).
- **Distributed by default** — Redis Streams invalidation worker, cluster-wide rate limiting.
- **Kubernetes-native** — hardened Helm chart (StatefulSets + PVCs, security contexts, external Secrets, image digests, PDBs).
- **Zero-infra dev mode** — LanceDB + SQLite + FastEmbed run entirely embedded.

---

## Repository Structure

```text
.
├── packages/
│   ├── ico-cache-py/              # Core Python library (pip package: ico-cache)
│   │   ├── pyproject.toml
│   │   ├── src/ico_cache/         # Engine, backends, universal loaders, telemetry
│   │   │   ├── core/              # CacheEngine (L1/L2/L3), metadata guard
│   │   │   ├── backends/          # vector (Qdrant/LanceDB), exact (Redis/SQLite), embedding
│   │   │   ├── loaders/           # universal content-based loaders + OCR
│   │   │   └── telemetry/         # Prometheus metrics, structlog, OTel/Langfuse
│   │   └── tests/                 # Dataset-free self-contained verification suite
│   └── ico-cache-js/              # TypeScript / JavaScript client SDK (npm: ico-cache-js)
├── apps/
│   └── financial-rag-demo/        # Financial RAG demo application
│       ├── api/                   # Hardened FastAPI service (/v1/*, rate limiting, health, metrics)
│       ├── ui/                    # Streamlit interactive query interface
│       └── docker/                # docker-compose.yml and container definitions
├── examples/
│   ├── financial_schema.py        # SEC-filing metadata schema
│   ├── universal_schema.py        # Cross-format metadata schema
│   ├── ingest_*.py                # Ready-made ingestion entry points
│   └── sec-filings-corpus/        # SEC EDGAR fetching/cleanup scripts (no data committed)
├── deploy/helm/ico-cache/         # Hardened installable Helm chart
├── docs/ARCHITECTURE.md           # In-depth architectural documentation
├── .env.example                   # Environment configuration template
├── eval_harness.py                # 0% false-hit evaluation harness (self-generating)
└── CHANGELOG.md                   # Version release notes
```

---

## Installation

Requires **Python 3.11+**.

```bash
# From PyPI (once published)
pip install ico-cache

# Or direct from GitHub
pip install "git+https://github.com/DEV-S-SHAH/ICO.git#subdirectory=packages/ico-cache-py"

# Extras
pip install "ico-cache[loaders,observability]"   # full document loaders + tracing
```

### TypeScript / JavaScript SDK (NPM)

```bash
cd packages/ico-cache-js
npm install
npm run build   # requires Node.js >= 20
```

---

## Quickstart: Zero-Infra Embedded Mode

Run ICO-Cache with **zero external services or Docker containers** — LanceDB for embedded vectors, SQLite for exact keys, FastEmbed for local ONNX embeddings:

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
        metadata_filter_keys=["entity", "quarter", "topic"],
        adaptive_threshold=True,
    )

    query = "What was Apple's total revenue in Q1?"
    result = await engine.resolve(query)

    if result["source"] == "MISS":
        print("Cache MISS. Generating fresh response...")
        answer = {"text": "$119.58 billion as reported in Apple Q1 10-Q."}
        engine.set_l1(query, answer)
        await engine.async_write_l2(query, answer)
    else:
        print(f"Cache HIT via {result['source']}: {result['response']}")

    paraphrased = "Apple Q1 revenue total"
    hit = await engine.resolve(paraphrased)
    print(f"Paraphrased query hit: {hit['source']} -> {hit['response']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Universal Ingestion

Feed **any** document — CSV, TXT, JSONL, HTML, PDF (incl. scanned), ODT/ODS, DOCX/XLSX/PPTX, PNG/JPG/TIFF, or source code — through the same AutoLoader. Format detection is content-based and OCR kicks in when a page is an image:

```python
from ico_cache.loaders import AutoLoader, ingest, configure_ocr
from examples.universal_schema import universal_schema

configure_ocr(enabled=True, languages="eng")        # optional tuning
chunks = AutoLoader(schema=universal_schema).load("annual_report.pdf")
for chunk in chunks:
    print(chunk.text, chunk.metadata)
```

---

## Distributed Server Mode (Docker Stack)

```bash
cp .env.example .env
cd apps/financial-rag-demo/docker
docker compose up -d
```

- **API Docs**: http://localhost:8000/docs — **Health**: http://localhost:8000/v1/health
- **Readiness**: http://localhost:8000/v1/ready (503 when a backend is down) — **Metrics**: http://localhost:8000/v1/metrics
- **Streamlit Demo UI**: http://localhost:8501 — **Qdrant Dashboard**: http://localhost:6333/dashboard

> [!WARNING]
> The preset demo API keys (`dev-key-default`, `key-tenant-a`, `key-tenant-b`) in `.env.example` and the UI selector are **insecure local fixtures only**. Always set cryptographically secure per-tenant keys via `API_KEYS` in production.

### Deploying to Kubernetes

```bash
helm install ico-cache deploy/helm/ico-cache \
  --set secrets.geminiApiKey='<key>' \
  --set externalSecrets.enabled=false
```

The chart runs Qdrant + Redis as StatefulSets with PVCs, runs every pod non-root with read-only root filesystems, supports immutable image digests, external Secret injection (external-secrets operator), a pod disruption budget, and a real worker entrypoint (`python -m ico_cache.invalidation`) with `/healthz` probes.

---

## Architecture Summary

| Layer | Technology | Typical Latency | Purpose |
| :--- | :--- | :--- | :--- |
| **L1 Exact** | Redis / SQLite | `< 1ms` | Instant hits for identical repeat queries with metadata fingerprinting. |
| **L2 Semantic** | Qdrant / LanceDB | `~15–30ms` | Matches reworded and paraphrased queries asking the same question. |
| **L3 Dual-Context** | Qdrant / LanceDB | `~30–50ms` | Resolves multi-turn and context-dependent queries. |
| **Guardrail** | `hard_gate` | `< 0.1ms` | Hard-blocks near-miss cross-entity / cross-quarter / cross-topic false hits. |

Details on the multi-vector schema, threshold tuning, and gating rules: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Testing & Quality Assurance

The test suite is **fully self-contained** — every fixture is generated at runtime, so there are no bundled datasets to download.

```bash
# 1. Lint and type-check
ruff check packages/ico-cache-py/src apps/financial-rag-demo
mypy packages/ico-cache-py/src

# 2. Pytest unit & layer verification
PYTHONPATH=packages/ico-cache-py/src pytest packages/ico-cache-py/tests/

# 3. 0% false-hit evaluation harness (self-generating synthetic data, or pass --data-dir)
PYTHONPATH=packages/ico-cache-py/src python3 eval_harness.py
PYTHONPATH=packages/ico-cache-py/src python3 eval_harness.py --eval-adversarial
```

CI runs lint, type-check, the full suite against live Redis + Qdrant, image builds, and `helm lint`/`template`. CodeQL runs on every push/PR and weekly.

---

## Publishing

The Python package (`ico-cache`) and JS SDK (`ico-cache-js`) are build-ready:

```bash
cd packages/ico-cache-py
pip install build twine
python -m build
twine check dist/*

# Publish to TestPyPI first
twine upload --repository testpypi dist/*
# Then to PyPI
twine upload dist/*
```

---

## License

MIT — see [LICENSE](LICENSE).