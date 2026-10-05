# ICO-Cache Phase 3 Security Architecture Review

**Reviewer**: Security Engineer  
**Date**: 2026-10-06  
**Scope**: PHASE3_ARCHITECTURE.md (Sections 10, 14), TECHNICAL_ANALYSIS_REPORT.md (Section 6), Current Implementation

---

## Executive Summary

The Phase 3 architecture proposes a 10-layer intelligent optimization layer (L0-L9) with significant security implications. While the current implementation has strong foundations (tenant isolation via collection/payload modes, hard gates on entity/quarter/topic, constant-time API key comparison), the proposed expansion introduces new attack surfaces that require careful hardening.

**Overall Risk Rating**: **HIGH** — The AGGRESSIVE reuse policy, L7 project memory, and semantic matching layers (L2/L3/L9) create material risks of cross-tenant leakage, IP exposure, and correctness violations if not implemented with strict guards.

---

## 1. Tenant Isolation Analysis

### 1.1 Current Implementation (Strong)

| Aspect | Implementation | Assessment |
|--------|----------------|------------|
| **Collection Mode** (default) | Separate Qdrant/LanceDB collections per tenant (`tenant_a_l2_cache`) | ✅ Strong — physical isolation |
| **Payload Mode** | Shared collections with `tenant_id` filter in payload + metadata filter | ⚠️ Defense-in-depth needed — filter bugs = leakage |
| **API Key → Tenant Binding** | Constant-time `secrets.compare_digest()` in `get_tenant_from_api_key()` | ✅ Strong — timing-safe |
| **Tenant Enforcement at API** | Explicit 403 if `req.tenant_id != authed_tenant` | ✅ Strong |
| **Ingest Path Isolation** | `_safe_ingest_path()` prevents directory traversal | ✅ Strong |

### 1.2 Phase 3 Risks (New Layers)

| Layer | Tenant Isolation Mechanism | Gap |
|-------|---------------------------|-----|
| **L0** (Deterministic) | Key includes `tenant_id` prefix | ✅ OK if enforced |
| **L1** (Exact) | Key includes `tenant_id` prefix | ✅ OK if enforced |
| **L2/L3** (Vector) | Collection isolation OR payload filter | ⚠️ Same as current — must default to collection mode |
| **L4/L5** (RAG Cache) | Key includes `collection_version` + `tenant_id` | 🔴 Must be explicit in key design |
| **L6** (Tool Cache) | Key includes `tenant_id` + `tool_version` | 🔴 Not designed yet |
| **L7** (Project Memory) | `project_id` = hash(repo_url + branch) — **NO tenant_id** | 🔴 **CRITICAL GAP** |
| **L8** (Session Memory) | `session_id` only — **NO tenant_id** | 🔴 **CRITICAL GAP** |
| **L9** (LLM Response) | Key includes `model + provider + params` but **NO tenant_id** | 🔴 **CRITICAL GAP** |

### 1.3 Findings

**CRITICAL**: L7, L8, L9 designs omit `tenant_id` from cache keys. This is a cross-tenant leakage vector.

**REQUIRED**: Every cache key in every layer MUST include `tenant_id` as a prefix or mandatory component. The `DecisionContext` (PHASE3_ARCHITECTURE.md:96-133) includes `tenant_id` but the layer key specifications do not consistently reflect this.

---

## 2. User/Session Isolation Analysis

### 2.1 Current State
- No user/session isolation exists — only tenant-level
- `QueryRequest` has optional `tenant_id` but no `user_id` or `session_id`
- API key maps 1:1 to tenant (no user distinction)

### 2.2 Phase 3 Proposals

| Layer | User/Session Isolation | Risk |
|-------|------------------------|------|
| **L8** (Session Memory) | `session_id + turn_id + scope` with "user consent required" | 🔴 **No tenant_id in key** — sessions could leak across tenants if session IDs collide |
| **L9** (LLM Response) | No user/session binding | 🔴 Responses for User A could be served to User B within same tenant |

