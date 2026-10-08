# Phase 5 Decision Trace — Implementation Report

**Project:** ICO-Cache  
**Date:** 2026-10-08  
**Status:** Complete — all tests pass, mypy/ruff/security audit clean

---

## Summary

Phase 5 implements a comprehensive **Decision Trace** system that explains exactly why every cache request results in a HIT, MISS, reuse, or LLM call. The trace covers the full cascade `L0a → L0b → L1 → L2 → L3 → L4 → L5 → LLM` and is exposed through a clean public API for the Dashboard.

---

## Deliverables

### 1. Core Data Model (`ico_cache/core/decision_trace.py`)

| Class/Enum | Purpose |
|------------|---------|
| `LayerStatus` | `NOT_ATTEMPTED`, `ATTEMPTED`, `HIT`, `MISS`, `BLOCKED`, `SKIPPED` |
| `DecisionOutcome` | `CACHE_RESPONSE`, `REUSE_RETRIEVAL`, `REUSE_CONTEXT`, `GENERATE_LLM`, `PARTIAL_RECOMPUTE` |
| `LayerTrace` | Per-layer record: attempted, hit/miss, reason, latency, reuse source, gates |
| `DecisionTrace` | Full cascade trace with request_id, tenant_id, query_hash, summary() |
| `DecisionTraceStore` | Thread-safe bounded store (LRU 1000) indexed by trace_id, request_id, tenant_id |
| ContextVar helpers | `begin_trace()`, `record_layer()`, `get_active_trace()`, `derive_outcome()` |

**Safety:** No raw queries/responses stored — only truncated SHA-256 `query_hash`. Request/tenant IDs sanitized (control chars stripped, max 128 chars).

---

### 2. DecisionEngine Integration (`ico_cache/core/decision_engine.py`)

- Added `request_id` field to `DecisionContext`
- `decide()` now:
  - Calls `begin_trace()` at start (reuses active trace if present)
  - Records each layer via `record_layer()` → builds `LayerTrace` from `LayerEvaluation`
  - Finalizes with `derive_outcome()` → stores in `trace_store`
  - Uses try/finally to reset contextvar
- Public API: `get_trace()`, `get_trace_by_request()`, `get_recent_traces()`, `get_trace_stats()`

---

### 3. CacheEngine Integration (`ico_cache/core/cache_engine.py`)

| Method | Trace Instrumentation |
|--------|----------------------|
| `__init__` | `enable_decision_tracing=True`, `max_decision_traces=1000`, `DecisionTraceStore` |
| `resolve()` | Creates trace if none active; records L1/L2/L3 with per-layer latency; finalizes on hit/miss |
| `resolve_or_generate(request_id=...)` | Main entry: creates trace with `request_id`; handles waiters (single-flight) with synthetic trace; leader path records L1-L3 via `resolve()`, LLM in `_generate_and_store()` |
| `_generate_and_store()` | Records LLM layer (latency, success) |
| `get_embedding(record_l0b=True)` | Records L0b HIT/MISS (skipped for write paths via `record_l0b=False`) |
| `execute_deterministic()` | Records L0a HIT/MISS |
| Public API | `get_decision_trace(request_id)`, `get_decision_trace_by_id(trace_id)`, `get_decision_traces(tenant_id, limit)`, `get_decision_trace_stats()`, `clear_decision_traces()` |

---

### 4. RAG Pipeline Integration (`ico_cache/rag/pipeline.py`)

| Method | Trace Instrumentation |
|--------|----------------------|
| `retrieve()` | Records L4 HIT (`reuse_source="retrieval_cache"`) or MISS (vector search latency) |
| `generate()` | Records L5 HIT (`reuse_source="context_cache"`) or MISS (construction + store latency) |

Uses `record_layer()` — no-op if no active trace (preserves standalone behavior).

---

### 5. HTTP API (`apps/financial-rag-demo/api/main.py`)

