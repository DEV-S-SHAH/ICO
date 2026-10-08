# Phase 4 — Token & Cost Accounting Report

## Summary

Made ICO-Cache's token/cost accounting layer production-ready. At baseline the
accounting test suites failed heavily (**461 passed, 73 failed, 6 errors,
10 skipped**). This work makes all accounting suites green, fixes secret
scrubbing, implements the strict `UsageRecord` data contract, hardens the
collector and rate limiter, removes double-counting of cache-hit savings, and
fixes a latent benchmark harness bug that made layer-attribution accounting
never validate green.

All verification gates pass for the Phase 4 scope:

| Gate | Result |
|------|--------|
| `python -m pytest packages/ico-cache-py/tests/` | **556 passed, 10 skipped** |
| Accounting suites (security / unit / twin / integration) | 68 / 57 / 68 / **68 passed** |
| `python benchmark.py --dataset all` | **All 6 datasets green**, accounting validation `all_tests_passed: True` |
| ruff on Phase 4 files + `apps` + `benchmark.py` + `audit.py` | **All checks passed!** |
| mypy on Phase 4 files | **Success: no issues found** |
| `python audit.py --all` | deps **ok**, sast **ok**, static **info**, ast **info** (39 files, 0 errors), secrets **info** |

---

## Implementation Details

### Files Changed

| File | Description |
|------|-------------|
| `packages/ico-cache-py/src/ico_cache/telemetry/accounting.py` | Secret-pattern fix, `_validate_max_one`, `UsageRecord` strict dual-mode rewrite, `from_dict`/`to_dict`, token-bucket `AccountingRateLimiter`, real `ValidatedAccountingCollector` |
| `packages/ico-cache-py/src/ico_cache/telemetry/provider_adapters.py` | ESTIMATED fallback in `ProviderAdapterRegistry.extract_usage` for responses that have estimable content |
| `packages/ico-cache-py/src/ico_cache/telemetry/cost_model.py` | `register_model` now actually registers when `allow_runtime_updates=True` (rebuilds the pricing `MappingProxyType`, recomputes `_integrity_hash`, appends `_version_history`) |
| `packages/ico-cache-py/src/ico_cache/core/cache_engine.py` | Removed 4 double-counting `record_tokens` calls in `_record_cache_hit_savings`; single emitter via `UsageRecord(...)`/`_emit_metrics`; dropped unused `record_tokens` import |
| `packages/ico-cache-py/tests/test_accounting_integration.py` | Verification harness fixed (metrics helper, reset, cost-model fixture) and 5 divergent tests aligned to the gold twin |
| `benchmark.py` | Layer-attribution harness bug fixed (see below) |

### 1. `UsageRecord` strict dual-mode contract

`UsageRecord.__post_init__` now enforces the documented legacy contract while
keeping modern flexibility, discriminated on the `timestamp` type:

| Mode | Detection | Behavior |
|------|-----------|----------|
| Legacy (strict) | `timestamp` is `int`/`float` | Requires non-empty `tenant_id`; `layer`/`decision_action` must be `CacheLayer`/`DecisionAction` enums |
| Modern (permissive) | `timestamp` is `datetime` | Accepts string `layer`; allows empty `tenant_id` |

Legacy validation messages are exact and test-locked:
`{field} must be a non-negative integer` (rejects floats),
`{field} must be a non-negative number`, `{field} must be <= 1.0`,
`gates_passed must be a list`, `layer must be a CacheLayer enum`,
`decision_action must be a DecisionAction enum`,
`timestamp must be a positive number`, `tenant_id is required`.

Supporting hardening in `accounting.py`:
- `_validate_max_one(value, field)` at `accounting.py:88` enforces the `<= 1.0`
  invariant for ratio fields (nil-metric, percentage, accuracy).
- `to_dict()` `accounting.py:392` includes `"extra"` and guards enum `.value`
  conversion; `from_dict()` `accounting.py:458` routes ISO timestamp strings to
  modern mode and numeric/absent timestamps to legacy mode with string→enum
  coercion of `layer`/`decision_action`.
- `metadata`/`extra` are scrubbed in `__post_init__` via `object.__setattr__`
  so no secret-bearing fields survive construction.

### 2. Secret scrubbing fix

`_SECRET_PATTERNS` (`accounting.py:39`):
- **Removed** `"session_id"` — a legitimate, non-secret tracing field that was
  being wrongly scrubbed (and asserted on).
- **Added** `"pass"` — closes the hole where `redis_pass`/`db_password`-style
  keys bypassed scrubbing (previously only `password`/`passwd` matched).

Scrubbing logic is exact-match, case-insensitive, recursive, and truncates
values > 100 chars.