### 2.3 Findings

**CRITICAL**: L8 session memory must be scoped to `(tenant_id, user_id, session_id)` — not just `session_id`. Session IDs are not globally unique.

**HIGH**: L9 response cache must include user/session context if personalized responses are cached. Current design only includes `model + provider + params + prompt_version`.

---

## 3. Project Isolation Analysis (L7)

### 3.1 Design (PHASE3_ARCHITECTURE.md:245-355)

```python
@dataclass
class ProjectMemory:
    project_id: str  # hash(repo_url + default_branch) — NO tenant_id!
    repo_url: str
    commit_sha: str
    ...
```

### 3.2 Risks

| Risk | Description | Severity |
|------|-------------|----------|
| **Cross-tenant project access** | `project_id` derived from repo URL only. Tenant A and Tenant B using same public repo (e.g., `github.com/org/repo`) get same `project_id` → shared memory | 🔴 **CRITICAL** |
| **Private repo leakage** | If Tenant A ingests private repo, Tenant B with same repo URL could access summaries/symbols | 🔴 **CRITICAL** |
| **IP leakage via summaries** | L7 stores "LLM-generated 2-3 sentence summaries" of source files — proprietary code patterns could leak | 🔴 **HIGH** |
| **Git commit verification** | "Git-verified commits only" — but no authz check on who can query which project | 🔴 **HIGH** |

### 3.3 Required Fixes

1. **Project ID must include tenant scope**: `project_id = hash(tenant_id + repo_url + default_branch)`
2. **Authorization check on project queries**: Verify tenant has access to this repo (via API key scope or explicit grant)
3. **Opt-in for full source storage**: Default to summaries + hashes only; full source requires explicit consent
4. **Redaction pipeline before L7 write**: Scan for secrets, API keys, PII in code before storing summaries

---

## 4. Authorization & Authentication

### 4.1 Current (Strong)
- API key authentication with constant-time comparison
- API key → tenant mapping (1:1)
- Rate limiting per API key (hashed)
- Fail-closed: empty API_KEYS rejects all requests in production

### 4.2 Phase 3 Gaps

| Gap | Description |
|-----|-------------|
| **No RBAC** | No role-based access control (admin, reader, writer) — all valid keys have full tenant access |
| **No authz_version in cache keys** | PHASE3_ARCHITECTURE.md:702 mentions `authz_version` but not in layer key specs |
| **No user-level authz** | Cannot restrict User A from seeing User B's session memory (L8) |
| **Model/Provider binding** | L9 key includes `model + provider + params` — ✅ Good, but must be enforced |

### 4.3 Findings

**HIGH**: Add `authz_version` to all cache keys (L1-L9). Invalidate on policy change.

**MEDIUM**: Implement RBAC for multi-user tenants. At minimum, add `user_id` to L8/L9 keys.

---

## 5. Cache Poisoning Prevention

### 5.1 Current Defenses
- `_is_cacheable()` blocks errors, refusals, empty responses (cache_engine.py:550-564)
- Single-flight lock prevents race conditions on L1 write
- Conditional write (`nx=True`) prevents overwrites
- Hard gates on metadata (entity, quarter, topic) at L2/L3

### 5.2 Phase 3 New Vectors

| Vector | Layer | Mitigation Needed |
|--------|-------|-------------------|
| **Malicious L2/L3 insert** | L2/L3 | Write path requires auth (✅ current API does this); but SDK direct calls bypass API |
| **Prompt injection via cached context** | L3/L5/L9 | Never cache raw user input; sanitize; `prompt_version` in keys (✅ proposed) |
| **Poisoned project memory (L7)** | L7 | Git-verified commits only; signed ingestion; checksum validation |
| **Poisoned session memory (L8)** | L8 | User consent required; TTL enforcement; scope isolation |
| **Malicious semantic matches** | L2/L3/L9 | Hard gates on CRITICAL_FIELDS; confidence thresholds; human review for AGGRESSIVE |

### 5.3 Findings

