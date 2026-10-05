# Phase 3 Architecture Review Report

**Generated**: 2026-10-06  
**Review Type**: Parallel Independent Architecture Validation  
**Status**: CONDITIONAL PASS  

---

## 1. Executive Summary

The Phase 3 architecture proposes a significant evolution from a 3-tier semantic cache (L1/L2/L3) to a 10-layer intelligent optimization layer (L0-L9) with a Decision Engine, project/session memory, and extensive integrations. The parallel review identified **strong foundations** in the current L1/L2/L3 implementation but also **critical architectural gaps** that must be resolved before implementation.

**Overall Verdict**: **CONDITIONAL PASS** — Implementation can begin only after resolving 8 blocking architectural issues identified across all review areas.

---

## 2. Parallel Agent Results

| Agent | Area | Status | Critical Findings |
|---|---|---|---|
| Architect | Architecture | ⚠️ CONDITIONAL | Layer ordering contradiction (graph vs algorithm); DecisionEngine vs CacheEngine ownership ambiguity; No migration strategy; 7 storage systems too complex |
| Cache Engineer | Cache | ⚠️ CONDITIONAL | L0 conflates deterministic + embedding cache; L1 key missing model/provider/prompt_version; Hard gates incomplete (missing authz, embedding_model, reranker versions); Storage assignment puts large blobs in Redis; Invalidation worker missing for new layers |
| Agent Memory Engineer | Memory | ⚠️ CONDITIONAL | L8/L9 interaction enables false hits; L8 privacy/consent model missing; L7 git SHA alone insufficient for staleness (uncommitted changes); Incremental re-analysis explosion risk; L7 cross-tenant leakage via project_id |
| RAG Engineer | RAG | ⚠️ CONDITIONAL | L4 key missing 7+ identity factors (embedder_fingerprint, chunking_fingerprint, reranker_fingerprint); L5 key uses chunk_ids instead of content hashes; Collection versioning not implemented; Pattern A (SDK wrapper) cannot leverage L4/L5 |
| LLM Optimization Engineer | LLM | ⚠️ CONDITIONAL | L1/L2/L3 keys missing model/provider fingerprint (P0 bug); Token counting absent in LiteLLM path; Partial recompute lacks param-sensitivity; L9 should only cache deterministic (temp=0) responses; Model routing not designed |
| Observability Engineer | Telemetry | ⚠️ CONDITIONAL | 70% of proposed metrics missing (tokens, cost, LLM calls, embedding calls, retrieval calls, gate evaluations, confidence); No baseline cost estimation methodology; OTel span hierarchy covers only 10% of proposed |
| Integration Engineer | SDK/Integrations | ⚠️ CONDITIONAL | JS SDK is 40-line HTTP wrapper — no embedded mode, no parity; 8/10 Phase 3 integration targets missing entirely; LLM Proxy needs streaming + token counting + model fingerprint; No OpenAPI spec for new endpoints |
| Security Engineer | Security | 🔴 CRITICAL | L7/L8/L9 keys lack tenant_id (cross-tenant leakage); AGGRESSIVE mode bypasses critical gates; L1/L2/L3 keys lack model fingerprint; No redaction pipeline implemented; Audit logs insufficient for security review |
| Testing Engineer | Testing | ⚠️ CONDITIONAL | 70% of Phase 3 surface untested; Decision Engine, L0, L4-L9, Project/Session Memory have zero tests; Need 15+ new test files; Adversarial coverage must extend to all new layers; Git test fixture needed for L7 |
| Benchmark Engineer | Benchmarking | ⚠️ CONDITIONAL | Current harness tests cache internals only — no WITH/WITHOUT mode; No token/cost accounting; Workload generators too small (54 queries vs 10k required); Adversarial set missing model/provider/commit_sha; No CI/CD integration; Cost measurement unreliable |
| Reviewer | Final Review | ⚠️ CONDITIONAL | Layer ordering contradiction; DecisionEngine vs CacheEngine ownership unclear; Identity/key specs incomplete; Hard gate AGGRESSIVE mode violates correctness principle; 7 storage systems too complex; No migration plan |

