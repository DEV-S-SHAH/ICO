# Verification/Test Requirements for C1-C8 Blocking Conditions

**Objective:** Define test specifications to verify each of the 8 blocking conditions from the Phase 3 Architecture Review is properly implemented before Phase 3A.1 begins.

---

## C1 — Layer Ordering Contradiction Resolved

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 3 (Critical Contradiction between Graph and Algorithm)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C1.1** | `test_decision_engine_layer_sequence_matches_algorithm` | DecisionEngine execution order follows: L0 → L1 → L2 → L3 → L7/L8 → L4 → L5 → L9 → L6 → PARTIAL → FULL (Algorithm authoritative) |
| **C1.2** | `test_layer_order_documented_and_distinguishable` | Three orderings explicitly documented: conceptual (L0-L9), dependency (edges), fallback (execution path) — no ambiguity |
| **C1.3** | `test_fallback_order_on_layer_failure` | When L2 fails, flow proceeds to L3 (not L4); when L4 fails, flow proceeds to L5; when L9 fails, flow proceeds to L6; all layers degrade gracefully to MISS |
| **C1.4** | `test_algorithm_overrides_graph_in_docs` | Architecture documentation Section 2 graph updated to match Section 3 algorithm; visual and textual consistent |

### Key Assertions
- DecisionEngine `decide(ctx)` returns `ReuseDecision` with `layers_checked` array matching algorithm order
- Each layer failure triggers `record_lookup(layer, False, latency)` and continues to next
- No circular dependency: L7/L8 feed L4/L5, not vice versa
- L6 (Partial Recompute) only reached after L9 miss

### New Test File Needed
- `packages/ico-cache-py/tests/test_decision_engine.py` (P0 per Section 9)

---