**CRITICAL**: The AGGRESSIVE mode (PHASE3_ARCHITECTURE.md:194-213) explicitly allows bypassing non-CRITICAL field gates. This is a **cache poisoning enabler**.

```python
# AGGRESSIVE mode from architecture:
AGGRESSIVE: Only block on CRITICAL fields (tenant, model, entity, quarter)
```

**REQUIRED**: AGGRESSIVE mode must be:
- Opt-in per tenant (not global)
- Audit-logged when used
- Never default
- Require explicit human approval for production use

---

## 6. Memory Poisoning (L7)

### 6.1 Design Claims (PHASE3_ARCHITECTURE.md:698)
- "Git-verified commits only"
- "Signed ingestion"
- "Checksum validation"

### 6.2 Actual Risks

| Attack | Description | Current Mitigation |
|--------|-------------|-------------------|
| **Malicious commit** | Attacker pushes commit with poisoned code → L7 analyzes → stores poisoned summaries | Git verification only checks commit exists, not content safety |
| **Dependency confusion** | Malicious dependency in repo → L7 extracts symbols → cached as "project knowledge" | No dependency validation |
| **Supply chain** | Compromised upstream repo → L7 ingests → all downstream tenants affected | No isolation between tenants sharing same repo |
| **Summary injection** | Code comments/docstrings crafted to inject malicious summaries | LLM-generated summaries not validated |

### 6.3 Required Fixes

1. **Content validation pipeline**: Scan ingested code for suspicious patterns before L7 analysis
2. **Tenant-scoped project IDs**: As noted in Section 3
3. **Signed ingestion**: Require cryptographic signature on ingestion requests (not just git commit)
4. **Summary sanitization**: Redact secrets, validate summary content before storage

---

## 7. Prompt Injection via Cached Data

### 7.1 Current State
- L1/L2/L3 store **generated answers**, not raw user input
- RAG context comes from corpus (ingested documents), not cache
- Corpus ingestion path: `_safe_ingest_path()` prevents path traversal

### 7.2 Phase 3 New Vectors

| Vector | Layer | Risk |
|--------|-------|------|
| **L5 Context Window Cache** | Caches assembled context (retrieved chunks + template) | If chunks contain injected content, cached context poisons future responses |
| **L7 Project Memory** | Stores code summaries from repo | Malicious comments in repo → poisoned summaries → injected into context |
| **L8 Session Memory** | Stores conversation history + extracted facts | User injects "fact" → stored → replayed in future turns |
| **L9 LLM Response Cache** | Caches full responses | Poisoned response cached → served to other users |

### 7.3 Required Fixes

1. **Redaction pipeline BEFORE any cache write** (PHASE3_ARCHITECTURE.md:707 — proposed as ADR-009)
2. **Input validation at ingestion**: Never trust document content
3. **Output validation before cache write**: Scan generated responses for injection patterns
4. **L8 fact extraction validation**: Don't blindly store "facts" from user conversations

---

## 8. Stale Data Risks

### 8.1 Current Invalidation
- Explicit `/invalidate` endpoint with filter
- Invalidation worker consumes Redis Streams
- TTL on L1 (default 1h)
- No auto-invalidation on corpus change

### 8.2 Phase 3 Invalidation Strategy (PHASE3_ARCHITECTURE.md:75-88)

| Layer | Trigger | Mechanism | Gap |
|-------|---------|-----------|-----|
| L0 | Function version/env change | Key includes version/hash → auto-miss | ✅ Good |
| L1 | Explicit, TTL | Redis DEL / SQLite DELETE | ⚠️ No corpus change detection |
| L2/L3 | Metadata filter change, collection rebuild | Qdrant `delete_matching` | ⚠️ Manual |
| L4 | Corpus version change | Collection version in key → auto-miss | ✅ Good if version bumped |
| L5 | Chunk version/template change | Chunk hashes in key → auto-miss | ✅ Good if version bumped |
| L6 | Tool version change | Tool version in key → auto-miss | ✅ Good |
| L7 | Git commit change | Git hook → recompute | 🔴 **No git hook implementation** |
| L8 | Session end, consent revoke | TTL + explicit delete | ⚠️ Relies on TTL |
| L9 | Model/param/prompt change | Version in key → auto-miss | ✅ Good |

