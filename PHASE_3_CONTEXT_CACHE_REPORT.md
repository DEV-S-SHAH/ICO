# Phase 3 — L5 Context Cache Implementation Report

## Summary

Successfully implemented **L5 Context Cache** for ICO-Cache, caching the assembled
RAG context so that identical retrieval inputs (same chunks, template, budget,
model) can reuse already-constructed context and skip construction work entirely.

L5 sits between L4 Retrieval and the LLM:

```
L0 → L1 → L2 → L3 → L4 Retrieval → L5 Context → LLM
```

The implementation follows the existing architecture (L5 is a Hot Store / exact
match layer, consistent with the pre-existing `get_layer("L5")`/`set_layer("L5")`
routing in `CacheEngine`), maintains full backward compatibility, and adds
complete isolation guarantees plus accounting/observability integration.

---

## Implementation Details

### Files Changed

| File | Description |
|------|-------------|
| `packages/ico-cache-py/src/ico_cache/core/decision_engine.py` | L5 key builder, chunk-content hash, context token estimator, L5 decision evaluation (Step 5) |
| `packages/ico-cache-py/src/ico_cache/core/cache_engine.py` | `get_l5`/`set_l5`/`get_l5_stats` on `CacheEngine` (Hot Store backend) |
| `packages/ico-cache-py/src/ico_cache/rag/pipeline.py` | L5 lookup-before-construction in `generate()`, unified key builder, accounting hooks |
| `packages/ico-cache-py/src/ico_cache/telemetry/accounting.py` | Context construction savings fields + L5 hit/miss counters |
| `packages/ico-cache-py/tests/test_l5_context_cache.py` | Comprehensive test suite (35 tests) |

### L5 Cache Key Schema

The L5 key encodes **all six required isolation dimensions** from
`CRITICAL_FIELDS["L5"]`:

```
v3:{tenant_id}:l5:{sha256(tenant_id:chunks_hash:template_version:token_budget:model_fingerprint:provider)}
```

Key components are derived deterministically:

| Component | Source | Purpose |
|-----------|--------|---------|
| `tenant_id` | Request parameter | Cross-tenant isolation |
| `chunks_hash` | `compute_chunks_hash()` — SHA256[:16] over sorted per-chunk content hashes | Document/chunk content isolation |
| `template_version` | Pipeline config / request param | Prompt template isolation |
| `token_budget` | Pipeline config / request param | Context budget isolation |
| `model_fingerprint` | `CacheEngine._compute_model_fingerprint()` | Model isolation |
| `provider` | Pipeline / engine config | Provider isolation |

`compute_chunks_hash` is order-independent (sorts per-chunk hashes) so identical
chunk sets produce the same key regardless of retrieval ordering, while any change
in chunk content changes the key and auto-invalidates stale context.

### Core Implementation

#### 1. Decision Engine (`decision_engine.py`)

**New module-level utilities:**
- `compute_chunks_hash(chunks)` — deterministic, order-independent hash of
  retrieved chunk contents. Returns `"empty"` for no chunks or no text content.
- `build_l5_key(...)` — v3-schema key with all 6 isolation components.
- `compute_context_tokens(text)` — ~4 chars/token estimation (ceiling).

**`decide()` Step 5:** `_evaluate_l5(ctx)` is invoked last, producing an L5
`LayerEvaluation` entry in `decision.layer_evaluations` (so the full layer chain
L0a/L0b/L1/L2/L3/L5 is visible in every decision).

#### 2. Cache Engine (`cache_engine.py`)

L5 uses the **exact store** (Hot Store), consistent with `get_layer("L5")` routing:

- `get_l5(query, chunks, template_version, token_budget, ...)` → exact-key lookup,
  then a STRICT `hard_gate` defense-in-depth re-verifies the six critical fields
  against the stored metadata before returning the cached context.
- `set_l5(...)` → serializes `{query, context, meta}` under the composite key with
  TTL (reuses `l1_ttl` by default).
- `get_l5_stats()` → `{hits, misses, hit_rate}` observability.
- Hard-gated hit/miss detection: gate failures count as misses (never return
  context whose critical metadata does not match).

