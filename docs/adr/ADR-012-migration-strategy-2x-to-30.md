# ADR-012: 2.x → 3.0 Migration Strategy

**Status**: ACCEPTED  
**Date**: 2026-10-06  
**Deciders**: Architect, Integration Engineer, Cache Engineer  
**Reviewers**: Security Engineer, Observability Engineer, Testing Engineer

## Context

ICO-Cache 2.x provides a 3-tier semantic cache (L1/L2/L3) with hard gates. Phase 3 introduces a 10-layer intelligent optimization layer (L0-L9) with Decision Engine, project/session memory, and new integration patterns. This ADR defines the migration strategy for existing 2.x users.

**Critical Finding**: **Existing 2.x cache entries CANNOT be safely reused in 3.0.** The cache key formats have fundamentally changed to include mandatory fields (model_fingerprint, provider, prompt_version, collection_version, tenant_id in all keys) that were absent in 2.x. Attempting to read 2.x entries with 3.0 keys will result in cache misses (safe), but any 2.x entries that somehow match new keys would violate correctness guarantees (unsafe).

## Decision

**Clean-break migration with explicit invalidation.** All 2.x cache data must be purged on upgrade. No automatic migration of cached entries.

## Migration Dimensions

### 1. API Compatibility

| 2.x API | 3.0 Status | Migration Path |
|---------|------------|----------------|
| `CacheEngine.embedded()` | ✅ Preserved | Zero-code change for embedded mode |
| `CacheEngine.resolve()` | ✅ Preserved (legacy path) | Works unchanged; uses sequential L1→L2→L3 |
| `CacheEngine.resolve_or_generate()` | ✅ Preserved (legacy path) | Works unchanged |
| `CacheEngine.invalidate()` | ✅ Preserved | Works unchanged for L1/L2/L3 |
| `CacheEngine.get_metrics()` | ✅ Preserved | Returns legacy stats + new fields |
| **New: `DecisionEngine.decide()`** | 🆕 Added | Opt-in for Phase 3 capabilities |
| **New: `cache.optimize()` (SDK)** | 🆕 Added | High-level API for new integrations |

**Policy**: 2.x APIs are **frozen but supported** for the 3.x lifecycle. No deprecation until 4.0.

### 2. Cache-Key Compatibility

| Layer | 2.x Key Format | 3.0 Key Format | Compatible? |
|-------|----------------|----------------|-------------|
| L1 | `tenant:l1:sha256(norm(query) + canon_meta)` | `tenant:l1:sha256(norm(query) + canon_meta + model_fp + prompt_ver + context_hash)` | ❌ No |
| L2 | Vector search with `meta` filter | Vector search with `meta` filter + `model_fp` + `embedding_model_ver` + `collection_ver` | ❌ No |
| L3 | Dual-vector with merged meta | Dual-vector with merged meta + `model_fp` + `embedding_model_ver` + `collection_ver` | ❌ No |
| L0, L4-L9 | N/A | New layers | N/A |

**Reason for incompatibility**: 
- 2.x keys lack `model_fingerprint` → cross-model false hits (P0 security bug)
- 2.x keys lack `prompt_version` → template changes don't invalidate
- 2.x keys lack `collection_version` → corpus changes don't invalidate
- 2.x L7/L8/L9 keys lack `tenant_id` → cross-tenant leakage (CRITICAL security)

**Action**: On 3.0 startup, **all 2.x cache entries MUST be purged**. This is enforced by the migration script.

### 3. Existing Cached Data

**All 2.x cache data is discarded on upgrade.**

| Data Type | 2.x Location | 3.0 Action |
|-----------|--------------|------------|
| L1 exact cache | Redis keys `tenant:l1:*` / SQLite `cache` table | `DELETE` / `DROP TABLE` |
| L2 vector cache | Qdrant collection `tenant_l2_cache` / LanceDB table | `DELETE COLLECTION` / `DROP TABLE` |
| L3 vector cache | Qdrant collection `tenant_l3_cache` / LanceDB table | `DELETE COLLECTION` / `DROP TABLE` |
| RAG corpus | Qdrant collection `tenant_ico_corpus` / LanceDB table | **PRESERVED** (not cache — source of truth) |
| Ingestion state | SQLite / Redis queues | **PRESERVED** (job metadata) |