### 8.3 Findings

**HIGH**: L7 git hook invalidation is proposed but not implemented. Without it, stale code summaries persist across commits.

**HIGH**: No automatic corpus change detection for RAG. Invalidation is manual.

**MEDIUM**: TTL-based invalidation for L8 is weak — session could persist beyond user intent.

---

## 9. Model/Provider Identity in Cache Keys

### 9.1 Current Gap (TECHNICAL_ANALYSIS_REPORT.md:99, 167-168)
- **L1 key lacks model/provider fingerprint** — switching models returns stale cache
- **L2/L3 keys lack model/provider** — embeddings are model-specific but key doesn't reflect this

### 9.2 Phase 3 Design (PHASE3_ARCHITECTURE.md:216)
- **CRITICAL_FIELDS**: `tenant_id`, `model`, `provider`, `entity`, `quarter`, `prompt_version`, `tool_version`, `collection_version`
- L9 key: `hash(full_rendered_prompt + model + provider + params + prompt_version)` ✅

### 9.3 Findings

**CRITICAL**: Current L1/L2/L3 keys do NOT include model/provider. This is a known bug (TECHNICAL_ANALYSIS_REPORT.md:99).

**REQUIRED**: Add `model_fingerprint` (hash of model + provider + params) to L1, L2, L3 keys immediately. This must be in the cache key, not just metadata.

---

## 10. Secret Handling

### 10.1 Current
- Secrets in env vars / Kubernetes secrets (Helm chart)
- `audit.py` scans for secrets in git-tracked files (SECRET_PATTERNS)
- API keys never logged (constant-time compare, hashed in rate limiter)

### 10.2 Phase 3 Risks

| Risk | Layer | Mitigation |
|------|-------|------------|
| **Secrets in L7 code summaries** | L7 | Redaction pipeline before L7 write |
| **Secrets in L8 session facts** | L8 | Redaction pipeline before L8 write |
| **Secrets in RAG corpus chunks** | L4/L5 | Redaction at ingestion |
| **API keys in cache values** | All | `_is_cacheable()` doesn't scan for secrets in response |

### 10.3 Required

1. **Redaction pipeline** (ADR-009) must be mandatory, not optional
2. **Scan cache values before write**: Detect and block secrets in generated responses
3. **Secret scanning in audit.py**: Already exists — must run in CI

---

## 11. Audit Logs

### 11.1 Current
- Structured logging with `structlog`
- Request ID middleware
- Logs: cache hits/misses, latency, tenant_id, query
- **No audit log for cache writes/invalidations** (only info logs)

### 11.2 Phase 3 Proposal (PHASE3_ARCHITECTURE.md:708)
- "Audit Logging: All cache writes/reads/invalidations logged with request_id, tenant_id, user_id"

### 11.3 Findings

**HIGH**: Current logs are observability, not audit. Audit logs need:
- Immutable storage (append-only)
- Tamper-evidence
- User identity (not just tenant)
- Action type (read/write/invalidate/decide)
- Decision reasoning (for forensic analysis)

**REQUIRED**: Implement dedicated audit log sink separate from application logs.

---

## 12. Sensitive Data Leakage

### 12.1 Current
- No PII detection/redaction
- Logs include `query` text (could contain PII)
- Metrics include `tenant_id` but not query content

### 12.2 Phase 3 Observability (PHASE3_ARCHITECTURE.md:498-563)
- Traces include `query` in span attributes
- Metrics include `tenant` label
- **No mention of PII scrubbing in traces/metrics**

### 12.3 Required

1. **PII redaction in logs/traces**: Structlog processor to scrub emails, SSNs, credit cards, API keys
2. **Query hashing in metrics**: Log `query_hash` not `query`
3. **Redaction pipeline** (ADR-009) for cache values

