# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-20

### Added
- **Monorepo Structure**: Clean separation of core reusable engine (`packages/ico-cache-py`), client SDK (`packages/ico-cache-js`), demo app (`apps/financial-rag-demo`), and example corpora (`examples/sec-filings-corpus`).
- **PEP 561 Typing**: Added `py.typed` marker to `ico_cache` for strict type-checking in consuming codebases.
- **Embedded Observability**: Integrated structured logging via `structlog` in `CacheEngine` covering layer decisions (L1/L2/L3/MISS) and latency profiling per layer without external infrastructure.
- **API Hardening**: Added `/health` backend connectivity status reporting, versioned `/v1/` routes, `slowapi` rate limiting, and request/response logging with `X-Request-ID`.
- **Packaging & Version Sync**: Pinned dependency versions across packages and added automated tests enforcing matching version numbers between Python and TypeScript/JavaScript SDKs.
- **CI Workflow**: Comprehensive `.github/workflows/ci.yml` running Ruff linting, Mypy type-checking, concurrency tests, and automated 0% false-hit threshold regressions.