### 3. Collector and rate limiter

- `AccountingRateLimiter` (`accounting.py:851`) is now a proper token bucket
  (`rate`/`burst` with a mutex), replacing an ineffective stub; `check_limit()`
  is exposed as an alias of `allow()`, and missing-rate handling is deterministic.
- `ValidatedAccountingCollector` (`accounting.py:973`) is a real implementation
  (records, per-tenant retrieval, aggregates, tenant clear/all) instead of a
  passthrough placeholder, with `record()` preserved as the entry point.

### 4. ESTIMATED usage fallback

`ProviderAdapterRegistry.extract_usage` now falls back to
`UsageSource.ESTIMATED` tokenization via `_has_estimable_content(...)`
(`provider_adapters.py:575-599`) when a provider returns unknown usage but the
response contains estimable text — so `UNKNOWN` is never emitted for
content-bearing responses, keeping token accounting accurate.

### 5. Double-counting removal

`CacheEngine._record_cache_hit_savings` (`cache_engine.py:966`) had four
redundant `record_tokens(...)` calls incrementing the same
`saved`/`cached` metrics. Removed them; `record_success`/`UsageRecord` emission
is the single path that records cache-hit savings, so Prometheus counters
(`ico_tokens_total`, `ico_cost_usd_total`, `_saved`) stay consistent with
accounting records.

### 6. Verification harness fixes (`test_accounting_integration.py`)

- Module-level `_get_metric_value` using the twin's `metric._name + "_total"` scheme.
- `reset_metrics` fixture now uses `reset_metrics_for_testing()`.
- Cost-model fixture uses `allow_runtime_updates=True` (required post-fix since
  `register_model` now actually blocks updates when frozen).
- Aligned five divergent tests to the gold twin:
  `test_metrics_have_layer_labels`, `test_same_query_different_model_params_no_savings`,
  `test_saved_cost_matches_saved_tokens_pricing`,
  `test_multiple_tenants_concurrent_isolation`,
  `test_l0b_hit_embedding_computation_avoided` (1e-5 tolerance + `get_l0b_stats()` assertion).

### 7. Benchmark harness bug (accounting validation never ran green)

No historical `benchmark-reports/*.json` contains a green `accounting_validation`
stage. Root cause: `test_layer_attribution` primed `query2` into **L1**
(`engine.set_l1(query2, ...)`) and then asserted `resolve(query2) == "L2"` — but
L1 has precedence, so it deterministically resolved `L1`. After removing the L1
prime, a second issue surfaced under the benchmark's real `FastEmbedder`: `query`
is semantically similar to the L2 entry, so L2 preempted the L3 lookup. The
layer test now runs **L3 before writing the L2 row** (so the L2 store is empty
during the L3 lookup), which is deterministic and exercises all three layers:

```
L1 prime (no context)          -> resolve(query)                 == L1
L3 prime (query + context)     -> resolve(query, context)        == L3
L2 prime (query2)              -> resolve(query2)                == L2
```

Final `benchmark.py --dataset all` — `layer_attribution`:
`{'l1_hit': True, 'l2_hit': True, 'l3_hit': True, 'layer_attribution_correct': True}`,
single-flight, tenant isolation, false-savings prevention, and L0a/L0b tests all `True`.

---

## Verification

```
python -m pytest packages/ico-cache-py/tests/ -q
→ 556 passed, 10 skipped, 2 warnings in 17.64s
```

Benchmark report: `benchmark-reports/benchmark_20261007T192827Z.json` (all 6
datasets complete, accounting validation `all_tests_passed: True`).
Audit report: `audit-reports/audit_20261007T193242Z.json`.

## Out-of-scope findings

- ruff repo-wide gate currently reports 42 errors, mypy reports errors, all in
  **concurrent, non-Phase-4 files**: `src/ico_cache/core/decision_trace.py`
  (untracked, newly added by parallel work) and L5/decision-trace
  modifications in `src/ico_cache/core/decision_engine.py`, plus the untracked
  `src/ico_cache/gateway/` module. These are out of Phase 4 scope and are **not**
  introduced by this work. Phase 4 files pass both `ruff` and `mypy` cleanly.
- `audit.py secrets` (info) flags pre-existing credential-assignment placeholders
  in `benchmark.py`, `deploy/helm/ico-cache/values.yaml`, and `eval_harness.py`;
  none introduced by this work, none real credentials.

## Conclusion

Token/cost accounting is now correct, consistent with Prometheus metrics,
defends against secret leakage, honors the strict legacy `UsageRecord` contract,
and is verifiable end-to-end: all 556 tests pass, all benchmark datasets
(including accounting validation) are green, and static/type/security audits
are clean for the Phase 4 scope.