---

## 13. Cross-Tenant Semantic Matches

### 13.1 Current Defense
- Collection isolation (default) — physical separation
- Payload mode — filter on `tenant_id` in vector search
- Hard gate on metadata (entity, quarter, topic)

### 13.2 Adversarial Test Results (benchmark.py:202-208)
```python
tenant_bleed = 0
asyncio.run(engine.async_write_l2("What is the revenue of AAPL in Q1?", {"content": "ten-a"}, tenant_id="tenant_a"))
for _ in range(3):
    hit, _ = l2_lookup(engine, "Tell me the revenue for AAPL Q1", tenant_id="tenant_b")
    if hit is not None:
        tenant_bleed += 1
```
**Test expects `tenant_bleed == 0`** — passes with collection mode.

### 13.3 Phase 3 Risk: AGGRESSIVE Mode + Payload Mode
If tenant uses payload mode AND AGGRESSIVE policy:
- Cross-tenant vectors in same collection
- AGGRESSIVE only blocks on CRITICAL_FIELDS (tenant, model, entity, quarter)
- If `tenant_id` not in metadata filter (bug), semantic match could cross tenant boundary

**REQUIRED**: 
- Default to collection mode (never payload) for multi-tenant deployments
- AGGRESSIVE mode must ALWAYS enforce `tenant_id` gate regardless of policy
- Integration test: payload mode + AGGRESSIVE = must not leak

---

## 14. CRITICAL_FIELDS Sufficiency Analysis

### 14.1 Proposed CRITICAL_FIELDS (PHASE3_ARCHITECTURE.md:216)
```
tenant_id, model, provider, entity, quarter, prompt_version, tool_version, collection_version
```

### 14.2 Missing Critical Fields

| Missing Field | Why Critical | Layer Impact |
|---------------|--------------|--------------|
| **user_id** | User isolation within tenant | L8, L9 |
| **session_id** | Session isolation | L8 |
| **project_id** | Project isolation (L7) | L7 |
| **repo_url / commit_sha** | Code freshness | L7 |
| **authz_version** | Authorization policy changes | All |
| **corpus_version** | RAG corpus freshness | L4, L5 |
| **embedding_model_version** | Embedding compatibility | L2, L3, L4, L7 |
| **reranker_version** | Retrieval determinism | L4 |
| **template_version** | Prompt template changes | L5, L9 |

### 14.3 Findings

**CRITICAL**: Current CRITICAL_FIELDS is **insufficient** for Phase 3 layers. Must expand per-layer.

**REQUIRED**: Per-layer critical fields:
- L0: `function_version, input_hash, env_hash`
- L1: `tenant_id, model, provider, prompt_version, entity, quarter, topic`
- L2/L3: `tenant_id, model, provider, embedding_version, entity, quarter, topic, collection_version`
- L4: `tenant_id, collection_version, filter_hash, top_k, embedding_version`
- L5: `tenant_id, chunk_hashes, template_version, token_budget, model`
- L6: `tenant_id, tool_name, tool_version, arg_hash, idempotency_key`
- L7: `tenant_id, project_id, commit_sha, file_hashes, dependency_graph_version`
- L8: `tenant_id, user_id, session_id, consent_version`
- L9: `tenant_id, user_id, model, provider, params_hash, prompt_version`

---

## 15. AGGRESSIVE Mode Security Risk Assessment

### 15.1 Definition (PHASE3_ARCHITECTURE.md:198-213)
```python
AGGRESSIVE: Only block on CRITICAL fields (tenant, model, entity, quarter)
```

### 15.2 Risk Scenarios

| Scenario | Result |
|----------|--------|
| Different `topic` (revenue vs margins), same entity/quarter | **FALSE HIT** — AGGRESSIVE allows |
| Different `prompt_version`, same model/entity | **FALSE HIT** — AGGRESSIVE allows (prompt_version is CRITICAL but only for L1/L9) |
| Different `tool_version`, same tool/args | **FALSE HIT** — AGGRESSIVE allows |
| Different `collection_version`, same query | **FALSE HIT** — AGGRESSIVE allows |
| Cross-tenant (if tenant_id gate bypassed) | **DATA LEAK** — CATASTROPHIC |