---

## 3. Architecture Consistency

### Layer Hierarchy Issues

**Critical Contradiction**: The visual dependency graph (Section 2) and decision algorithm (Section 3) describe different layer orderings.

| Source | Layer Order |
|--------|-------------|
| **Graph (Section 2)** | L0 → L1 → L2 → L3 → L4 ← L5 ← L9 → L6 ← L7 ← L8 |
| **Algorithm (Section 3)** | L0 → L1 → L2 → L3 → L7/L8 → L4 → L5 → L9 → L6 → PARTIAL → FULL |

**Impact**: Implementers will be misled. The algorithm is more detailed and should be authoritative, but the graph will be referenced first.

### Component Boundaries

| Boundary | Status | Issue |
|----------|--------|-------|
| DecisionEngine ↔ CacheEngine | ❌ Unclear | Two competing decision paths; circular dependency risk |
| L4/L5 vs RAGPipeline | ❌ Unclear | L4/L5 are RAG-internal, not sequential layers |
| L7 Project Memory vs RAG Corpus | ❌ Unclear | Both store repository knowledge; deduplication unclear |
| Storage Abstraction | ❌ Missing | 7 concrete stores used directly; no interface layer |

### Responsibilities

| Component | Current | Proposed | Gap |
|-----------|---------|----------|-----|
| CacheEngine | L1/L2/L3 sequential lookup | Decision logic + 10 layer storage | Overloaded |
| DecisionEngine | New | Confidence-thresholded reuse decisions | No clear API boundary |
| Project Memory | None | Git-backed incremental analysis | Scope too large for 4 weeks |
| Invalidation | L1/L2/L3 only | L0-L9 + Redis Streams worker | No consumer protocol |

---

## 4. Critical Ambiguities

### Ambiguity A: L0 Deterministic Computation vs Embedding Cache
- **Finding**: L0 conflates mathematically verifiable deterministic functions (1.0 confidence) with probabilistic embeddings (0.99 confidence, model-dependent)
- **Resolution**: Split into **L0a (Deterministic)** and **L0b (Embedding Cache)** with separate storage (Redis vs LanceDB), TTL, and confidence models

### Ambiguity B: L1 Exact Prompt Match vs L9 LLM Response Cache
- **Finding**: L1 = query+metadata match; L9 = full rendered prompt match. Overlap when metadata is embedded in prompt.
- **Resolution**: L1 = query-centric (includes model_fingerprint, prompt_version); L9 = prompt-centric (opt-in, temp=0 only)

### Ambiguity C: Decision Engine vs CacheEngine Responsibility
- **Finding**: Two patterns proposed — DecisionEngine as wrapper class AND methods added to CacheEngine
- **Resolution**: Choose **Option B** — DecisionEngine as policy layer above CacheEngine; keep `resolve()` stable

### Ambiguity D: Project Memory vs Document/RAG Memory
- **Finding**: L7 stores code summaries; RAG corpus stores documents. Both can answer "how does X work?"
- **Resolution**: L7 = code/symbol knowledge (git-verified); RAG = document knowledge (ingested). Separate query paths.

### Ambiguity E: Session Memory vs Response Caching
- **Finding**: L8 injects context into prompt → L9 caches full prompt. Same prompt from different sessions could hit L9 incorrectly.
- **Resolution**: L9 key must include `session_id` or `injected_context_hash`; or L8 feeds L5 not L9

---

## 5. Cache-Key and Identity Review