**Rationale**: The correctness risk of stale 2.x entries (model mismatch, tenant leakage, missing version gates) far exceeds the performance cost of cold-start rebuild. Re-population happens naturally within hours at typical traffic.

### 4. Configuration Compatibility

| 2.x Config | 3.0 Status | Notes |
|------------|------------|-------|
| `thresh_semantic` | ✅ Preserved | Maps to `DecisionEngine.policy.threshold` |
| `thresh_ctx_q`, `thresh_ctx_c` | ✅ Preserved | Legacy L3 thresholds |
| `adaptive_threshold` | ⚠️ Deprecated | Replaced by `ReusePolicy` (STRICT/BALANCED) |
| `l1_ttl` | ✅ Preserved | L1 TTL unchanged |
| `tenant_isolation_mode` | ✅ Preserved | `collection` (default) / `payload` |
| `metadata_filter_keys` | ✅ Preserved | Extended with CRITICAL_FIELDS |
| **New: `reuse_policy`** | 🆕 Required | `STRICT` (0.95), `BALANCED` (0.80), `AGGRESSIVE` (0.65, opt-in only) |
| **New: `model_fingerprint`** | 🆕 Required | Auto-detected from `provider:model` |
| **New: `prompt_version`** | 🆕 Required | Defaults to `v1` if not set |

**Migration**: 2.x config dict passes to 3.0 `CacheEngine` constructor unchanged. New fields have safe defaults.

### 5. Storage Migration

| Storage System | 2.x Use | 3.0 Use | Migration Action |
|----------------|---------|---------|------------------|
| Redis | L1, invalidation streams | L0, L1, L4, L5, L6, L8, L9, invalidation streams | **FLUSHDB** on upgrade (cache only); streams recreated |
| SQLite | L1 (embedded) | L1 (embedded), Project metadata (L7) | **DROP cache table**; new `project_memory` tables created |
| Qdrant | L2, L3, RAG corpus | L2, L3, RAG corpus | **DELETE l2_cache, l3_cache collections**; corpus preserved |
| LanceDB | L2, L3, RAG corpus (embedded) | L2, L3, RAG corpus, L7 vectors (embedded) | **DROP l2_cache, l3_cache tables**; corpus & new L7 tables created |
| **PostgreSQL** | ❌ Not used | L7 metadata (distributed), Project metadata | **NEW** — provision for distributed deployments |

**Embedded mode**: `CacheEngine.embedded()` handles schema migration automatically on first init.

**Distributed mode**: Run `ico-cache migrate storage` CLI command (provided in 3.0) which:
1. Flushes Redis cache keys (preserves streams config)
2. Drops Qdrant `*_l2_cache`, `*_l3_cache` collections
3. Creates new collections with updated schemas
4. Initializes PostgreSQL schema for L7 (if configured)

### 6. SDK Compatibility

| SDK | 2.x Status | 3.0 Status | Migration |
|-----|------------|------------|-----------|
| **Python SDK** (`ico_cache`) | `CacheEngine` class | `CacheEngine` + `ICOCache` (high-level) + `DecisionEngine` | `pip install -U ico-cache` — zero breaking changes |
| **JS/TS SDK** (`ico-cache-js`) | Thin HTTP wrapper | Full parity with Python + `optimize()` | `npm update ico-cache-js` — new methods added, none removed |
| **REST API** | `/resolve`, `/ingest`, `/invalidate`, `/stats` | Same endpoints + `/decide`, `/optimize`, `/project-memory`, `/session` | API versioned via `Accept: application/vnd.ico-cache.v3+json` |