### 15.3 Verdict

**AGGRESSIVE MODE IS UNSAFE FOR PRODUCTION USE.**

Recommendations:
1. **Remove AGGRESSIVE mode** — or restrict to single-tenant, non-sensitive workloads only
2. If kept: **Require explicit opt-in per request**, audit log every AGGRESSIVE decision, never default
3. **Minimum**: STRICT and BALANCED only for multi-tenant; AGGRESSIVE only for single-tenant internal tools

---

## 16. Redaction Pipeline Design Review (ADR-009)

### 16.1 Proposed (PHASE3_ARCHITECTURE.md:707, 871)
- "Redaction pipeline before cache write (configurable)"

### 16.2 Required Capabilities

| Capability | Required? | Notes |
|------------|-----------|-------|
| PII detection (emails, phones, SSN, credit cards) | ✅ Yes | Regex + ML |
| Secret detection (API keys, passwords, tokens) | ✅ Yes | Regex patterns |
| Code secret detection (hardcoded keys in source) | ✅ Yes | For L7 |
| Configurable rules per tenant | ✅ Yes | Different compliance needs |
| Fail-closed (block write if redaction fails) | ✅ Yes | Never cache unredacted |
| Audit log of redaction actions | ✅ Yes | What was redacted, why |

### 16.3 Findings

**Design is insufficiently specified**. Must define:
- Where in pipeline (before L1 write? before all layer writes?)
- Whether redaction applies to keys or only values
- Performance impact (latency budget)
- False positive handling (block legitimate cache entries)

---

## 17. Audit Log Completeness

### 17.1 Current Gaps
- No audit of cache write decisions
- No audit of hard gate evaluations
- No audit of invalidation triggers
- No audit of AGGRESSIVE mode usage
- No audit of cross-tenant access attempts

### 17.2 Required Audit Events

| Event | Fields |
|-------|--------|
| `cache.decide` | request_id, tenant_id, user_id, decision, confidence, layer, gates_passed, gates_failed, policy |
| `cache.read` | request_id, tenant_id, layer, key_hash, hit, latency_ms |
| `cache.write` | request_id, tenant_id, layer, key_hash, value_hash, ttl, cacheable |
| `cache.invalidate` | request_id, tenant_id, layer, filter, purged_count, trigger |
| `cache.aggressive_used` | request_id, tenant_id, layer, reason, approver |
| `cache.cross_tenant_attempt` | request_id, source_tenant, target_tenant, layer, blocked |
| `redaction.applied` | request_id, tenant_id, layer, field, pattern_matched |

---

## 18. Summary of Critical Findings

| # | Finding | Severity | Component | Required Action |
|---|---------|----------|-----------|-----------------|
| 1 | L7/L8/L9 keys lack `tenant_id` | 🔴 CRITICAL | Project/Session/Response Memory | Add `tenant_id` to all layer key specs |
| 2 | L7 `project_id` not tenant-scoped | 🔴 CRITICAL | Project Memory | `project_id = hash(tenant_id + repo_url + branch)` |
| 3 | AGGRESSIVE mode bypasses critical gates | 🔴 CRITICAL | Decision Engine | Remove or restrict to single-tenant opt-in |
| 4 | L1/L2/L3 keys lack model/provider fingerprint | 🔴 CRITICAL | Cache Keys | Add `model_fingerprint` to all keys |
| 5 | No redaction pipeline implemented | 🔴 CRITICAL | All Writes | Implement ADR-009 before any L7/L8/L9 write |
| 6 | No authz_version in cache keys | 🔴 CRITICAL | All Layers | Add `authz_version` to all keys |
| 7 | No user/session isolation in L8/L9 | 🔴 CRITICAL | Session/Response Memory | Scope L8/L9 to `(tenant_id, user_id, session_id)` |
| 8 | L7 git hook invalidation not implemented | 🔴 HIGH | Project Memory | Implement git webhook/hook for auto-invalidation |
| 9 | Audit logs are observability, not audit | 🔴 HIGH | Observability | Implement tamper-evident audit log sink |
| 10 | PII/secrets in logs/traces | 🔴 HIGH | Telemetry | Add structlog processors for redaction |
| 11 | Payload mode + AGGRESSIVE = leak risk | 🔴 HIGH | Multi-tenancy | Default to collection mode; ban AGGRESSIVE in payload mode |
| 12 | CRITICAL_FIELDS insufficient for new layers | 🔴 HIGH | Hard Gates | Define per-layer critical fields |
| 13 | No RBAC for multi-user tenants | 🟠 MEDIUM | AuthZ | Add role-based access control |
| 14 | L8 TTL-only session expiry | 🟠 MEDIUM | Session Memory | Add explicit revoke + consent tracking |
| 15 | No secret scanning in cache values | 🟠 MEDIUM | Cache Write | Scan `_is_cacheable()` output for secrets |