| Endpoint | Description |
|----------|-------------|
| `GET /v1/decision-traces?request_id=...` | Single trace by request ID (tenant-scoped) |
| `GET /v1/decision-traces?trace_id=...` | Single trace by trace ID |
| `GET /v1/decision-traces?limit=10` | Recent traces for authenticated tenant |
| `GET /v1/decision-trace-stats` | Trace store statistics |
| `POST /query` | Now passes `X-Request-ID` header to `resolve_or_generate()` |

---

### 6. Tests Coverage

| Scenario | Test File |
|----------|-----------|
| **Exact hit (L1)** | `test_cache_engine.py::test_resolve_l1_hit`, `test_l1_exact_prompt_match.py` |
| **Semantic hit (L2)** | `test_cache_engine.py::test_resolve_l2_hit_roundtrips_structured_answer`, `test_l1_exact_prompt_match.py` |
| **Context hit (L3)** | `test_cache_engine.py::test_resolve_l3_hit` |
| **Retrieval hit (L4)** | `test_l4_retrieval_cache.py::test_l4_cache_hit_avoids_retrieval` |
| **Context hit (L5)** | `test_l5_context_cache.py::TestL5RAGPipelineIntegration::test_l5_cache_integration` |
| **Complete miss → LLM** | `test_cache_engine.py::test_resolve_miss`, `test_decision_engine.py` |
| **Fallback (gate blocked)** | `test_l1_exact_prompt_match.py` hard gate tests |
| **Concurrent requests** | `test_cache_engine.py::test_single_flight_generates_once`, `test_l1_exact_prompt_match.py::TestL1Concurrency` |
| **Tenant isolation** | `test_cache_engine.py::test_resolve_l1_is_tenant_scoped`, `test_l1_exact_prompt_match.py` |

All 556 existing tests pass — no regressions.

---

## Architecture Notes

### Trace Propagation

Uses `contextvars.ContextVar` (`_active_trace`) so traces flow across module boundaries without threading arguments:
- `resolve_or_generate()` sets trace active
- `resolve()` reuses active trace → records L1/L2/L3
- `_generate_and_store()` reuses active trace → records LLM
- RAG `retrieve()`/`generate()` reuse active trace → records L4/L5
- Waiters create independent traces (each task has its own context copy)

### Single-Flight Waiter Traces

Waiters record synthetic traces:
- L0a-L5: `SKIPPED` with reason "Joined in-flight generation (single-flight dedup)"
- LLM: `ATTEMPTED` with wait latency, metadata `{"single_flight": "waiter"}`
- Outcome: `GENERATE_LLM` (honest — response came from shared LLM call)

### Outcome Derivation Precedence

```python
if final_layer in (L0a, L0b, L1, L2, L3) and hit:  CACHE_RESPONSE
elif L5 hit:                                         REUSE_CONTEXT
elif L4 hit:                                         REUSE_RETRIEVAL
else:                                                GENERATE_LLM
```

---

## Verification

| Check | Result |
|-------|--------|
| Unit/Integration Tests | 556 passed, 10 skipped |
| `ruff check` | Clean on all modified files |
| `mypy` | Success (44 source files) |
| `audit.py --all` | All phases OK (deps, sast, static, ast, secrets) |
| No regressions | All Phase 1-4 behavior preserved |

---

## Files Modified

### New
- `packages/ico-cache-py/src/ico_cache/core/decision_trace.py`

### Modified
- `packages/ico-cache-py/src/ico_cache/__init__.py` (exports)
- `packages/ico-cache-py/src/ico_cache/core/decision_engine.py`
- `packages/ico-cache-py/src/ico_cache/core/cache_engine.py`
- `packages/ico-cache-py/src/ico_cache/rag/pipeline.py`
- `apps/financial-rag-demo/api/main.py` (HTTP endpoints + request_id passthrough)

---

## Future Extensions

- WebSocket streaming of traces for live Dashboard
- Trace export (OpenTelemetry, Jaeger, Zipkin)
- Correlation IDs across microservices
- Trace sampling for high-volume production

---

**Implementation complete.** The Dashboard can now consume decision traces via the HTTP API or Python public API to explain every cache decision.