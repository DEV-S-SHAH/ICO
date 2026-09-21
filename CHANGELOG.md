# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- **Vendored dependencies and tooling config**: `packages/ico-cache-js/node_modules/` (TypeScript compiler) is no longer committed (gitignored); GitNexus agent scaffolding (`.agents/`, `.claude/`) and its root docs (`AGENTS.md`/`CLAUDE.md` gitnexus block) removed; `test_concurrency.py` scratch load-test removed. `AGENTS.md` now documents the project itself.
- **Dead/unreferenced files**: `docs/BUILD_GRAPH_RAG_TERMINAL_PROMPT.md` (agent build prompt), `PRODUCTION_CHECKLIST.md`, `langfuse-compose-example.yml`, and `apps/financial-rag-demo/ui/scripted_journey.json` (no references anywhere in the repo).

### Changed
- **Default LLM is now Google Gemini** (`gemini/gemini-flash-latest` via LiteLLM). Configure with `GEMINI_API_KEY` and `LLM_MODEL`; `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` control timeouts and retries. Ollama is no longer required or shipped as the default.
- **Python 3.11+ / Node.js 20+**: base images, CI and release workflows, `requires-python`, and ruff/mypy targets upgraded.
- **Universal, dataset-free by design**: all bundled corpora (`examples/test-corpus`, `examples/sec-filings-corpus/datasets`, `examples/data`) removed from the repository. The test suite and `eval_harness.py` now generate deterministic synthetic fixtures at runtime, so the library ingests any document you provide — no data ships with it.

### Added
- **Single-flight generation**: `CacheEngine.resolve_or_generate` coalesces concurrent identical cache misses into one generation and performs conditional (insert-if-absent) writes.
- **Never cache errors**: refusals ("Insufficient context."), empty answers, and generation failures are returned to the caller but never written to L1/L2/L3.
- **Graceful degradation**: each L1/L2/L3 lookup is bounded by `lookup_timeout` and failures are swallowed to a MISS instead of surfacing a 500.
- **Stable cache IDs**: L2/L3 point ids are derived from sha256 (process-independent), replacing the non-deterministic `hash()`.
- **Non-blocking I/O**: embedding, exact-store access, and Qdrant search run off the event loop (`asyncio.to_thread` / async client).
- **Content-based universal ingestion**: format detection sniffs content (PDF magic bytes, decodable images) rather than trusting extensions; OCR fallback (`OCR_ENABLED` / `OCR_LANGUAGES` / `OCR_DPI`) covers scanned PDFs and images; new loaders for ODT/ODS, DOCX/XLSX/PPTX, and images.
- **Benchmark harness (`benchmark.py`)**: five dataset types generated at runtime — `paraphrase-hit` (efficiency: hit rate, latency p50/p90, throughput, LLM-avoidance), `adversarial` (near-miss false-hit + tenant-bleed prevention), `multilingual` (cross-language paraphrase matching), `code-ast` (tree-sitter entity extraction), `lifecycle` (stale-write suppression, invalidation, eviction hit ratio). Writes a JSON report to `benchmark-reports/`.
- **Code + security audit (`audit.py`)**: five phases — `deps` (pip-audit CVEs), `sast` (bandit SAST), `static` (ruff + mypy), `ast` (tree-sitter AST scan of py/js/go for structure + credential/risky-pattern markers), `secrets` (regex scan of git-tracked text). Writes a JSON report to `audit-reports/`; the `audit` extra ships bandit + pip-audit, and `tree-sitter-python` joins the `loaders` extra.
- **Fixed in audit pass**: `IcoCache` HTTP client now sends `requests` calls with a 10s timeout and `raise_for_status` (was: unbounded, unchecked calls — bandit B113).
- **Observability**: Prometheus metrics (`/v1/metrics`), `configure_logging` structured JSON logs, OTel/Langfuse tracing exporters, `/v1/health` + `/v1/ready` probes (readiness 503s when a dependency is down).
- **Distributed rate limiting**: cluster-wide limit via `RATE_LIMIT_STORAGE_URI` (Redis) with hashed-API-key buckets; `memory://` in dev.
- **Helm hardening**: Qdrant/Redis StatefulSets with PVCs and retain-on-delete, pod/container `securityContext`s (non-root, read-only root, dropped caps, seccomp), external-secrets operator support, ServiceAccount + automount-off, PodDisruptionBudgets, immutable image digests, and a real worker entrypoint (`python -m ico_cache.invalidation` with a `/healthz` HTTP probe and graceful shutdown).
- **Dependency automation**: Dependabot (pip/npm/docker/actions) and CodeQL (Python + JavaScript/TypeScript) on push/PR and weekly.

### Fixed
- Vector payloads are JSON-encoded on write and decoded on read (LanceDB), replacing the lossy `str()` / `replace("'", '"')` round-trip.
- Test suite: real `conftest.py` with service-free fixtures, `asyncio_mode = "auto"`, a working single-flight stampede test, and unit tests for `resolve`.

## [1.0.1] - 2026-09-21

### Security
- **Active-content hardening in `HTMLLoader`**: `<script>`/`<style>`/`nav`/`header`/`footer`/`aside`/`iframe` blocks, inline event handlers (`onerror=` etc.), and `javascript:` URIs are stripped from the raw markup *before* parsing. Python's bundled `html.parser` can re-parent such payloads into surrounding text on 3.11 for malformed documents, so source-level removal is parser-version-independent. XSS/`onerror` payloads are never ingested (verified on Python 3.11 / BeautifulSoup 4.15).
- **`PyPDF2` replaced with `pypdf`** in core dependencies: removes PYSEC-2026-1835 (infinite loop), the only CVE in the production install. `pip-audit` on the production venv: **0 CVEs**.
- **LanceDB cosine distance now actually applied**: `_distance` was silently L2 after the search-builder `.metric()` API was removed (lancedb ≥ 0.34), making cosine similarity wrong. Sets a cosine index per collection at creation and calls `.metric()` only when supported.
- `audit.py` deps phase now audits the committed production file `apps/financial-rag-demo/requirements-demo.txt` (used by Dockerfiles).

### Changed
- Version **1.0.1** (Python `ico-cache` and JS `ico-cache-js` kept in sync per `test_version_sync`).

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
