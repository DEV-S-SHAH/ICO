# ICO-Cache — Development Guide

Dataset-free semantic cache for LLM applications: L1 (exact), L2 (vector), L3 (RAG);
async ingestion, multi-tenancy, observability, universal document loaders, and a
Graph-RAG build prompt in `docs/`. No datasets are bundled — ingest your own documents.

## Repository Layout

| Path | What it is |
| --- | --- |
| `packages/ico-cache-py/` | Python library (`ico-cache` on PyPI, module `ico_cache`). Python 3.11+. |
| `packages/ico-cache-js/` | JavaScript SDK (`ico-cache-js`). Node.js 20+. |
| `apps/financial-rag-demo/` | Demo API (FastAPI) + UI (Streamlit) built on the cache. |
| `deploy/helm/ico-cache/` | Production Helm chart (Qdrant + Redis + API + worker). |
| `examples/` | Schemas and ingestion scripts (financial schema, universal loaders). |
| `scripts/` | Release gates: version sync, changelog, dry-run. |
| `benchmark.py` | 5-dataset benchmark harness; JSON reports to `benchmark-reports/`. |
| `audit.py` | `deps` (pip-audit) / `sast` (bandit) / `static` (ruff+mypy) / `ast` / `secrets`; reports to `audit-reports/`. |
| `docs/` | Architecture and the Graph-RAG build prompt. |

## Commands

```bash
# Tests (Python 3.11)
python -m pytest packages/ico-cache-py/tests/ -q

# Static + type checks
python -m ruff check packages/ico-cache-py/src apps benchmark.py audit.py
python -m mypy packages/ico-cache-py/src

# Security / dependency audit
python audit.py --all        # audits apps/financial-rag-demo/requirements-demo.txt

# Benchmarks
python benchmark.py --dataset all
```

## Conventions

- **Dataset-free**: never commit data. Tests and benchmarks generate deterministic
  fixtures at runtime (`packages/ico-cache-py/tests/fixtures_gen.py`).
- **Version sync**: `ico-cache-py` and `ico-cache-js` must share the same version
  (enforced by `tests/test_version_sync.py`).
- **Universal loaders**: format detection sniffs content, never trusts extensions;
  loaders must tolerate malformed/empty/non-UTF-8/large inputs without raising.
  Active HTML content (`<script>`, event handlers) is stripped before parsing.
- Do not commit secrets, build artifacts, or `node_modules/` (gitignored).