**Version Header Strategy**:
```
# 2.x clients (unchanged)
GET /resolve → routes to legacy CacheEngine.resolve()

# 3.0 clients
Accept: application/vnd.ico-cache.v3+json
POST /decide → routes to DecisionEngine.decide()
POST /optimize → routes to high-level optimize()
```

### 7. Tenant Behavior

| Aspect | 2.x | 3.0 | Migration Impact |
|--------|-----|-----|------------------|
| Tenant isolation | Collection or payload | Collection (default) + payload | Unchanged |
| Tenant ID in keys | L1/L2/L3 only | **All layers (L0-L9)** | **Breaking** — requires cache purge |
| Cross-tenant leakage risk | Low (collection mode) | **Zero** (tenant_id in every key) | Improved |
| AuthZ versioning | ❌ Not implemented | `authz_version` in all keys | New — auto-populated from auth middleware |

**No tenant action required** — purge handles key format change.

### 8. Rollout / Rollback Strategy

#### Rollout (Blue/Green or Canary)

```
Phase 1: Deploy 3.0 alongside 2.x (separate cache namespaces)
         - New Redis DB index (e.g., db=1 vs db=0)
         - New Qdrant collections (prefixed `v3_`)
         - Run shadow traffic: mirror requests to 3.0, compare decisions
         
Phase 2: Canary 5% → 25% → 50% → 100%
         - Feature flag: `ICO_CACHE_VERSION=3.0`
         - Monitor: false hit rate, latency, hit rate, cost
         
Phase 3: Full cutover
         - Switch default to 3.0
         - Run migration script to purge 2.x cache
         - Decommission 2.x cache namespaces
```

#### Rollback Plan

| Trigger | Action | Time |
|---------|--------|------|
| False hit rate > 0.1% | Flip feature flag to 2.x | < 30 sec |
| Latency p99 > 2x baseline | Flip feature flag to 2.x | < 30 sec |
| Data corruption detected | Flip feature flag + restore Redis/Qdrant from backup | < 5 min |
| Critical bug in DecisionEngine | Disable DecisionEngine, fall back to `CacheEngine.resolve()` | < 1 min |

**Rollback is instant** because 2.x cache namespaces are preserved during canary. The migration script (purge) only runs after 100% cutover with 24h stability.

### 9. Feature Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `ICO_CACHE_VERSION` | `2.x` | Global version selector |
| `ICO_ENABLE_DECISION_ENGINE` | `false` | Enable DecisionEngine path |
| `ICO_ENABLE_L0_EMBEDDING_CACHE` | `false` | Enable L0 embedding cache |
| `ICO_ENABLE_L4_RETRIEVAL_CACHE` | `false` | Enable L4 retrieval cache |
| `ICO_ENABLE_L5_CONTEXT_CACHE` | `false` | Enable L5 context window cache |
| `ICO_ENABLE_L7_PROJECT_MEMORY` | `false` | Enable L7 project memory |
| `ICO_ENABLE_L8_SESSION_MEMORY` | `false` | Enable L8 session memory |
| `ICO_ENABLE_L9_RESPONSE_CACHE` | `false` | Enable L9 response cache |
| `ICO_REUSE_POLICY` | `BALANCED` | STRICT / BALANCED / AGGRESSIVE (opt-in) |
| `ICO_ENABLE_AGGRESSIVE_MODE` | `false` | Allow AGGRESSIVE policy (audit required) |

**All Phase 3 layers default OFF**. Enable incrementally per workload.

### 10. Versioning

| Scheme | Format | Example |
|--------|--------|---------|
| **Library version** | SemVer | `3.0.0`, `3.1.0`, `3.0.1` |
| **Cache schema version** | Integer in key prefix | `v3:tenant:l1:...` |
| **Collection version** | Integer per tenant | `collection_version: 7` (auto-increment on ingest) |
| **Prompt template version** | SemVer or content hash | `v2.1.0` or `sha256:abc123` |
| **Embedding model version** | From `BaseEmbedder.model_version` | `BAAI/bge-small-en-v1.5@1.0.0` |