---

## 19. Recommendations Priority Order

### P0 (Blockers for Phase 3 Implementation)
1. Add `tenant_id` to L7, L8, L9 key specifications
2. Make `project_id` tenant-scoped
3. Add `model_fingerprint` to L1/L2/L3 keys (fix known bug)
4. Remove AGGRESSIVE mode or restrict to single-tenant opt-in with audit
5. Implement redaction pipeline (ADR-009) as mandatory pre-write step

### P1 (Required Before Multi-Tenant Production)
6. Define per-layer CRITICAL_FIELDS
7. Add `authz_version` to all cache keys
8. Implement audit log sink (tamper-evident)
9. Add PII/secret redaction in structlog processors
10. Implement L7 git hook invalidation

### P2 (Hardening)
11. Add RBAC for multi-user tenants
12. Scope L8/L9 to user/session
13. Secret scanning in `_is_cacheable()`
14. Payload mode: require collection mode for multi-tenant
15. Adversarial test suite for all new layers (L4-L9)

---

## 20. Compliance with "Correctness > Hit Rate" Principle

The Phase 3 architecture states: **"Core Principle: Correctness > Hit Rate. A wrong cache hit is worse than a cache miss."**

### Violations in Current Design:
1. **AGGRESSIVE mode** directly violates this — trades correctness for hit rate
2. **Missing model fingerprint in L1/L2/L3** — known cause of wrong hits
3. **L7/L8/L9 missing tenant_id** — enables cross-tenant wrong hits
4. **No authz_version** — stale authorization = wrong hits

### Required Alignment:
Every design decision must be evaluated: "Does this increase hit rate at the cost of correctness?" If yes, reject or add compensating hard gate.

---

## Appendix: Key Files Inspected

| File | Purpose |
|------|---------|
| `docs/PHASE3_ARCHITECTURE.md` | Phase 3 target architecture (Sections 10, 14) |
| `TECHNICAL_ANALYSIS_REPORT.md` | Baseline analysis (Section 6) |
| `packages/ico-cache-py/src/ico_cache/core/metadata_guard.py` | Hard gate implementation |
| `packages/ico-cache-py/src/ico_cache/core/cache_engine.py` | Cache engine, L1/L2/L3, `_is_cacheable()` |
| `apps/financial-rag-demo/api/main.py` | API auth, tenant enforcement, rate limiting |
| `apps/financial-rag-demo/api/config.py` | Settings, API key parsing, secrets |
| `packages/ico-cache-py/tests/test_multitenancy.py` | Cross-tenant isolation tests |
| `examples/financial_schema.py` | Financial metadata schema |
| `examples/universal_schema.py` | Universal metadata schema |
| `deploy/helm/ico-cache/templates/secrets.yaml` | Kubernetes secrets management |
| `audit.py` | Security audit automation |
| `benchmark.py` | Adversarial benchmark (D2) |

---

*End of Security Review Report*