| Data | Identity Required | Current | Proposed | Risk |
|---|---|---|---|---|
| **L1 Exact** | query, meta, model, provider, params, prompt_version, context | query + meta | + model, provider, params, prompt_version | **HIGH** — Cross-model false hits (P0 #5) |
| **L2 Semantic** | query_emb, meta, model, provider, embedding_model, collection_version | query_emb + meta | + model, provider, embedding_model, collection_version | **HIGH** — Embedding drift, model switch |
| **L3 Context** | query_emb, context_emb, merged_meta, model, provider, embedding_model | query_emb + context_emb + merged_meta | + model, provider, embedding_model | **HIGH** — Same as L2 |
| **L4 Retrieval** | query_emb, filter, top_k, collection_version, embedder_fingerprint, chunking_fingerprint, reranker_fingerprint | N/A | query_emb + filter + top_k + collection_version | **CRITICAL** — Missing 4+ fingerprints |
| **L5 Context Window** | chunk_content_hashes, template_version, token_budget, model, provider | N/A | chunk_ids + template + token_budget + model | **HIGH** — chunk_ids mutable; missing provider |
| **L6 Tool** | tool_name, args_hash, tool_version, idempotency_key | N/A | tool_name + args + tool_version | **MEDIUM** — Idempotency detection undefined |
| **L7 Project** | tenant_id, repo_url, branch, commit_sha, file_hash, symbol_path | N/A | project_id + file_hash + symbol_path | **CRITICAL** — Missing tenant_id in project_id |
| **L8 Session** | tenant_id, user_id, session_id, turn_id, scope, consent | N/A | session_id + turn_id + scope | **HIGH** — Missing tenant/user isolation |
| **L9 Response** | tenant_id, full_prompt, model, provider, params, prompt_version | N/A | full_prompt + model + provider + params + prompt_version | **CRITICAL** — Missing tenant_id |

---

## 6. Hard-Gate Review

| Gate | Required? | Reason | Failure Action |
|---|---|---|---|
| **tenant_id** | YES | Cross-tenant isolation | Block (CRITICAL) |
| **model** | YES | Model outputs differ | Block (CRITICAL) |
| **provider** | YES | Provider outputs differ | Block (CRITICAL) |
| **model_params** | YES | Temperature/top_p change behavior | Block (CRITICAL) |
| **prompt_version** | YES | Template change = different output | Block (CRITICAL) |
| **entity** | YES | Domain correctness | Block (CRITICAL) |
| **quarter** | YES | Temporal correctness | Block (CRITICAL) |
| **topic** | YES | Domain correctness | Block (CRITICAL) |
| **collection_version** | YES | Corpus change = stale retrieval | Block (CRITICAL) |
| **embedding_model_version** | YES | Embedding drift = false semantic | Block (CRITICAL) |
| **reranker_version** | YES | Reranker change = different order | Block (CRITICAL) |
| **authz_version** | YES | Permission change = security | Block (CRITICAL) |
| **commit_sha** | YES | Stale code knowledge | Degrade confidence (L7) |
| **tool_version** | YES | Tool behavior change | Block (CRITICAL) |
| **time_sensitive** | YES | Real-time data must not cache | Block (CRITICAL) |
| **user_id/session_id** | CONDITIONAL | Personalized responses | Block for personalized (L8/L9) |

**Critical Issue**: AGGRESSIVE mode (0.65 threshold) allows fuzzy gate passes on non-CRITICAL fields, directly violating "Correctness > Hit Rate" principle.

---

## 7. Invalidation Review

| Resource | Trigger | Invalidation Mechanism | Risk |
|---|---|---|---|
| **L0a Deterministic** | Function version, env change | Key includes version → auto-miss | Stale entries accumulate (no active invalidation) |
| **L0b Embedding** | Embedding model version change | Key includes model_version → auto-miss | Silent model updates not detected |
| **L1 Exact** | Explicit invalidate, TTL | Redis DEL / SQLite DELETE | Model fingerprint change not handled |
| **L2/L3 Vector** | Metadata filter change, collection rebuild | Qdrant delete_matching / LanceDB delete | Collection version bump not automated |
| **L4 Retrieval** | Corpus version change | collection_version in key → auto-miss | Version tracking not implemented |
| **L5 Context** | Chunk version change, template change | Chunk hashes in key → auto-miss | Chunk versioning not designed |
| **L6 Tool** | Tool version change, non-idempotent | Tool version in key → auto-miss | Tool versioning scheme undefined |
| **L7 Project** | Git commit change, file modification | Git hook → recompute affected symbols | Git hooks local; distributed notification missing |
| **L8 Session** | Session end, user revoke consent | TTL + explicit delete | Multi-instance needs pub/sub |
| **L9 Response** | Model/param change, prompt template change | Version in key → auto-miss | Prompt template registry not designed |
| **Cross-layer** | L4 invalidated but L5 has stale context | None specified | **HIGH** — Stale context served from L5 |

**Critical Gap**: No Redis Streams consumer protocol defined. Who processes invalidation events? Workers? API pods?

---

## 8. Security Review

### Tenant Risks
- L7 `project_id = hash(repo_url + branch)` — **missing tenant_id** → cross-tenant knowledge leakage
- L8 `session_id` only — no tenant scoping → session hijack across tenants
- L9 key missing `tenant_id` — potential cross-tenant response reuse

### Semantic Reuse Risks
- AGGRESSIVE mode allows false hits on topic/prompt_version/tool_version/collection_version
- Model/provider fingerprint missing from L1/L2/L3 keys (known P0 bug)
- No protection against "iPhone ₹80,000 2025" vs "iPhone ₹90,000 2026" false hits

### Memory Poisoning Risks
- L7 ingests LLM-generated summaries without redaction → code secrets cached
- L8 stores user facts/preferences without validation → injection vector
- L4/L5 cache RAG chunks that may contain PII/secrets

### Stale Data Risks
- Uncommitted changes invisible to git SHA staleness detection
- Branch switching triggers full re-analysis (expensive)
- No semantic diff — file-level invalidation too coarse

### Authorization Risks
- `authz_version` mentioned but not in CRITICAL_FIELDS or key specs
- No hard gate for authorization context

### Sensitive Data Risks
- ADR-009 (redaction pipeline) proposed but not designed
- No mandatory pre-write PII scanning
- Token/cost metrics may leak query semantics

---

## 9. Testing Requirements

### Mandatory Test Files (Priority Order)

| Priority | File | Component |
|---|---|---|
| P0 | `test_decision_engine.py` | Decision logic, confidence, gates, thresholds |
| P0 | `test_hard_gates_extended.py` | CRITICAL_FIELDS, GateMode, confidence penalties |
| P0 | `test_l0_embedding_cache.py` | Embedding cache + deterministic fn cache |
| P0 | `test_l4_retrieval_cache.py` | Retrieval cache with corpus versioning |
| P0 | `test_l5_context_window_cache.py` | Context window cache with chunk/template versioning |
| P0 | `test_l9_llm_response_cache.py` | Full response cache with model/provider binding |
| P1 | `test_l7_project_memory.py` | Repository analysis, incremental updates, staleness |
| P1 | `test_l8_session_memory.py` | Conversation history, facts, consent, TTL |
| P1 | `test_l6_tool_cache.py` | Idempotent tool caching, version invalidation |
| P1 | `test_partial_recompute.py` | Reuse plan, partial execution, fallback |
| P1 | `test_adversarial_l4_l5.py` | Retrieval/context false hits |
| P1 | `test_adversarial_l7_l8.py` | Memory staleness/isolation |
| P1 | `test_adversarial_l9.py` | LLM response model/provider false hits |
| P1 | `test_adversarial_cross_layer.py` | Decision engine fallback correctness |
| P2 | `test_invalidation_extended.py` | L4/L5/L7/L8 invalidation paths |
| P2 | `test_degraded_partial_failure.py` | Partial cache failure scenarios |
| P2 | `test_cache_poisoning.py` | Malicious inserts, prompt injection |

### Infrastructure Needed
- Git test repository fixture in `fixtures_gen.py`
- In-memory `ProjectMemoryStub` for unit tests
- Staleness injection helpers
- Extended `eval_harness.py` for L4/L5/L7/L8/L9 adversarial evaluation
- Cross-platform CI (add Windows runner)

---

## 10. Benchmark Requirements

### Required Measurements

| Metric | Measurement Method | Target |
|---|---|---|
| **Token reduction** | WITH vs WITHOUT token counting | ≥40% |
| **Cost reduction** | Provider pricing × token delta | ≥35% |
| **Latency reduction (p50)** | WITH vs WITHOUT histogram | ≥50% |
| **LLM call reduction** | `llm_calls_total` counter | ≥60% |
| **Embedding call reduction** | `embedding_calls_total` counter | ≥70% |
| **Retrieval call reduction** | `retrieval_calls_total` counter | ≥80% |
| **Repository read reduction** | `repo_reads_total` counter | ≥50% |
| **Cache hit rate** | Per-layer `lookups_total{layer,result}` | Layer-specific |
| **Correctness** | Golden set + LLM judge equivalence | ≥99.5% |
| **False hit rate** | Adversarial eval harness | 0% |

### Required Infrastructure
1. `--mode baseline|optimized` flag in `benchmark.py`
2. `workload_generators.py` for chatbot/coding_agent/rag/multi_agent
3. Golden answer set + LLM-judge equivalence checker
4. Provider pricing registry (configurable, versioned)
5. CI/CD pipeline with regression gates (`scripts/compare_benchmarks.py`)
6. Baseline artifact storage (main branch benchmarks as reference)

---

## 11. Implementation Dependencies

```
Component                    Depends On                    Can Start After
─────────────────────────────────────────────────────────────────────────────
L0 Embedding Cache           BaseEmbedder.model_version    BaseEmbedder interface extended
L4 Retrieval Cache           L0 (query_emb cheap), RAGIntegration abstraction
L5 Context Window Cache      L4 (retrieval), PromptTemplate registry
Decision Engine              L0-L5 interfaces defined, hard gate v2
Token/Cost Accounting        LiteLLM usage capture in pipeline
Model Fingerprint in Keys    All layer key formats updated
L7 Project Memory            Git library chosen, storage abstraction
L8 Session Memory            Consent API, redaction pipeline
L9 Response Cache            Model fingerprint, deterministic-only guard
LLM Proxy                    Streaming, token counting, model fingerprint
MCP Server                   Decision Engine, tool definitions
```

### True Critical Path
```
BaseEmbedder.version → L0 Embedding Cache → L4 Retrieval Cache → L5 Context Cache
                                                         ↓
                                              Decision Engine (confidence, gates)
                                                         ↓
                                              L9 Response Cache → LLM Proxy → SDK optimize()
```

---

## 12. Recommended Changes Before Implementation

### Must Fix (Blocking)

1. **Split L0** → L0a (Deterministic) + L0b (Embedding Cache) with separate specs
2. **Fix L1 key** → Add `model_fingerprint`, `prompt_version`, `context_hash` to `_l1_key()`
3. **Define DecisionEngine pattern** → Explicitly choose wrapper vs internal strategy (ADR-002)
4. **Reconcile layer ordering** → Algorithm is authoritative; update graph
5. **Add tenant_id to L7/L8/L9 keys** → Critical security fix
6. **Remove AGGRESSIVE gate mode** → Or restrict to single-tenant opt-in with audit
7. **Consolidate storage** → Reduce 7 stores to ≤3 (LanceDB for vectors+metadata, Redis for exact, PostgreSQL for relational)
8. **Write ADR-001 through ADR-010** → Decisions, not proposals

### Should Fix (Phase 3A)

9. **Add token/cost accounting** → Prerequisite for all savings claims
10. **Implement collection versioning** → Auto-increment on ingestion
11. **Define chunk versioning** → Content hash in vector payload
12. **Design prompt template registry** → Versioned templates for L1/L5/L9 keys
13. **Specify embedder versioning interface** → `BaseEmbedder.model_version` property
14. **Create migration guide skeleton** → Forces migration thinking

### Defer to Phase 4

15. **L6 Tool Cache** — Not core to semantic caching
16. **L8 Session Memory** — Complex consent/privacy; defer
17. **MCP Server, IDE Extensions, LLM Proxy, CLI** — Integration layer, not core
18. **Multi-region HA** — Operational, not architectural

---

## 13. Final Gate Decision

### CONDITIONAL PASS

**Implementation may begin ONLY after the following 8 conditions are resolved:**

| # | Condition | Owner | Evidence Required |
|---|-----------|-------|-------------------|
| **C1** | Layer ordering contradiction resolved — algorithm authoritative, graph updated | Architect | Updated PHASE3_ARCHITECTURE.md Section 2 |
| **C2** | DecisionEngine vs CacheEngine ownership declared in ADR-002 | Architect + Cache Engineer | ADR-002 with clear interface contract |
| **C3** | L0 split into L0a (Deterministic) + L0b (Embedding) with separate specs | Cache Engineer | Updated Section 2 table + key format specs |
| **C4** | L1 key format updated with model_fingerprint, prompt_version, context_hash | Cache Engineer | Updated `_l1_key()` implementation + tests |
| **C5** | AGGRESSIVE gate mode removed or restricted to opt-in with audit | Security Engineer | ADR-005 updated; GateMode enum has STRICT/BALANCED only |
| **C6** | tenant_id added to L7 project_id, L8 session keys, L9 response keys | Security + Memory Engineers | Key format specs in Sections 2, 4, 5 |
| **C7** | Storage abstraction layer defined (ExactStore, VectorStore, GraphStore, Embedder v2) | Cache Engineer | Interface definitions in `backends/base.py` |
| **C8** | Migration strategy documented for 2.x → 3.0 users | Architect + Integration | ADR-0XX Migration Strategy |

---

## Next Implementation Phase

Once all 8 conditions are met and verified:

**PHASE 3A.1 — DECISION ENGINE + IDENTITY FOUNDATION**

### Scope
1. **ADR-001 to ADR-010** finalized and approved
2. **BaseEmbedder v2** with `model_version` property
3. **L0a Deterministic Cache** — `hash(fn_name + args + version + env_hash)` → Redis
4. **L0b Embedding Cache** — `emb:{model_version}:{text_hash}` → LanceDB
5. **Hard Gate v2** — CRITICAL_FIELDS, GateMode (STRICT/BALANCED), confidence penalties
6. **DecisionEngine** — Internal strategy in CacheEngine; `decide(ctx) → ReuseDecision`
7. **L1 Key Fix** — `model_fingerprint + prompt_version + context_hash` in key
8. **Token/Cost Accounting** — LiteLLM usage capture, Prometheus counters, cost model
9. **Observability Extensions** — Decision spans, gate evaluations, confidence histograms
10. **Test Foundation** — `test_decision_engine.py`, `test_hard_gates_extended.py`, `test_l0_embedding_cache.py`

### Deliverables
- Updated `cache_engine.py` with DecisionEngine integration
- New `decision_engine.py` module
- Extended `metadata_guard.py` with GateMode
- New `embedding_cache.py` module
- Real `/stats` endpoint with token/cost metrics
- All P0 tests passing

### Exit Criteria
- All 8 CONDITIONAL PASS conditions verified
- Decision Engine makes correct reuse decisions for L0/L1/L2/L3
- Embedding cache reduces embedding calls by >70% in benchmark
- Token/cost accounting accurate vs manual calculation
- Zero regressions in existing L1/L2/L3 tests
- Adversarial eval harness passes 0 false hits

---

*End of Phase 3 Architecture Review Report*