**Cache key prefix**: All 3.0 keys prefixed with `v3:` to coexist with 2.x during canary.

### 11. Cache Invalidation During Migration

| Scenario | Action |
|----------|--------|
| **Canary phase** | 2.x and 3.0 caches isolated (different Redis DB / Qdrant collections). No cross-invalidation needed. |
| **Cutover** | Run `ico-cache migrate purge-2x-cache` — deletes all 2.x keys/collections. |
| **Post-cutover** | 3.0 invalidation works normally via Redis Streams. |
| **Rollback** | 2.x cache namespaces intact — traffic resumes with cold 2.x cache (acceptable). |

### 12. Schema Versioning

```python
# In cache key: v3:{tenant}:{layer}:{schema_version}:{payload_hash}
# Schema version increments when key format changes incompatibly

CACHE_SCHEMA_VERSION = 3  # 3.0 launch
# Future: 4 = key format change requiring purge
```

**Version check on read**: `CacheEngine.get_layer()` validates `schema_version` prefix. Mismatch → treated as MISS (safe).

### 13. Migration Checklist (Pre-Release)

- [ ] ADR-001 through ADR-010 finalized
- [ ] `ico-cache migrate storage` CLI implemented and tested
- [ ] `ico-cache migrate purge-2x-cache` CLI implemented and tested
- [ ] Feature flags gating all L0, L4-L9 layers
- [ ] Python SDK `ICOCache.optimize()` parity with `CacheEngine.resolve_or_generate()`
- [ ] JS SDK `optimize()` method with full type definitions
- [ ] REST API v3 endpoints documented in OpenAPI spec
- [ ] Helm chart supports `cacheVersion: "2.x" | "3.0"` with separate namespaces
- [ ] Benchmark harness `--mode baseline|optimized` implemented
- [ ] Adversarial eval harness passes 0 false hits
- [ ] Migration documented in `MIGRATION_GUIDE.md`
- [ ] CHANGELOG.md includes breaking changes section

### 14. Post-Migration Validation

| Check | Method | Success Criteria |
|-------|--------|------------------|
| No 2.x keys remain | `redis-cli KEYS "v2:*"` / `KEYS "tenant:l1:*"` | Empty |
| No 2.x collections | `qdrant collections list` | No `*_l2_cache`, `*_l3_cache` without `v3_` prefix |
| L1 hit rate recovers | Monitor 24h post-cutover | > 80% of pre-migration rate within 4h |
| False hit rate | Adversarial eval on production traffic | 0% |
| Token savings | WITH/WITHOUT benchmark | ≥ 40% reduction |
| Cost savings | Cost tracking dashboard | ≥ 35% reduction |

## Consequences

### Positive
- **Zero correctness risk**: No stale 2.x entries can cause false hits or tenant leakage
- **Clean architecture**: 3.0 key formats designed correctly from start
- **Incremental rollout**: Feature flags allow per-layer enablement
- **Instant rollback**: 2.x namespaces preserved until migration script runs

### Negative
- **Cold cache on upgrade**: Performance dip for ~4 hours while cache repopulates
- **Operational complexity**: Migration script required for distributed deployments
- **Storage cost during canary**: 2x Redis/Qdrant usage during shadow/canary phase

## Related ADRs

- ADR-001: 10-Layer Cache Hierarchy
- ADR-002: DecisionEngine vs CacheEngine Ownership
- ADR-005: Hard Gates on CRITICAL_FIELDS
- ADR-006: Confidence-Thresholded Reuse

## References

- Phase 3 Architecture Review: Blocking Condition C8
- PHASE3_ARCHITECTURE_REVIEW.md Section 13 (Final Gate Decision)
- TECHNICAL_ANALYSIS_REPORT.md Section 3 (Current Data Flow)

---
*This ADR resolves blocking condition C8 from the Phase 3 Architecture Review.*