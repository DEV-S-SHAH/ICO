# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-20

### Added
- **Universal Document Loaders**: `TXTLoader`, `StructuredLoader` (CSV/JSON with row coalescing), `CodeLoader` (AST-aware, Python/JS/TS/Go/Rust), `PDFLoader` (text-layer + OCR fallback via pytesseract), `HTMLLoader`, and `AutoLoader` dispatch by file extension. All loaders handle malformed input, empty files, non-UTF-8 encodings, and very large files (>10 MB) without raising unhandled exceptions.
- **Config-Driven Metadata Schema**: `MetadataSchema` Pydantic model with field-level extractors. Hard-gate diff in `MetadataGuard` is now fully generic over any schema. Financial extraction moved to `examples/financial_schema.py` as a bundled plugin, not a default.
- **LLM-Agnostic Generation via LiteLLM**: RAG fallback path uses `litellm.completion(model=<configurable>)`. Supports Ollama, OpenAI, Anthropic, Gemini, Groq, and any LiteLLM-compatible provider. Model selected at runtime via `OLLAMA_MODEL` or the Streamlit UI.
- **Multi-Tenancy**: `CacheEngine` supports both `collection-per-tenant` and `payload-filter` isolation modes. Payload-filter mode uses filtered point deletes on invalidation — shared collections are never dropped. Verified: cross-tenant isolation holds in both embedded (LanceDB/SQLite) and distributed (Qdrant/Redis) backends.
- **Async Ingestion Pipeline**: `IngestionJobManager` with background worker threads, per-job status tracking, TTL-based eviction (1 hour default), and capacity cap (10 000 jobs). Thread-local `AsyncQdrantClient` prevents event-loop collisions at 100+ concurrent ingest workers.
- **Distributed Backend Parity**: Full parity between embedded (LanceDB + SQLite + FastEmbed) and distributed (Qdrant + Redis) stacks verified across all test modes. Redis Streams invalidation correctly purges Qdrant collections and payload-filtered points.
- **OpenTelemetry Tracing**: Span instrumentation on L1/L2/L3 resolve, RAG fallback, and ingest paths via `ico_cache.telemetry.tracing`. Configurable OTLP exporter; Langfuse integration for LLM call tracing.
- **Adversarial Evaluation Suite**: `cross_type_adversarial.jsonl` — 32 near-miss pairs (similarity 0.80–0.8483) with no metadata conflicts. False-hit rate: **0.00%**. Extends `eval_harness.py` with `--loader-type` flag for per-type and mixed corpus evaluation.
- **Automated Release Pipeline**: `release.yml` GitHub Actions workflow on tag push — version sync gate, changelog enforcement, full pytest + eval harness gate (must be 0% false hits), Helm lint, PyPI publish, npm publish, Docker push to GHCR, GitHub Release creation with CHANGELOG notes.
- **Helm Chart**: Production-ready Helm chart at `deploy/helm/ico-cache` with configurable replicas, resource limits, ingress, and secrets.
- **OCR Scanned-PDF Support**: `PDFLoader` tracks `last_status` (`text_layer_success` / `ocr_success` / `image_only_no_text`) and reports data-loss events when scanned pages yield zero extractable text.
- **StructuredLoader Row Coalescing**: 50–100 rows per chunk (configurable). Large CSV benchmark (10 MB, ~10 000 rows) completes in under 10 s.

### Fixed
- Payload-filter mode invalidation now uses `delete_matching` (filtered point delete) instead of falling through to `delete_collection`, which would have wiped all tenants sharing a collection.
- `AsyncQdrantClient` made thread-local to prevent `ValueError: list.remove(x): x not in list` under concurrent ingest load.
- Synchronous `submit_ingest` spawns a dedicated thread to avoid `RuntimeError: Cannot run the event loop while another loop is running` inside FastAPI async handlers.

### Security
- Preset API keys (`dev-key-default`, `key-tenant-a`, `key-tenant-b`) are now explicitly labelled `[DEV ONLY]` in the Streamlit UI, `.env.example`, and `README.md`. Production deployments must provision keys via `API_KEYS` env var.

### Quality
- Ruff: 0 errors across all source files.
- Mypy: 0 errors across 26 source files (all pre-existing type annotation gaps fixed).
- Test suite: **48/48 tests pass** including multi-tenancy, invalidation isolation, telemetry, universal loaders, adversarial similarity bounds, and job manager memory bounds.
- Eval harness: **0% false hits** across text, structured, code, mixed, and adversarial modes on both embedded and Qdrant backends.

## [0.1.0] - 2026-09-20

### Added
- **Monorepo Structure**: Clean separation of core reusable engine (`packages/ico-cache-py`), client SDK (`packages/ico-cache-js`), demo app (`apps/financial-rag-demo`), and example corpora (`examples/sec-filings-corpus`).
- **PEP 561 Typing**: Added `py.typed` marker to `ico_cache` for strict type-checking in consuming codebases.
- **Embedded Observability**: Integrated structured logging via `structlog` in `CacheEngine` covering layer decisions (L1/L2/L3/MISS) and latency profiling per layer without external infrastructure.
- **API Hardening**: Added `/health` backend connectivity status reporting, versioned `/v1/` routes, `slowapi` rate limiting, and request/response logging with `X-Request-ID`.
- **Packaging & Version Sync**: Pinned dependency versions across packages and added automated tests enforcing matching version numbers between Python and TypeScript/JavaScript SDKs.
- **CI Workflow**: Comprehensive `.github/workflows/ci.yml` running Ruff linting, Mypy type-checking, concurrency tests, and automated 0% false-hit threshold regressions.