> **Design note:** The initial `get_l5/set_l5` Draft used a vector-store collection
> with a dummy-vector filter search. Testing revealed LanceDB ignores
> Qdrant-style filters during flat cosine search, and a zero vector under cosine
> metric returns no rows (NaN distance). Since L5 is a deterministic exact-match
> layer by design (the key encodes all identity), the implementation was corrected
> to use the exact store — matching the architecture's existing Hot Store routing
> and the `RAGPipeline` L5 path.

#### 3. RAG Pipeline (`pipeline.py`)

**Unified key builder:** `_build_l5_key()` now delegates to the shared
`build_l5_key` from `decision_engine` (previously it used a divergent local
format `l5:{tenant}:...`).

**`generate()` context phase reordered:** the L5 lookup now happens **before**
context construction:

- L5 hit → reuse cached context, record `context_cache_hits`,
  `context_construction_tokens_avoided`, `context_construction_latency_saved_ms`;
  construction is genuinely skipped (honest savings accounting).
- L5 miss → construct the context, record `context_cache_misses`,
  `context_construction_latency_ms`, then store in L5 for future reuse.

#### 4. Accounting (`accounting.py`)

Added to `AccountingContext`:
- `context_construction_latency_saved_ms` (was being set by pipeline but did not
  exist — latent AttributeError on L5 hit, now fixed)
- `context_cache_hits`, `context_cache_misses`

#### 5. Test Fix

`tests/test_decision_engine.py::test_decide_returns_full_llm_call_on_empty_cache`
asserted exactly 5 layer evaluations; updated to 6 to include the new L5 entry.

---

## Isolation Guarantees (verified by tests)

| Dimension | Test |
|-----------|------|
| Tenant isolation | `test_l5_tenant_isolation`, `TestL5CollisionResistance` |
| Chunk/content change | `test_l5_chunks_change_invalidates`, `test_different_chunks_hash_produces_different_key` |
| Template version | `test_l5_template_version_isolation`, `test_template_version_change_invalidates` |
| Token budget | `test_l5_token_budget_isolation`, `test_token_budget_change_invalidates` |
| Model fingerprint | `test_l5_model_provider_isolation`, `test_model_change_invalidates` |
| Provider | `test_different_provider_produces_different_key` |
| Hard gates (STRICT + critical fields) | `TestL5HardGates` |

---

## Verification

### Python tests

```
tests/test_l5_context_cache.py .... 35 passed
tests/test_decision_engine.py  ..... 37 passed
tests/test_l4_retrieval_cache.py .... 18 passed
tests/test_l1_exact_prompt_match.py . 47 passed
tests/test_cache_engine.py ......... 15 passed
```

L1/L4 suites (the pre-existing phase boundary suites) remain unchanged and green.

**Full-suite differential:** `test_accounting_*.py` has 74 pre-existing failures
that originate from uncommitted WIP shipped in the working tree (an untracked
`UsageRecord` requires a positional `trace_id` that test factories do not pass;
several test classes reference a missing `_get_metric_value` helper; metric-name
assertions do not match the current `metrics.py`). These were verified **not**
caused by L5:

- With L5 changes: 74 failed / 113 passed in the accounting suites.
- Without L5 changes (stashed L5 source): 78 failed / 109 passed.
- `comm` diff: **0 new failures introduced by L5; 4 accounting tests fixed**.

### Static checks (repo gate)

```
python -m ruff check packages/ico-cache-py/src apps benchmark.py audit.py  → All checks passed!
python -m mypy packages/ico-cache-py/src                                     → Success: no issues found in 38 source files
```

### Audit (`python audit.py --all`)

| Phase | Result |
|-------|--------|
| deps (pip-audit) | ok (0 vulnerabilities) |
| sast (bandit) | ok |
| static (ruff + mypy) | ok |
| ast | ok (0 errors across 39 files) |
| secrets | ok |

---

## Known Issues / Out of Scope

1. **74 pre-existing `test_accounting_*` failures** — inherited from prior
   uncommitted WIP, unrelated to L5 (see differential evidence above). Not
   addressed here to avoid entangling with that in-flight work.
2. **No Gateway/Dashboard/NPX changes** — Phase 3 scope explicitly excludes them.
3. **L5 does not yet participate in `invalidate()` pruning** — TTL-based expiry
   covers staleness; explicit invalidation can be added in a follow-up.