## C2 — DecisionEngine vs CacheEngine Ownership

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 3 (Ambiguity C) + Section 12 (Must Fix #3)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C2.1** | `test_decision_engine_delegates_to_cache_engine_get_layer_set_layer` | DecisionEngine calls `CacheEngine.get_l1()`, `get_l2()`, `get_l3()`, `set_l1()`, `async_write_l2()`, `async_write_l3()` — never stores data directly |
| **C2.2** | `test_decision_engine_no_cache_storage_logic` | DecisionEngine has no Redis/Qdrant/LanceDB imports; no key generation; no TTL management; no collection setup |
| **C2.3** | `test_cache_engine_resolve_remains_stable_api` | `CacheEngine.resolve(query, context, meta, tenant_id)` signature unchanged; returns `{"source": "L1|L2|L3|MISS", "response": ...}` |
| **C2.4** | `test_single_flight_works_through_decision_engine` | Concurrent `DecisionEngine.decide()` calls for same query+tenant → single `generate_fn` execution; `CacheEngine._inflight` still used |
| **C2.5** | `test_decision_engine_confidence_thresholded_reuse` | `ReuseDecision.confidence` computed from hard gate results + similarity scores; threshold gates reuse |
| **C2.6** | `test_decision_engine_no_circular_dependency` | Import graph: `decision_engine.py` imports `cache_engine`; `cache_engine.py` does NOT import `decision_engine` |

### Key Assertions
- DecisionEngine is a **policy layer** (stateless, configurable thresholds, gate modes)
- CacheEngine is **storage + lookup layer** (stateful, backends, single-flight)
- ADR-002 documents this boundary with interface contract
- `CacheEngine` gets optional `decision_engine: DecisionEngine = None` parameter for injection

### New Test File Needed
- `packages/ico-cache-py/tests/test_decision_engine.py` (P0)

---

## C3 — L0 Split: Deterministic (L0a) + Embedding Cache (L0b)

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 4 (Ambiguity A) + Section 12 (Must Fix #1)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C3.1** | `test_l0a_deterministic_cache_returns_cached_for_same_fn_args_version` | `l0a_cache.get(fn_name, args, fn_version, env_hash)` returns cached result for identical inputs |
| **C3.2** | `test_l0a_invalidates_on_fn_version_change` | Changing `fn_version` → cache miss; old entry not returned |
| **C3.3** | `test_l0a_invalidates_on_env_hash_change` | Changing `env_hash` (e.g., Python version, library version) → cache miss |
| **C3.4** | `test_l0a_confidence_always_1_0` | L0a `ReuseDecision.confidence == 1.0` (mathematically verifiable) |
| **C3.5** | `test_l0a_storage_hot_store_redis_or_sqlite` | L0a entries stored in ExactStore (Redis/SQLite) with key `l0a:{fn_name}:{args_hash}:{fn_version}:{env_hash}` |
| **C3.6** | `test_l0b_embedding_cache_returns_cached_for_same_text_model_version` | `l0b_cache.get(text, model_fingerprint)` returns cached embedding vector |
| **C3.7** | `test_l0b_invalidates_on_model_fingerprint_change` | Changing `model_fingerprint` (e.g., BAAI/bge-small-en-v1.5 → v2.0) → cache miss |
| **C3.8** | `test_l0b_confidence_0_99_model_dependent` | L0b `ReuseDecision.confidence == 0.99` (probabilistic, model-dependent) |
| **C3.9** | `test_l0b_storage_vector_store_lancedb_or_qdrant` | L0b entries stored in VectorStore with key `emb:{model_version}:{text_hash}` |
| **C3.10** | `test_l0a_never_used_for_embedding` | Calling `l0a_cache.get()` with embedding function → TypeError or explicit rejection |
| **C3.11** | `test_l0b_never_used_for_deterministic_functions` | Calling `l0b_cache.get()` with non-embedding function → TypeError or explicit rejection |
| **C3.12** | `test_l0_split_key_formats_documented` | Both key formats in ADR-001; L0a uses ExactStore, L0b uses VectorStore |

### Key Assertions
- `L0aDeterministicCache` class: `get(fn_name, args, fn_version, env_hash)`, `set(fn_name, args, fn_version, env_hash, result)`
- `L0bEmbeddingCache` class: `get(text, model_fingerprint)`, `set(text, model_fingerprint, embedding)`
- Both implement `BaseCacheLayer` interface for DecisionEngine polymorphism
- `BaseEmbedder.model_version` property provides `model_fingerprint` for L0b key

### New Test Files Needed
- `packages/ico-cache-py/tests/test_l0_embedding_cache.py` (P0)
- `packages/ico-cache-py/tests/test_deterministic_cache.py` (P0)

---

## C4 — L1 Key Fix: model_fingerprint, prompt_version, context_hash

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 5 (L1 row HIGH risk) + Section 12 (Must Fix #2)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C4.1** | `test_l1_key_includes_model_fingerprint` | `_l1_key(query, meta, tenant_id)` output includes `model_fingerprint` from metadata or embedder |
| **C4.2** | `test_l1_key_includes_prompt_version` | `_l1_key()` output includes `prompt_version` from metadata |
| **C4.3** | `test_l1_key_includes_context_hash` | `_l1_key()` output includes `context_hash` when context provided |
| **C4.4** | `test_cross_model_hit_blocked` | Same query, different `model_fingerprint` → MISS (not L1 hit) |
| **C4.5** | `test_cross_prompt_version_hit_blocked` | Same query, different `prompt_version` → MISS |
| **C4.6** | `test_cross_context_hit_blocked` | Same query, different `context_hash` → MISS |
| **C4.7** | `test_same_query_model_version_context_hit` | Identical query + model_fingerprint + prompt_version + context_hash → L1 HIT |
| **C4.8** | `test_l1_key_format_matches_documented_contract` | Key format: `{tenant_id}:l1:{sha256(normalized_query|model_fp|prompt_ver|context_hash|meta_suffix)}` documented in ADR-001 |
| **C4.9** | `test_l1_key_backward_compatible_for_same_tenant` | Existing L1 entries without new fields still work (graceful degradation) |

### Key Assertions
- `_l1_key()` signature: `_l1_key(query: str, meta: dict, tenant_id: str, model_fingerprint: str = None, prompt_version: str = None, context_hash: str = None)`
- Metadata extraction: `model_fingerprint` from `meta.get("model_fingerprint")` or `embedder.model_version`
- `prompt_version` from `meta.get("prompt_version")` or template registry
- `context_hash` = `sha256(context)[:16]` when context provided
- Cross-model false hits (P0 bug #5) eliminated

### Existing Test File to Extend
- `packages/ico-cache-py/tests/test_cache_engine.py` — add L1 key tests

---

## C5 — AGGRESSIVE Mode Removed / Restricted

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 6 (Critical Issue) + Section 12 (Must Fix #6)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C5.1** | `test_gate_mode_enum_only_strict_balanced` | `GateMode` enum has exactly `STRICT` and `BALANCED` — no `AGGRESSIVE` |
| **C5.2** | `test_strict_blocks_on_all_critical_fields` | `GateMode.STRICT` + any CRITICAL_FIELD mismatch → `hard_gate()` returns `False` (blocked) |
| **C5.3** | `test_balanced_allows_fuzzy_fields_with_confidence_penalty` | `GateMode.BALANCED` + FUZZY field mismatch → gate passes but `confidence -= penalty` |
| **C5.4** | `test_no_confidence_threshold_bypasses_critical_fields` | Even with `confidence=1.0`, CRITICAL_FIELD mismatch → blocked |
| **C5.5** | `test_tenant_id_gate_never_bypassed_any_mode` | `tenant_id` mismatch → blocked in STRICT, BALANCED, and any future mode |
| **C5.5** | `test_balanced_fuzzy_fields_list` | FUZZY fields: `topic`, `prompt_version`, `tool_version`, `collection_version` (configurable) |
| **C5.6** | `test_balanced_confidence_penalty_accumulates` | Multiple FUZZY mismatches → cumulative penalty; if `confidence < threshold` → blocked |
| **C5.7** | `test_adversarial_near_miss_blocked_in_balanced` | Near-miss queries (entity swap, quarter swap) blocked by CRITICAL gates even in BALANCED |

### Key Assertions
- CRITICAL_FIELDS: `tenant_id`, `model`, `provider`, `model_params`, `prompt_version`, `entity`, `quarter`, `topic`, `collection_version`, `embedding_model_version`, `reranker_version`, `authz_version`, `commit_sha`, `tool_version`, `time_sensitive`
- FUZZY_FIELDS: `topic` (debated), `prompt_version` (debated), `tool_version`, `collection_version`
- `hard_gate(meta_in, meta_cached, filter_keys, gate_mode=GateMode.STRICT)` signature
- BALANCED mode: opt-in per-tenant with audit log entry

### Existing Test File to Extend
- `packages/ico-cache-py/tests/test_hard_gates_extended.py` (NEW P0 file per Section 9)

---

## C6 — Tenant Isolation L7/L8/L9

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 5 (L7/L8/L9 rows CRITICAL/HIGH) + Section 8 (Security Review) + Section 12 (Must Fix #5)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C6.1** | `test_l7_project_id_includes_tenant_id` | `project_id = hash(tenant_id + repo_url + branch)` — cross-tenant same repo = different project_id |
| **C6.2** | `test_l7_write_requires_tenant_authorization` | `L7ProjectMemory.write(tenant_id, project_id, data)` validates `tenant_id` owns `project_id` |
| **C6.3** | `test_l7_read_requires_tenant_authorization` | `L7ProjectMemory.read(tenant_id, project_id)` returns MISS if tenant mismatch |
| **C6.4** | `test_l7_cross_tenant_same_repo_different_project_id` | Tenant A + repo X → project_id_A; Tenant B + repo X → project_id_B; A cannot read B's project |
| **C6.5** | `test_l8_key_includes_tenant_id_user_id_session_id` | L8 key: `session:{tenant_id}:{user_id}:{session_id}` |
| **C6.6** | `test_l8_cross_tenant_access_returns_miss` | Tenant A session data not accessible to Tenant B |
| **C6.7** | `test_l9_key_includes_tenant_id` | L9 key: `llm:{tenant_id}:{full_prompt_hash}:{model_fp}:{provider}:{params_hash}:{prompt_ver}` |
| **C6.8** | `test_l9_cross_tenant_access_returns_miss` | Tenant A LLM response not served to Tenant B |
| **C6.9** | `test_l8_to_l9_different_injected_context_different_l9_entry` | Same query, different L8 injected context → different `injected_context_hash` → different L9 key |
| **C6.10** | `test_l9_personalized_includes_user_session` | When `personalized=True`, L9 key includes `user_id` + `session_id` |

### Key Assertions
- All L7/L8/L9 keys start with `tenant_id:` prefix
- Tenant authorization check at storage abstraction layer (not just application layer)
- `L8SessionMemory` consent model: `user_id` must consent to `session_id` data storage
- L9 `personalized` flag controls user/session inclusion

### New Test Files Needed
- `packages/ico-cache-py/tests/test_l7_project_memory.py` (P1)
- `packages/ico-cache-py/tests/test_l8_session_memory.py` (P1)
- `packages/ico-cache-py/tests/test_l9_llm_response_cache.py` (P0)

---

## C7 — Storage Abstraction Layer

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 3 (Storage Abstraction ❌ Missing) + Section 12 (Must Fix #7)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C7.1** | `test_hot_store_interface_redis_backend` | `HotStore` (ExactStore) works with `RedisStore` — `get/set/delete_prefix` |
| **C7.2** | `test_hot_store_interface_sqlite_backend` | `HotStore` works with `SQLiteStore` — same API |
| **C7.3** | `test_vector_store_interface_qdrant_backend` | `VectorStore` works with `QdrantStore` — `create_collection/search/insert/delete_matching` |
| **C7.4** | `test_vector_store_interface_lancedb_backend` | `VectorStore` works with `LanceDBStore` — same API |
| **C7.5** | `test_durable_store_interface_sqlite_backend` | `DurableStore` (new) works with `SQLiteStore` — relational metadata, project memory |
| **C7.6** | `test_durable_store_interface_postgresql_backend` | `DurableStore` works with `PostgreSQLStore` — same API |
| **C7.7** | `test_layer_to_abstraction_mapping_correct` | L1→HotStore, L2→VectorStore, L3→VectorStore, L4→VectorStore, L5→VectorStore, L7-meta→DurableStore, L8→HotStore (session), L9→HotStore |
| **C7.8** | `test_tenant_isolation_at_abstraction_level` | All stores enforce tenant isolation: HotStore keys prefixed, VectorStore collections scoped, DurableStore tables partitioned |
| **C7.9** | `test_storage_factory_creates_correct_backend` | `StorageFactory.create(config)` returns correct implementation based on config |
| **C7.10** | `test_no_direct_backend_imports_in_cache_engine` | `cache_engine.py` imports only `BaseExactStore`, `BaseVectorStore`, `BaseDurableStore` — not concrete classes |

### Key Assertions
- `backends/base.py` defines: `BaseExactStore` (HotStore), `BaseVectorStore`, `BaseDurableStore` (NEW)
- `BaseEmbedder` v2 adds `model_version` property
- All layer implementations use abstraction interfaces
- Configuration-driven backend selection (env var or config file)
- Tenant isolation implemented at each abstraction level

### New Test Files Needed
- `packages/ico-cache-py/tests/test_storage_abstraction.py` (P0)

---

## C8 — Migration Strategy 2.x → 3.0

**Source:** PHASE3_ARCHITECTURE_REVIEW.md Section 12 (Must Fix #8)

### Test Requirements

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| **C8.1** | `test_2x_cache_entries_purged_on_upgrade` | Upgrade script/migration purges all L1/L2/L3 entries from 2.x format |
| **C8.2** | `test_feature_flags_control_layer_enablement` | Feature flags: `enable_l0`, `enable_l4`, `enable_l5`, `enable_l7`, `enable_l8`, `enable_l9` — each independently toggleable |
| **C8.3** | `test_legacy_v1_query_endpoint_works_30_days` | `/v1/query` endpoint returns 200 with deprecation header for 30 days post-release |
| **C8.4** | `test_canary_rollout_with_measurable_gates` | Canary: 5% traffic → 25% → 50% → 100%; gates: false-hit rate 0%, latency p99 < baseline, error rate < 0.1% |
| **C8.5** | `test_rollback_via_feature_flag_flip` | Flipping `enable_l4=false` immediately disables L4 without restart; no data corruption |
| **C8.6** | `test_migration_guide_document_exists` | `MIGRATION.md` with step-by-step: purge, config changes, feature flags, validation |
| **C8.7** | `test_version_sync_py_js_enforced` | `test_version_sync.py` passes — Python and JS SDK versions match |
| **C8.8** | `test_2x_client_compatibility` | 2.x Python client (`ico_cache.Client`) works against 3.0 server for 30 days (deprecated path) |

### Key Assertions
- Migration is **additive**: new layers opt-in via feature flags
- 2.x cache format incompatible → full purge required (documented)
- Legacy endpoint: `/v1/query` proxies to new DecisionEngine with STRICT mode
- Canary metrics collected via Prometheus: `cache_false_hit_rate`, `cache_latency_p99`, `cache_error_rate`
- Rollback tested in CI: enable flag → run tests → disable flag → verify clean state

### New Test Files Needed
- `packages/ico-cache-py/tests/test_migration.py` (P1)
- `packages/ico-cache-py/tests/test_feature_flags.py` (P1)

---

## Summary: New Test Files Required (15+ from Section 9)

| Priority | File | Covers |
|----------|------|--------|
| P0 | `test_decision_engine.py` | C1, C2 |
| P0 | `test_hard_gates_extended.py` | C5 |
| P0 | `test_l0_embedding_cache.py` | C3 (L0b) |
| P0 | `test_deterministic_cache.py` | C3 (L0a) |
| P0 | `test_l4_retrieval_cache.py` | L4 (future) |
| P0 | `test_l5_context_window_cache.py` | L5 (future) |
| P0 | `test_l9_llm_response_cache.py` | C6 (L9) |
| P1 | `test_l7_project_memory.py` | C6 (L7) |
| P1 | `test_l8_session_memory.py` | C6 (L8) |
| P1 | `test_l6_tool_cache.py` | L6 (future) |
| P1 | `test_partial_recompute.py` | L6 (future) |
| P1 | `test_adversarial_l4_l5.py` | L4/L5 (future) |
| P1 | `test_adversarial_l7_l8.py` | C6 (L7/L8) |
| P1 | `test_adversarial_l9.py` | C6 (L9) |
| P1 | `test_adversarial_cross_layer.py` | C1, C2 |
| P2 | `test_invalidation_extended.py` | C3, C7 |
| P2 | `test_degraded_partial_failure.py` | C1, C2 |
| P2 | `test_cache_poisoning.py` | C5, C6 |
| P0 | `test_storage_abstraction.py` | C7 |
| P1 | `test_migration.py` | C8 |
| P1 | `test_feature_flags.py` | C8 |

---

## Integration Test Scenarios (Cross-Layer)

| Scenario | Layers Involved | Verification |
|----------|-----------------|--------------|
| **S1: Full Pipeline Hit** | L0a → L1 → L2 → L3 → L7 → L4 → L5 → L9 | Query hits at L1; all downstream layers skipped; metrics recorded per layer |
| **S2: L0a Hit → Skip Embedding** | L0a | Deterministic function cached; embedder not called; `embedding_calls_avoided++` |
| **S3: L0b Hit → Skip Embedding** | L0b | Same text + model_fingerprint → cached embedding; `embedding_calls_avoided++` |
| **S4: L2 Miss → L3 Hit with Context** | L1→L2→L3 | Context-aware hit; hard gate passes on merged metadata |
| **S5: L4 Retrieval Cache Hit** | L7→L4 | Project memory provides context; retrieval cached with corpus version |
| **S6: L5 Context Window Reuse** | L4→L5 | Same chunks + template + token budget → cached context window |
| **S7: L9 Response Cache Hit (temp=0)** | L1→L2→L3→L7→L4→L5→L9 | Deterministic LLM response cached; model_fingerprint + prompt_version in key |
| **S8: Cross-Tenant Isolation** | L1/L2/L3/L7/L8/L9 | Tenant A data never returned to Tenant B at any layer |
| **S9: Invalidation Cascade** | L4→L5 | Corpus version bump → L4 invalidated → L5 entries with old chunk hashes invalidated |
| **S10: Degraded Mode** | All | L2 backend down → falls through to L3 → L7 → L4 → L5 → L9 → L6 → FULL; no exceptions |

---

## CI/CD Requirements

### Benchmark Gates (from Section 10)

```yaml
# .github/workflows/benchmark.yml
regression_thresholds:
  tokens_saved_pct: -5%           # No more than 5% token increase vs baseline
  cost_saved_pct: -5%
  latency_reduction_pct: -10%
  hit_rate_l1_delta: -0.02        # No more than 2pp hit rate drop
  hit_rate_l2_delta: -0.02
  hit_rate_l3_delta: -0.02
  quality_delta: -0.01            # Quality score drop < 1pp
  false_hit_rate: 0               # Zero tolerance for false hits
```

### Required CI Pipeline

1. **Unit Tests** (every PR): `pytest packages/ico-cache-py/tests/ -q --tb=short`
2. **Integration Tests** (every PR): `pytest packages/ico-cache-py/tests/test_decision_engine.py packages/ico-cache-py/tests/test_l0_embedding_cache.py ... -v`
3. **Adversarial Evaluation** (every PR): `python eval_harness.py --loader-type mixed --eval-adversarial`
4. **Benchmark Regression** (nightly + release): `python benchmark.py --dataset all --backend embedded` → compare with baseline artifact
5. **Cross-Platform** (release): Linux (CI), macOS (local), Windows (CI runner)
6. **Security Audit** (every PR): `python audit.py --all`
7. **Type/Lint** (every PR): `ruff check` + `mypy`

### Benchmark Infrastructure Updates Needed

| Component | Requirement |
|-----------|-------------|
| `benchmark.py` | Add `--mode baseline|optimized` flag for WITH/WITHOUT comparison |
| `workload_generators.py` | New file: chatbot/coding_agent/rag/multi_agent workloads (10k queries each) |
| Golden Set | Deterministic Q&A pairs with expected answers for correctness validation |
| LLM Judge | Equivalence checker for response quality (semantic similarity > 0.95) |
| Provider Pricing | Configurable registry: `pricing.yaml` with per-model token costs |
| CI Script | `scripts/compare_benchmarks.py` — fails PR if any metric regresses beyond threshold |
| Baseline Storage | `benchmark-reports/main/` — main branch reports as reference artifacts |

---

## Test Implementation Order (Dependency-Aware)

```
Phase 1 (Foundation - C1, C2, C3, C7):
├── test_decision_engine.py          ← C1, C2
├── test_hard_gates_extended.py      ← C5
├── test_l0_embedding_cache.py       ← C3 (L0b)
├── test_deterministic_cache.py      ← C3 (L0a)
├── test_storage_abstraction.py      ← C7

Phase 2 (Layer Fixes - C4, C6):
├── Extend test_cache_engine.py      ← C4 (L1 key)
├── test_l7_project_memory.py        ← C6
├── test_l8_session_memory.py        ← C6
├── test_l9_llm_response_cache.py    ← C6

Phase 3 (Adversarial/Integration - C1, C2, C6):
├── test_adversarial_cross_layer.py  ← C1, C2, C6
├── test_adversarial_l7_l8.py        ← C6
├── test_adversarial_l9.py           ← C6
├── test_invalidation_extended.py    ← C3, C7
├── test_degraded_partial_failure.py ← C1, C2

Phase 4 (Migration - C8):
├── test_feature_flags.py            ← C8
├── test_migration.py                ← C8

Phase 5 (Future Layers - Deferred to Phase 4):
├── test_l4_retrieval_cache.py
├── test_l5_context_window_cache.py
├── test_l6_tool_cache.py
├── test_partial_recompute.py
├── test_adversarial_l4_l5.py
├── test_cache_poisoning.py
```

---

## Validation Checklist Before Phase 3A.1 Start

- [ ] All 8 CONDITIONAL PASS conditions have corresponding test files created
- [ ] Each test file has ≥5 test cases covering happy path + edge cases + adversarial
- [ ] `pytest packages/ico-cache-py/tests/ -q` passes with zero failures
- [ ] `python eval_harness.py --loader-type mixed --eval-adversarial` passes (0 false hits)
- [ ] `python benchmark.py --dataset all --backend embedded` produces valid JSON report
- [ ] Cross-platform test run passes (Linux CI + macOS local + Windows CI)
- [ ] Security audit `python audit.py --all` passes
- [ ] Type check `mypy packages/ico-cache-py/src` passes
- [ ] Lint `ruff check packages/ico-cache-py/src` passes
- [ ] Version sync `pytest packages/ico-cache-py/tests/test_version_sync.py` passes
- [ ] ADR-001 through ADR-010 committed with decisions (not proposals)
- [ ] `MIGRATION.md` exists with purge + feature flag + rollback procedures