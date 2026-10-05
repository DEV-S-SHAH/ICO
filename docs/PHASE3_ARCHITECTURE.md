# ICO-Cache Phase 3: Intelligent AI Optimization Layer — Target Architecture

> **Status**: DESIGN ONLY — No implementation in this phase
> **Scope**: Evolve from semantic/RAG cache → reusable optimization layer between AI apps, RAG systems, coding agents, IDE agents, multi-agent systems, and LLM APIs

---

## 1. Executive Summary

### Current State (EXISTING)
- 3-tier cache: L1 (exact hash), L2 (semantic vector), L3 (dual-context vector)
- Metadata hard gates (entity, quarter, topic) → 0% false-hit baseline
- Multi-tenant (collection or payload isolation)
- Observability: Prometheus, OpenTelemetry, Langfuse
- Async ingestion + universal loaders
- Python/JS SDKs, FastAPI demo, Helm deployment

### Target State (PROPOSED)
ICO-Cache becomes an **Intelligent AI Optimization Layer** that sits between AI consumers and LLM providers, making reuse decisions across a richer hierarchy:

```
EXACT_REUSE → SEMANTIC_REUSE → CONTEXT_REUSE → MEMORY_RETRIEVAL
    → RAG_RETRIEVAL → PARTIAL_RECOMPUTE → FULL_LLM_CALL
```

**Core Principle**: Correctness > Hit Rate. A wrong cache hit is worse than a cache miss.

---

## 2. Target Cache Hierarchy

### Design Rationale
Each layer addresses a distinct reuse scenario with its own key structure, hard gates, TTL, and invalidation. Layers are checked sequentially; first hit wins.

| Layer | Name | Key Structure | Hard Gates | TTL | Storage | Latency Target |
|-------|------|---------------|------------|-----|---------|----------------|
| **L0a** | **Deterministic Computation Cache** | `hash(fn_name + args + fn_version + env_hash)` | Function version, input hash, env hash | ∞ (content-addressable) | Redis (Hot Store) | <1ms |
| **L0b** | **Embedding Cache** | `emb:{model_version}:{text_hash}` | Model version, text hash | 30 days | LanceDB (Vector Store) | <5ms |
| **L1** | **Exact Prompt Match** | `tenant_id:l1:sha256(norm(query) + "|" + model_fingerprint + "|" + prompt_version + "|" + context_hash + "|" + canon_meta)` | tenant_id, model_fingerprint, provider, prompt_version, context_hash, entity, quarter, topic | 1h default | Redis/SQLite (Hot Store) | <1ms |
| **L2** | **Semantic Query Match** | Vector(query_emb) | Metadata hard gate + semantic threshold (≥0.85) | 24h | Qdrant/LanceDB (Vector Store) | ~15ms |
| **L3** | **Context-Aware Match** | Vector(query_emb) + Vector(context_emb) | Merged query+context metadata + dual thresholds | 24h | Qdrant/LanceDB | ~30ms |
| **L4** | **Retrieval Result Cache** | `hash(query_emb + filter + top_k + collection_version)` | Collection version, filter equivalence | 1h | Redis | <5ms |
| **L5** | **Context Window Cache** | `hash(retrieved_chunks + template + token_budget)` | Chunk versions, template version, token budget | 1h | Redis | <5ms |
| **L6** | **Tool Execution Cache** | `hash(tool_name + args + tool_version)` | Tool version, arg hash, idempotency key | Configurable | Redis | <1ms |
| **L7** | **Project/Repository Memory** | `tenant_id + project_id + file_hash + symbol_path` where `project_id = hash(tenant_id + repo_url + default_branch)` | Git commit SHA, file hash, dependency graph, **tenant_id**, **project_id**, embedding_model_version | ∞ (git-backed) | LanceDB + SQLite | ~10ms |
| **L8** | **Session Memory** | `tenant_id + user_id + session_id + turn_id + scope` | Session isolation, user consent, **tenant_id**, **user_id**, **consent_version** | Session TTL | Redis | <1ms |
| **L9** | **LLM Response Cache** | `hash(full_rendered_prompt + model + provider + params + prompt_version + tenant_id + injected_context_hash)` | Model, provider, params, prompt_version, **tenant_id**, **user_id** (if personalized), **session_id** (if personalized), **injected_context_hash** (if L8 context injected), **authz_version** | 1h | Redis | <1ms |

### Layer Ordering: Four Distinct Orderings (Resolves C1)

The Phase 3 Architecture Review identified a contradiction between the conceptual dependency graph and the Decision Engine evaluation sequence. **These are intentionally different orderings serving different purposes.** The Decision Engine evaluation sequence (Execution Order) is **authoritative** for implementation.

#### 1. Conceptual Hierarchy (Abstraction Levels)
```
L0a Deterministic Computation  ← Pure functions, content-addressable
L0b Embedding Cache            ← Version-pinned embeddings
L1 Exact Prompt Match          ← Query + metadata + model_fp + prompt_ver (exact hash)
L2 Semantic Query Match        ← Query embedding + metadata filter (vector similarity)
L3 Context-Aware Match         ← Query emb + Context emb + merged metadata (dual-vector)
─────────────────────────────────────────────────────────────────────────────────────
L4 Retrieval Result Cache      ← RAG retrieval results (query_emb + filter + corpus_version)
L5 Context Window Cache        ← Assembled context (chunk_hashes + template + token_budget)
L6 Tool Execution Cache        ← Idempotent tool results (tool_name + args + version)
L7 Project/Repository Memory   ← Git-verified code knowledge (project_id + commit_sha)
L8 Session Memory              ← Conversation history, facts, preferences (session-scoped)
L9 LLM Response Cache          ← Full rendered prompt + model + params (response reuse)
```

#### 2. Execution Order (AUTHORITATIVE — DecisionEngine Evaluation Sequence)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DecisionEngine.decide(ctx)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. EXACT_REUSE (L0a → L0b → L1)                                           │
│     ├─ L0a: Check deterministic fn cache (Hot Store)                       │
│     ├─ L0b: Check embedding cache for query/context (Vector Store)         │
│     └─ L1: Check exact prompt match (query + model_fp + provider +         │
│           prompt_version + context_hash + meta) → Hot Store                │
│           → If hit & gates pass → RETURN EXACT_REUSE (confidence=1.0)      │
│                                                                             │
│  2. SEMANTIC_REUSE (L2)                                                     │
│     ├─ Embed query (use L0b embedding cache if available)                  │
│     ├─ Vector search with metadata filter                                   │
│     ├─ Hard gate on CRITICAL_FIELDS (tenant, model, entity, quarter, ...)  │
│     └─ If any pass & score ≥ threshold → RETURN SEMANTIC_REUSE             │
│                                                                             │
│  3. CONTEXT_REUSE (L3)                                                      │
│     ├─ Embed query + context (use L0b embedding cache)                     │
│     ├─ Dual-vector intersection search                                     │
│     ├─ Hard gate on merged query+context metadata                          │
│     └─ If hit → RETURN CONTEXT_REUSE (confidence=min(query_score, ctx))    │
│                                                                             │
│  4. MEMORY_RETRIEVAL (L7 → L8)                                              │
│     ├─ L7: If project_id → query project memory (git-verified symbols)     │
│     ├─ L8: If session_id → retrieve session context (facts, history)       │
│     ├─ Assemble retrieved knowledge into context                           │
│     └─ If sufficient coverage → RETURN MEMORY_RETRIEVAL                    │
│                                                                             │
│  5. RAG_RETRIEVAL (L4 → L5)                                                 │
│     ├─ L4: Check retrieval cache (query_emb + filter + top_k + corpus_ver) │
│     │     └─ If miss: run retrieval → populate L4                          │
│     ├─ L5: Check context window cache (chunk_hashes + template + budget)   │
│     │     └─ If miss: construct context → populate L5                      │
│     └─ RETURN RAG_RETRIEVAL (confidence=retrieval_score)                   │
│                                                                             │
│  6. PARTIAL_RECOMPUTE                                                       │
│     ├─ Identify reusable components from L0a-L6 hits                       │
│     ├─ Identify stale/missing components                                   │
│     └─ RETURN PARTIAL_RECOMPUTE with recompute_plan                        │
│                                                                             │
│  7. FULL_LLM_CALL                                                           │
│     └─ No safe reuse path → RETURN FULL_LLM_CALL (confidence=0.0)          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**This is the single authoritative answer to: "In what order does ICO-Cache actually evaluate reuse opportunities?"**

#### 3. Dependency Order (Data Flow Dependencies)

```
L0a (deterministic fn cache) ──┬──→ L1 (exact key includes fn results)
                               ├──→ L4 (retrieval key includes embeddings)
                               └──→ L5 (context key includes embeddings)
                               
L0b (embedding cache) ─────────┬──→ L2 (needs query embedding)
                               ├──→ L3 (needs query + context embeddings)
                               ├──→ L4 (retrieval key includes query_emb)
                               └──→ L7 (project memory embeddings)
                               
L1 (exact match) ───────────────┤  (independent — checked first, no deps)
                               
L7 (project memory) ────────────┼──→ L5 (project knowledge feeds context construction)
                               
L8 (session memory) ────────────┤  (session context feeds context construction)
                               
L4 (retrieval cache) ───────────┼──→ L5 (retrieval results are input to context window)
                               
L5 (context window) ────────────┼──→ L9 (assembled context + prompt = L9 key)
                               
L6 (tool cache) ────────────────┤  (tools execute during generation; results cached)
                               
L9 (response cache) ────────────┘  (final layer — full prompt hash)
```

**Rule**: A layer's dependencies must be resolvable before that layer can be evaluated. L0a/L0b are root dependencies. L7/L8 are independent knowledge sources. L4→L5→L9 is a linear chain.

#### 4. Fallback Order (Degradation Path)

| Trigger | Fallback Action |
|---------|-----------------|
| Vector store (Qdrant/LanceDB) unavailable | Skip L2, L3, L4, L7(vectors) → Degrade to L1 → L5(if chunks cached) → L7(SQLite) → L8 → L9 → PARTIAL → FULL |
| Redis unavailable | Skip L0a, L1, L4, L5, L6, L8, L9 → Degrade to L2/L3 (Qdrant) → L7(LanceDB) → PARTIAL → FULL |
| Embedder unavailable | Skip L0b, L2, L3, L4, L7(vectors) → Degrade to L1 → L5(if chunks cached) → L7(SQLite) → L8 → L9 → FULL |
| Project memory stale (commit_sha mismatch) | L7 confidence -= 0.2; if below threshold → skip L7, continue to L8 |
| Confidence < policy threshold (STRICT=0.95, BALANCED=0.80) | Skip current layer, continue to next |
| Hard gate conflict (CRITICAL_FIELD mismatch) | Skip current layer, continue to next (never degrade confidence) |
| Partial recompute fails | Fall back to FULL_LLM_CALL |
| Generation fails (LLM error) | Return error; do NOT cache; invalidate single-flight lock |

**Principle**: Correctness > Availability. A layer that cannot execute safely is skipped, not approximated.

---

**Key Insight**: L4/L5 sit *between* retrieval and LLM call — they cache RAG internals, not just final responses. L7/L8 are *knowledge sources* that feed into context construction (L5).

**L0a vs L0b Distinction**: L0a caches mathematically verifiable deterministic function results (1.0 confidence — same input always produces same output). L0b caches probabilistic embeddings (model-dependent, ~0.99 confidence — same text with same model version produces same embedding, but model upgrades change outputs). They are separated because:
- **Different correctness models**: L0a = exact reuse; L0b = version-pinned reuse
- **Different storage**: L0a → Redis (Hot Store, sub-ms); L0b → LanceDB (Vector Store, ~5ms)
- **Different invalidation**: L0a invalidates on function version/env change; L0b invalidates on embedding model version change
- **Different consumers**: L0a feeds L1/L4/L5/L6/L9; L0b feeds L2/L3/L4/L5/L7

### Hard Gates Per Layer (PROPOSED)

| Layer | Required Gates (CRITICAL_FIELDS) | Fuzzy-Eligible (BALANCED only) | Confidence Model |
|-------|----------------------------------|--------------------------------|------------------|
| L0a (Deterministic) | Function version, input hash, env hash | — | 1.0 (deterministic) |
| L0b (Embedding Cache) | Model fingerprint, text hash | — | 1.0 (exact) |
| L1 (Exact Prompt) | Tenant_id, model fingerprint, prompt_version, entity, quarter, topic | Custom metadata (if declared fuzzy) | 1.0 (exact) |
| L2 (Semantic) | Tenant_id, model fingerprint, embedding_version, entity, quarter, topic, collection_version | Topic, custom metadata (if declared fuzzy) | 0.85-0.95 (adaptive) |
| L3 (Context-Aware) | Tenant_id, model fingerprint, embedding_version, entity, quarter, topic, collection_version, context_hash | Topic, custom metadata (if declared fuzzy) | 0.75-0.90 |
| L4 (Retrieval Cache) | Tenant_id, collection_version, filter_hash, top_k, embedding_version | Reranker_version (if declared fuzzy) | 0.95 (retrieval determinism) |
| L5 (Context Window) | Tenant_id, chunk content hashes, template_version, token_budget, model fingerprint | — | 0.90 |
| L6 (Tool Cache) | Tenant_id, tool_name, tool_version, arg_hash, idempotency_key | — | 1.0 (if idempotent) |
| L7 (Project Memory) | Tenant_id, project_id, commit_sha, file_hashes, dependency_graph_version, embedding_version | — | 1.0 (git-verified) |
| L8 (Session Memory) | Tenant_id, user_id, session_id, consent_version | Scope (if declared fuzzy) | 0.8 (contextual) |
| L9 (LLM Response) | Tenant_id, user_id (if personalized), model fingerprint, params_hash, prompt_version | — | 0.95 |

**Notes**:
- `model_fingerprint` = `hash(model + provider + params)` — single field replacing separate model/provider/params
- `embedding_version` = `embedder.model_version` property (required by BaseEmbedder v2)
- `collection_version` = Auto-incremented on every corpus ingestion/delete
- `authz_version` = Authorization policy version — **MUST be added to ALL layers** (tracked separately)
- `consent_version` = Incremented when user revokes/grants session memory consent
- `dependency_graph_version` = Hash of project dependency graph
- **AGGRESSIVE mode REMOVED** — see ADR-005. Only STRICT (0.95) and BALANCED (0.80) supported.

### Invalidation Strategy

| Layer | Invalidation Trigger | Mechanism |
|-------|---------------------|-----------|
| L0a | Function version change, env change | Key includes version/hash → auto-miss |
| L0b | Embedding model version change | Key includes model_version → auto-miss |
| L1 | Explicit invalidate, TTL expiry | Redis `DEL` / SQLite `DELETE` |
| L2/L3 | Metadata filter change, collection rebuild | Qdrant `delete_matching` / LanceDB `delete` |
| L4 | Corpus version change (new ingest, delete) | Collection version in key → auto-miss |
| L5 | Chunk version change, template change | Chunk hashes in key → auto-miss |
| L6 | Tool version change, non-idempotent flag | Tool version in key → auto-miss |
| L7 | Git commit change, file modification | Git hook → recompute affected symbols |
| L8 | Session end, user revoke consent | TTL + explicit delete |
| L9 | Model/param change, prompt template change | Version in key → auto-miss |

---

## 2.1 L0a: Deterministic Computation Cache — Detailed Specification

**Purpose**: Cache mathematically verifiable deterministic function results where identical inputs **always** produce identical outputs (1.0 confidence). Examples: token counting, hash computation, AST parsing, schema validation, prompt template rendering, JSON serialization.

**Input**: 
- Function name/identifier (stable, versioned)
- Function arguments (serialized deterministically)
- Function version (semver or content hash of function body)
- Environment hash (Python version, dependency versions, OS) — optional but recommended for cross-env reproducibility

**Output**: Serialized function return value (bytes)

**Identity**: `fn_name + args_hash + fn_version + env_hash` — content-addressable, collision-resistant

**Key Format**: `det:{fn_name}:{fn_version}:{args_hash}:{env_hash}` (Redis string key)

**TTL**: Infinite (content-addressable — never expires unless explicitly invalidated). Optional TTL for memory pressure (e.g., 30 days LRU).

**Storage**: **Hot Store (Redis)** — sub-millisecond latency, high throughput, TTL support for LRU eviction. SQLite fallback for embedded mode.

**Invalidation**:
- **Automatic**: Key includes `fn_version` and `env_hash` — any change = new key = auto-miss
- **Explicit**: `INVALIDATE det:{fn_name}:*` on function removal or forced refresh
- **No async invalidation needed** — content-addressable keys are self-invalidating

**Correctness Gates**:
- Function must be **provably deterministic** (no randomness, no external I/O, no time-dependent logic)
- `fn_version` must change on any semantic change to function body
- `env_hash` must capture all environmental dependencies
- Gate check: `cached_fn_version == current_fn_version AND cached_env_hash == current_env_hash`

**Failure Behavior**:
- On cache miss: execute function, store result, return
- On Redis failure: degrade to direct function execution (no cache)
- On serialization failure: log error, execute function, do not cache
- **Never** return stale result — key mismatch = miss

---

## 2.2 L0b: Embedding Cache — Detailed Specification

**Purpose**: Cache embedding vectors for text inputs to avoid redundant embedding model calls. Same text + same embedding model version = same vector (~0.99 confidence). Model upgrades change outputs → must not reuse across versions.

**Input**:
- Text string (query, context, document chunk, etc.)
- Embedding model identifier + version (e.g., `bge-small-en-v1.5@1.0.0` or model fingerprint)
- Optional: embedding parameters (normalize, truncate, pooling) — folded into model fingerprint

**Output**: Embedding vector (float32 array, typically 384-1536 dimensions)

**Identity**: `model_fingerprint + text_hash` — model-version-pinned

**Key Format**: `emb:{model_fingerprint}:{sha256(text)[:16]}` (LanceDB table key / Redis hash field)

**TTL**: 30 days (embeddings are expensive to recompute but model upgrades invalidate). Configurable per model.

**Storage**: **Vector Store (LanceDB)** — columnar storage optimized for vector payloads, efficient bulk reads, supports metadata filtering. Redis hash fallback for hot embeddings (<10k).

**Invalidation**:
- **Automatic**: Key includes `model_fingerprint` — model upgrade = new key = auto-miss
- **Explicit**: `DELETE FROM embeddings WHERE model_fingerprint = 'old_model'` on model deprecation
- **No async invalidation needed** — model version in key is self-invalidating

**Correctness Gates**:
- `model_fingerprint` MUST be derived from model weights/architecture, not just name (e.g., `sha256(model_config + tokenizer_config)[:12]`)
- Text normalization must be consistent (strip, lowercase, unicode normalize) — same as L1/L2
- Gate check: `cached_model_fingerprint == current_model_fingerprint`

**Failure Behavior**:
- On cache miss: call embedder, store vector, return
- On LanceDB failure: degrade to direct embedder call
- On dimension mismatch: treat as miss (model changed)
- **Never** return embedding from different model version

---

## 2.3 Why Embeddings Are Not Ordinary Deterministic Computation

| Dimension | L0a (Deterministic Fn) | L0b (Embeddings) |
|-----------|------------------------|------------------|
| **Correctness Model** | Mathematical identity: `f(x) = f(x)` always | Version-pinned: `embed_v1(x) = embed_v1(x)` but `embed_v1(x) ≠ embed_v2(x)` |
| **Confidence** | 1.0 (provable) | ~0.99 (empirical, model-dependent) |
| **Invalidation** | Function version + env hash | Embedding model fingerprint |
| **Storage** | Hot Store (Redis) — small values, ultra-low latency | Vector Store (LanceDB) — larger values, batch-friendly |
| **Consumers** | L1, L4, L5, L6, L9 (control flow) | L2, L3, L4, L5, L7 (vector search) |
| **TTL** | Infinite (content-addressable) | Bounded (30 days — model drift risk) |
| **Failure Mode** | Execute fn directly | Call embedder directly |

**Architectural Principle**: The cache hierarchy must prevent confusion between *deterministic function reuse* (L0a — always safe if version matches) and *embedding computation reuse* (L0b — safe only within same model version). Mixing them would allow embedding drift to silently corrupt downstream semantic layers (L2/L3/L4/L5/L7).

---

## 3. Intelligent Decision Engine (Core)

### Purpose
The single component that answers: **"Can previous computation safely be reused?"**

### Inputs (Decision Context)
```python
@dataclass
class DecisionContext:
    # Request identity
    query: str
    context: Optional[str]
    prompt_template: Optional[str]
    prompt_version: str
    
    # Model/Provider
    model: str
    provider: str
    model_params: dict  # temperature, top_p, etc.
    
    # Metadata (extracted + explicit)
    metadata: dict  # entity, quarter, topic, custom
    
    # Identity & Scope
    tenant_id: str
    user_id: Optional[str]
    session_id: Optional[str]
    project_id: Optional[str]
    
    # Repository state (for coding agents)
    repo_url: Optional[str]
    commit_sha: Optional[str]
    changed_files: List[str]
    
    # Tool context
    available_tools: List[ToolSpec]
    tool_versions: dict
    
    # L8/L9 Interaction Control (NEW)
    personalized_response: bool = False  # True if L8 context injected → L9 key includes user/session
    injected_context_hash: Optional[str] = None  # Hash of L8-injected context for L9 key binding
    
    # Authorization
    authz_version: str  # Authorization policy version for cache key invalidation
    
    # Policy
    reuse_policy: ReusePolicy  # STRICT, BALANCED (AGGRESSIVE removed per ADR-005)
    max_latency_ms: int
    cost_budget_usd: Optional[float]
```

---

## 3.1 L1 Exact Prompt Match — Complete Key Contract

**Purpose**: The L1 key defines the exact identity conditions under which a previously generated LLM response can be safely reused. An L1 hit returns the **exact same response bytes** — no semantic approximation.

**Key Format**:
```
{tenant_id}:l1:{sha256(normalized_query + "|" + model_fingerprint + "|" + prompt_version + "|" + context_hash + "|" + canonical_meta_suffix)}
```

**Identity Components** (all REQUIRED):

| Component | Source | Derivation | Purpose |
|-----------|--------|------------|---------|
| `tenant_id` | Request context | Explicit parameter | Cross-tenant isolation (CRITICAL) |
| `normalized_query` | User query | `" ".join(query.lower().strip().split())` | Case/whitespace normalization |
| `model_fingerprint` | Model registry | `sha256(model_config + tokenizer_config + provider_config)[:12]` | Model identity — different model = different output |
| `provider` | Request context | Explicit (openai, anthropic, ollama, gemini, etc.) | Provider identity — same model, different provider = different output |
| `prompt_version` | Prompt template registry | Semver or content hash of rendered system prompt + few-shots | Template change = different output |
| `context_hash` | Context string | `sha256(context)[:16]` if context provided, else `empty` | Context change = different output (fixes C4) |
| `canonical_meta_suffix` | Extracted + explicit metadata | Sorted `k=v` pairs for all non-None metadata fields | Entity/quarter/topic isolation |

**Hard Gates (CRITICAL — all must pass for L1 hit)**:
1. `tenant_id` match (exact)
2. `model_fingerprint` match (exact)
3. `provider` match (exact)
4. `prompt_version` match (exact)
5. `context_hash` match (exact — empty vs non-empty is a mismatch)
6. For each metadata field in `metadata_filter_keys`: if both incoming and cached have non-None values, they must be equal

**TTL**: 1 hour default (configurable per tenant/layer)

**Storage**: Hot Store (Redis primary, SQLite embedded fallback)

**Invalidation**:
- TTL expiry
- Explicit `INVALIDATE {tenant_id}:l1:*`
- Automatic on any identity component change (key changes → auto-miss)

**Under exactly what conditions is an L1 exact result safe to reuse?**
> **An L1 cached response is safe to reuse IF AND ONLY IF all of the following hold:**
> 1. Same tenant (`tenant_id` identical)
> 2. Same normalized query text (case/whitespace normalized)
> 3. Same embedding model fingerprint (model weights + tokenizer + config)
> 4. Same provider (openai vs anthropic vs ollama etc.)
> 5. Same prompt template version (system prompt + few-shots + instructions)
> 6. Same context hash (if context provided; empty context ≠ no context)
> 7. All gated metadata fields match (entity, quarter, topic, and any custom `required_in_gate` fields)
> 8. The cached entry was generated with `temperature=0` or deterministic params (enforced at write time via `_is_cacheable`)

**Why each dimension is required**:
- `model_fingerprint`: GPT-4o vs GPT-4o-mini vs Claude-3.5 produce semantically different outputs for same prompt
- `provider`: Same model (e.g., Llama-3.1-70B) on Ollama vs Together vs Fireworks differs in quantization, system prompt handling, sampling
- `prompt_version`: Template change (even whitespace) changes rendered prompt → different LLM input
- `context_hash`: "What were their risk factors?" with Walmart context ≠ Apple context
- `canonical_meta_suffix`: "Q1 revenue" for MSFT ≠ AAPL (existing hard gate)

**Validation against `cache_engine.py:_l1_key()`**:
Current implementation (line 190-194) only includes `normalized_query + canonical_meta_suffix`. **Missing**: `model_fingerprint`, `provider`, `prompt_version`, `context_hash`. This is the P0 bug identified in the review.

### Outputs (Decision)
```python
@dataclass
class ReuseDecision:
    action: ReuseAction  # EXACT_REUSE, SEMANTIC_REUSE, CONTEXT_REUSE, 
                         # MEMORY_RETRIEVAL, RAG_RETRIEVAL, 
                         # PARTIAL_RECOMPUTE, FULL_LLM_CALL
    confidence: float  # 0.0 - 1.0
    layer: str  # Which layer hit (L0-L9)
    cache_key: Optional[str]
    reasoning: str  # Human-readable explanation
    required_recompute: List[str]  # What must be recomputed if PARTIAL
    metadata_gates_passed: List[str]
    metadata_gates_failed: List[str]
    fallback_reason: Optional[str]  # If not REUSE
```

### Decision Algorithm (PROPOSED) — **AUTHORITATIVE EXECUTION ORDER**

> **Note**: This algorithm defines the **authoritative execution order** for reuse evaluation. 
> The conceptual dependency graph in Section 2 shows data flow dependencies; this algorithm 
> shows the actual evaluation sequence where first hit wins. See Section 2 "Layer Ordering: 
> Four Distinct Orderings" for the complete mapping of all four orderings.

```
1. EXACT_REUSE (L0a/L0b/L1)
   ├─ L0a: Compute deterministic fn key → check Hot Store
   ├─ L0b: Compute embedding key (query, context) → check Vector Store
   ├─ L1: Compute exact key (query + model_fingerprint + provider + prompt_version + context_hash + meta) → check Hot Store
   └─ If hit & all hard gates pass → RETURN EXACT_REUSE (confidence=1.0)

2. SEMANTIC_REUSE (L2)
   ├─ Embed query (use L0b cache)
   ├─ Vector search with metadata filter
   ├─ For each candidate: hard_gate(incoming_meta, cached_meta)
   └─ If any pass & score ≥ threshold → RETURN SEMANTIC_REUSE (confidence=score)

3. CONTEXT_REUSE (L3)
   ├─ Embed query + context (use L0b cache)
   ├─ Dual-vector intersection search
   ├─ Hard gate on merged metadata
   └─ If hit → RETURN CONTEXT_REUSE (confidence=min(query_score, context_score))

4. MEMORY_RETRIEVAL (L7/L8)
   ├─ If project_id: query project memory for relevant symbols/files
   ├─ If session_id: retrieve session context
   ├─ Assemble retrieved knowledge
   └─ If sufficient coverage → RETURN MEMORY_RETRIEVAL (confidence=coverage_score)

5. RAG_RETRIEVAL (L4/L5)
   ├─ Check L4 (retrieval cache) for query+filter
   ├─ If miss: run retrieval → populate L4
   ├─ Check L5 (context window cache) for chunks+template
   ├─ If miss: construct context → populate L5
   └─ RETURN RAG_RETRIEVAL (confidence=retrieval_score)

6. PARTIAL_RECOMPUTE
   ├─ Identify reusable components (L0a-L6 hits)
   ├─ Identify stale/missing components
   └─ RETURN PARTIAL_RECOMPUTE with recompute_plan

7. FULL_LLM_CALL
   └─ No safe reuse path → RETURN FULL_LLM_CALL (confidence=0.0)
```

### Hard Gate Rules (EXTENDING EXISTING)

```python
def hard_gate(incoming: dict, cached: dict, filter_keys: List[str], 
              mode: GateMode = GateMode.STRICT) -> GateResult:
    """
    STRICT:  Both non-None + different → BLOCK
    BALANCED: Both non-None + different → BLOCK unless field marked FUZZY
    """
    for key in filter_keys:
        v_in = incoming.get(key)
        v_cached = cached.get(key)
        if v_in is not None and v_cached is not None and v_in != v_cached:
            if mode == GateMode.STRICT:
                return GateResult(blocked=True, field=key, 
                                 incoming=v_in, cached=v_cached)
            elif mode == GateMode.BALANCED and not is_fuzzy_field(key):
                return GateResult(blocked=True, field=key, ...)
    return GateResult(blocked=False)
```

**GateMode**: `STRICT` (default) | `BALANCED` — **AGGRESSIVE REMOVED** (see ADR-005)

**Per-Layer CRITICAL_FIELDS** (always block on mismatch in BOTH modes):

| Layer | CRITICAL_FIELDS |
|-------|-----------------|
| **L0a** | `function_version`, `input_hash`, `env_hash` |
| **L0b** | `embedding_model_version`, `text_hash` |
| **L1** | `tenant_id`, `model_fingerprint`, `provider`, `prompt_version`, `entity`, `quarter`, `topic` |
| **L2/L3** | `tenant_id`, `model_fingerprint`, `provider`, `embedding_version`, `entity`, `quarter`, `topic`, `collection_version` |
| **L4** | `tenant_id`, `collection_version`, `filter_hash`, `top_k`, `embedding_version`, `reranker_version` |
| **L5** | `tenant_id`, `chunk_content_hashes`, `template_version`, `token_budget`, `model_fingerprint`, `provider` |
| **L6** | `tenant_id`, `tool_name`, `tool_version`, `arg_hash`, `idempotency_key` |
| **L7** | `tenant_id`, `project_id`, `commit_sha`, `file_hash`, `embedding_version`, `dependency_graph_version` |
| **L8** | `tenant_id`, `user_id`, `session_id`, `consent_version` |
| **L9** | `tenant_id`, `model_fingerprint`, `provider`, `params_hash`, `prompt_version`, `authz_version`, `injected_context_hash` (if personalized) |

**FUZZY Fields** (BALANCED mode allows pass with confidence penalty):
Only fields explicitly declared `fuzzy=True` in `MetadataSchema`. Default: `fuzzy=False`.

### Confidence Model

| Action | Base Confidence | Modifiers |
|--------|-----------------|-----------|
| EXACT_REUSE | 1.0 | — |
| SEMANTIC_REUSE | cosine_score | -0.1 per fuzzy gate pass, -0.05 per missing metadata |
| CONTEXT_REUSE | min(query_score, context_score) | -0.1 per context metadata mismatch |
| MEMORY_RETRIEVAL | coverage_ratio | -0.2 if commit_sha mismatch, -0.1 per stale file |
| RAG_RETRIEVAL | retrieval_score | -0.1 if collection version stale |
| PARTIAL_RECOMPUTE | 0.5 | +0.1 per reusable component |
| FULL_LLM_CALL | 0.0 | — |

**Threshold**: Only reuse if `confidence ≥ policy_threshold` (STRICT=0.95, BALANCED=0.80)

### Failure Modes (Safe Defaults)

| Scenario | Behavior |
|----------|----------|
| Confidence < threshold | FULL_LLM_CALL |
| Hard gate conflict | Skip layer, continue to next |
| Vector store unavailable | Degrade to next layer (L2→L3→L4→FULL) |
| Metadata extraction failure | Treat as None (gate passes, but lower confidence) |
| Concurrent generation for same key | Single-flight lock (EXISTING) |
| Partial recompute fails | Fall back to FULL_LLM_CALL |

---

## 4. Agent/Repository Memory (L7)

### Problem
Coding agents re-read entire repositories for related tasks. Need persistent, versioned project knowledge that stays fresh.

### Data Model

```python
@dataclass
class ProjectMemory:
    project_id: str  # hash(tenant_id + repo_url + default_branch) — TENANT-SCOPED
    tenant_id: str   # Explicit tenant scope (CRITICAL for isolation)
    repo_url: str
    default_branch: str
    commit_sha: str  # HEAD at last analysis
    analyzed_at: datetime
    
    # File-level
    files: Dict[str, FileMemory]  # path → FileMemory
    
    # Symbol-level (cross-file)
    symbols: Dict[str, SymbolMemory]  # qualified_name → SymbolMemory
    
    # Architecture
    dependencies: DependencyGraph  # file → [files]
    layers: Dict[str, List[str]]  # layer_name → [files]
    entry_points: List[str]
    
    # Change tracking
    file_hashes: Dict[str, str]  # path → sha256
    last_invalidated: Dict[str, datetime]  # path → when

@dataclass
class FileMemory:
    path: str
    hash: str
    language: str
    symbols: List[str]  # qualified names defined in this file
    imports: List[str]  # qualified names imported
    summary: str  # LLM-generated 2-3 sentence summary
    last_analyzed: datetime
    chunk_ids: List[str]  # References to L7 vector store

@dataclass
class SymbolMemory:
    qualified_name: str
    kind: SymbolKind  # CLASS, FUNCTION, METHOD, VARIABLE, TYPE
    file_path: str
    span: Span  # start_line, end_line
    signature: str
    docstring: Optional[str]
    summary: str  # LLM-generated
    dependencies: List[str]  # symbols this calls/uses
    dependents: List[str]  # symbols that call this
    complexity_score: float
    last_analyzed: datetime
```

### Ingestion Pipeline (PROPOSED)

```
Repository (git) 
    ↓
Git watcher / webhook / scheduled
    ↓
Changed files detection (git diff --name-only)
    ↓
**Authorization Check**: Verify tenant has explicit grant for repo_url (allowlist/OAuth scope)
    ↓
Incremental re-analysis (only changed files + dependents)
    ↓
Update file hashes, symbols, summaries
    ↓
Update dependency graph
    ↓
Vector embeddings for symbols + file summaries → L7 vector store
    ↓
Update commit_sha, analyzed_at
```

**Authorization Requirements**:
- **Write path**: Ingestion request must include valid API key for `tenant_id`. Verify tenant has explicit grant for `repo_url` (allowlist or OAuth token scope with `repo:read`).
- **Read path**: Query must include `tenant_id` and `project_id`. Verify `hash(tenant_id + repo_url + default_branch) == project_id` before returning data.
- **Cross-tenant access**: Explicitly denied. No shared project memory across tenants even for public repos.

### Change Detection & Invalidation

| Event | Invalidation Scope |
|-------|-------------------|
| File modified | File + all symbols in file + dependents (transitive) |
| File deleted | File + symbols + dependents |
| New file | New file + symbols (no invalidation) |
| Dependency added/removed | Affected files + transitive dependents |
| Branch switched | Full re-analysis (different commit_sha) |
| Commit changed (same branch) | Incremental from diff |

**Key Principle**: Never trust stale knowledge. Every query includes `commit_sha`; if mismatch → MEMORY_RETRIEVAL confidence drops, forces re-analysis.

### Memory Retrieval (for Decision Engine)

```python
def retrieve_project_knowledge(
    tenant_id: str,           # NEW: Required for tenant isolation
    project_id: str,
    query: str,
    commit_sha: str,
    task_context: str,  # "add dark mode", "fix bug in payment"
    max_tokens: int,
    user_id: Optional[str] = None  # NEW: For personalized retrieval
) -> ProjectKnowledge:
    """
    Returns relevant symbols, files, summaries for the task.
    Uses hybrid search: vector(query) + graph traversal from entry points.
    Enforces tenant isolation: project_id must match hash(tenant_id + repo_url + branch)
    """
    # 1. Verify project_id belongs to tenant (hash(tenant_id + repo_url + branch) == project_id)
    # 2. Vector search on symbol summaries + file summaries
    # 3. Graph expansion: from hits, traverse dependencies/dependents
    # 4. Rank by relevance to task_context (LLM or heuristic)
    # 5. Pack into token budget
    # 6. Return with confidence = coverage / required_coverage
```

---

## 5. Prompt/Context Optimization (L4, L5, L8, L9)

### Separation of Concerns

| Reuse Type | What | Layer | Example |
|------------|------|-------|---------|
| **Prompt Reuse** | System prompts, instructions, few-shot examples | L1/L9 | Same system prompt across requests |
| **Context Reuse** | Retrieved chunks, assembled context window | L4/L5 | Same docs retrieved for similar queries |
| **Knowledge Reuse** | Project facts, API specs, conventions | L7/L8 | Repository structure, coding standards |
| **Response Reuse** | Full LLM output | L9 | Identical prompt → identical response |

### L4: Retrieval Result Cache
- **Key**: `hash(query_embedding + metadata_filter + top_k + collection_version)`
- **Value**: `[{chunk_id, text, score, metadata}, ...]`
- **Invalidation**: Collection version bump on ingest/delete
- **Use Case**: 1000 users ask "refund policy" → retrieval runs once

### L5: Context Window Cache
- **Key**: `hash(sorted(chunk_ids) + template_version + token_budget + model)`
- **Value**: `{context_string, token_count, chunk_mapping}`
- **Invalidation**: Any chunk_id version change, template change
- **Use Case**: Same retrieved chunks → same context construction

### L8: Session Memory
- **Structure**: Conversation history + extracted facts + user preferences
- **Key**: `tenant_id + user_id + session_id + turn_id + scope + consent_version`  
  (scope = "facts", "preferences", "history", "context")
- **Privacy**: User consent required; TTL = session timeout; auto-purge; explicit revoke endpoint
- **Isolation**: Fully scoped to `(tenant_id, user_id, session_id)` — session IDs are NOT globally unique
- **Use Case**: "Continue my previous analysis" → inject relevant history

### L9: LLM Response Cache
- **Key**: `hash(full_rendered_prompt + model + provider + params + prompt_version + tenant_id + injected_context_hash)`  
  + optional `user_id` + `session_id` if personalized response
- **Value**: `{response, tokens_used, latency_ms, cost_usd, personalized: bool}`
- **Hard Gates**: Model, provider, all params, prompt_version, **tenant_id**, **injected_context_hash** (if L8 context injected), **authz_version** must match exactly
- **Personalization**: Default non-personalized (shared across tenant). Opt-in personalized includes `user_id`/`session_id` when response depends on user/session context
- **L8→L9 Interaction Protection**: `injected_context_hash` in key binds L9 entry to specific L8-injected context, preventing cross-session false hits
- **Use Case**: Deterministic prompts (classification, extraction) with temp=0

### Prompt Template Versioning (PROPOSED)
```python
@dataclass
class PromptTemplate:
    name: str
    version: str  # semver or content hash
    template: str  # jinja2 or similar
    variables: List[str]
    metadata: dict  # intended_model, expected_output_format, etc.
```
All cache keys include `prompt_version` → template change = auto-invalidation.

---

## 6. RAG Integration Model

### Design Goal
Wrap existing RAG systems without requiring replacement. ICO-Cache sits **between** the application and the RAG+LLM pipeline.

### Integration Patterns

#### Pattern A: SDK Wrapper (Recommended)
```python
# User's existing code
rag = MyRAGSystem()
answer = rag.query("What is the refund policy?")

# Becomes
from ico_cache import ICOCache

cache = ICOCache(engine=...)
answer = cache.query(
    query="What is the refund policy?",
    generate_fn=lambda: rag.query("What is the refund policy?")
)
```

#### Pattern B: Proxy Mode
```
Client → ICO-Cache Proxy → User's RAG API → LLM
              ↑
         Cache check here
```
- Deploy as sidecar or gateway
- Transparent to client
- Requires request/response format standardization

#### Pattern C: MCP (Model Context Protocol)
- Expose cache as MCP server
- Agents discover and use via standard protocol
- `tools/cache_lookup`, `tools/cache_ingest`, `tools/project_memory_query`

#### Pattern D: Library Integration (Deep)
```python
# Inside user's RAG pipeline
class MyRAG:
    def __init__(self, cache: Optional[CacheEngine] = None):
        self.cache = cache
    
    def retrieve(self, query):
        # Check L4 retrieval cache
        if self.cache:
            cached = self.cache.get_retrieval(query, self.filters)
            if cached: return cached
        # ... normal retrieval ...
        if self.cache:
            self.cache.set_retrieval(query, self.filters, results)
        return results
```

### Cacheable RAG Stages

| Stage | Cache Layer | Key Includes |
|-------|-------------|--------------|
| Query embedding | L0 | query + model_version |
| Retrieval (vector search) | L4 | query_emb + filter + top_k + corpus_version |
| Reranking | L0/L4 | retrieval_results + reranker_version |
| Context construction | L5 | chunk_ids + template + token_budget + model |
| LLM generation | L9 | full_prompt + model + params |

### Non-Cacheable (Must Execute Fresh)
- User-specific authorization checks
- Real-time data (stock prices, current time)
- Non-idempotent tool calls
- Streaming responses (cache after complete)

---

## 7. Observability Data Model

### Event Flow
```
Request Start
    ├─ DecisionEngine.decide() → ReuseDecision (logged)
    ├─ For each layer checked:
    │    ├─ CacheLookupStart {layer, key_hash, tenant_id}
    │    └─ CacheLookupEnd {layer, hit, latency_ms, confidence}
    ├─ If MISS:
    │    ├─ GenerationStart {model, provider, prompt_tokens_est}
    │    └─ GenerationEnd {completion_tokens, latency_ms, cost_usd}
    ├─ CacheWriteStart {layer, key_hash}
    └─ CacheWriteEnd {layer, success, latency_ms}
Request End
```

### Core Metrics (Per Request)

```json
{
  "request_id": "uuid",
  "session_id": "uuid",
  "tenant_id": "string",
  "agent_type": "chatbot|coding_agent|rag|multi_agent",
  "provider": "openai|anthropic|ollama|gemini",
  "model": "gpt-4o|claude-3.5|llama-3.1",
  
  "decision": {
    "action": "EXACT_REUSE|SEMANTIC_REUSE|CONTEXT_REUSE|MEMORY_RETRIEVAL|RAG_RETRIEVAL|PARTIAL_RECOMPUTE|FULL_LLM_CALL",
    "confidence": 0.92,
    "layer": "L2",
    "reasoning": "Semantic match score 0.91, all hard gates passed",
    "gates_evaluated": ["entity", "quarter", "topic", "model", "tenant"],
    "gates_passed": ["entity", "quarter", "topic", "model", "tenant"],
    "gates_failed": []
  },
  
  "tokens": {
    "input_tokens": 1500,
    "output_tokens": 400,
    "cached_tokens": 1200,
    "tokens_saved": 1200
  },
  
  "latency_ms": {
    "total": 45,
    "decision_engine": 2,
    "cache_lookup": {"L1": 0.5, "L2": 12, "L3": 0},
    "retrieval": 0,
    "llm_generation": 0,
    "cache_write": {"L1": 0.3, "L2": 8, "L3": 0}
  },
  
  "cost_usd": {
    "estimated": 0.002,
    "estimated_without_optimization": 0.008,
    "estimated_savings": 0.006
  },
  
  "cache_layers": {
    "L0": {"checked": true, "hit": false},
    "L1": {"checked": true, "hit": false},
    "L2": {"checked": true, "hit": true, "score": 0.91},
    "L3": {"checked": false},
    "L4": {"checked": false},
    "L5": {"checked": false},
    "L6": {"checked": false},
    "L7": {"checked": false},
    "L8": {"checked": false},
    "L9": {"checked": false}
  },
  
  "project_memory": {
    "project_id": "proj_abc",
    "commit_sha": "a1b2c3d",
    "files_retrieved": 3,
    "symbols_retrieved": 12,
    "tokens_used": 800,
    "staleness_detected": false
  }
}
```

### Aggregated Metrics (Prometheus)

| Metric | Type | Labels |
|--------|------|--------|
| `ico_cache_requests_total` | Counter | `decision`, `agent_type`, `tenant` |
| `ico_cache_tokens_total` | Counter | `type` (input/output/cached/saved), `tenant` |
| `ico_cache_cost_usd_total` | Counter | `type` (actual/saved), `tenant` |
| `ico_cache_latency_seconds` | Histogram | `phase` (decision/cache_lookup/generation/write), `layer` |
| `ico_cache_reuse_confidence` | Histogram | `action`, `layer` |
| `ico_cache_gate_evaluations_total` | Counter | `gate`, `result` (pass/fail), `layer` |
| `ico_cache_project_memory_staleness` | Gauge | `project_id`, `commit_age_hours` |
| `ico_cache_false_hit_suspected` | Counter | `layer`, `reason` |

### Tracing (OpenTelemetry)

**Span Hierarchy**:
```
request (root)
├─ decision_engine.decide
├─ cache_lookup.L1
├─ cache_lookup.L2
├─ cache_lookup.L3
├─ retrieval (if RAG_RETRIEVAL)
│  ├─ cache_lookup.L4
│  ├─ vector_search
│  ├─ cache_lookup.L5
│  └─ context_construction
├─ project_memory.query (if MEMORY_RETRIEVAL)
├─ llm_generation (if FULL_LLM_CALL or PARTIAL_RECOMPUTE)
└─ cache_write.L1/L2/L3/L4/L5/L9
```

**Key Attributes**: All decision fields + `cache.layer`, `cache.hit`, `cache.key_hash` (not full key)

---

## 8. Storage Architecture

### 8.1 Logical Storage Abstractions (C7 Resolution)

The architecture consolidates 7+ physical backends into **3 logical storage abstractions**. Each abstraction defines a clear contract; physical backends implement the contract.

| Logical Abstraction | Responsibility | Latency Target | Durability | Consistency Model | Multi-Tenancy |
|---------------------|----------------|----------------|------------|-------------------|---------------|
| **Hot Store** (Exact/Operational Cache) | L0a deterministic fn cache, L1 exact prompt cache, L4 retrieval cache, L5 context window cache, L6 tool cache, L8 session memory, L9 LLM response cache, invalidation events, prompt template registry | <1ms (p99 <5ms) | Optional (TTL-based eviction acceptable) | Eventual (async replication OK); read-after-write for single-flight | Key prefix `tenant_id:`; Redis: key pattern; SQLite: row tenant_id column |
| **Vector Store** (Semantic/Vector Cache) | L0b embedding cache, L2/L3 semantic/context cache, L7 project memory vectors, RAG corpus | ~5-50ms (p99 <100ms) | Required (persisted to disk) | Strong for metadata filters; eventual for vector index refresh | Collection-per-tenant (default) OR shared collection + payload filter |
| **Durable Store** (Relational/Metadata Memory) | L7 project memory metadata (files, symbols, dependencies, git refs), ingestion job queue, audit logs, analytics/metrics aggregates | ~1-10ms | Required (ACID) | Strong (serializable for metadata) | Row-level tenant_id; PostgreSQL RLS or SQLite per-tenant file |

**Ownership**:
- **Hot Store**: Cache Engineer — all exact-match, TTL-based, high-throughput cache layers
- **Vector Store**: Cache Engineer + RAG Engineer — all vector search, embedding cache, semantic layers
- **Durable Store**: RAG Engineer + Agent Memory Engineer — project memory metadata, ingestion, audit

---

### 8.2 Physical Backend Mapping

| Physical Backend | Implements Abstraction | Deployment Mode | Collections/Tables |
|------------------|------------------------|-----------------|-------------------|
| **Redis** | Hot Store (primary) | Distributed | Keys: `{tenant}:l1:*`, `{tenant}:l4:*`, `{tenant}:l5:*`, `{tenant}:l6:*`, `{tenant}:l8:*`, `{tenant}:l9:*`, `inv:*`, `prompt:*` |
| **SQLite** | Hot Store (embedded fallback) + Durable Store (embedded) | Embedded | Tables: `cache_l1`, `cache_l4`, `cache_l5`, `cache_l6`, `cache_l8`, `cache_l9`, `invalidation_events`, `project_files`, `project_symbols`, `project_deps`, `ingestion_jobs`, `audit_log` |
| **Qdrant** | Vector Store (primary) | Distributed | Collections: `{tenant}_l2_cache`, `{tenant}_l3_cache`, `{tenant}_l0b_embeddings`, `{tenant}_l7_vectors`, `{tenant}_ico_corpus` |
| **LanceDB** | Vector Store (embedded) + Durable Store (embedded, columnar) | Embedded | Tables: `{tenant}_l2_cache`, `{tenant}_l3_cache`, `{tenant}_l0b_embeddings`, `{tenant}_l7_vectors`, `{tenant}_ico_corpus`, `project_metadata` |
| **PostgreSQL** | Durable Store (distributed) | Distributed | Tables: `project_files`, `project_symbols`, `project_dependencies`, `git_refs`, `ingestion_jobs`, `audit_log`, `prompt_templates` (with RLS) |
| **Filesystem** | (Not a store) — LanceDB data files, document uploads | Local/Volume | `./lancedb/`, `INGEST_ROOT/uploads/` |

---

### 8.3 Abstraction Contracts (Validated Against `backends/base.py`)

#### Hot Store Interface (extends `BaseExactStore`)
```python
class BaseHotStore(BaseExactStore):
    # EXISTING
    def get(self, key: str) -> Optional[bytes]: ...
    def set(self, key: str, value: bytes, ex: Optional[int] = None, nx: bool = False): ...
    def delete_prefix(self, prefix: str) -> int: ...
    
    # NEW for L4/L5/L6/L8/L9
    def mget(self, keys: List[str]) -> List[Optional[bytes]]: ...
    def mset(self, mapping: Dict[str, bytes], ex: Optional[int] = None): ...
    def exists(self, key: str) -> bool: ...
    def ttl(self, key: str) -> int: ...
    def publish_invalidation(self, channel: str, message: dict): ...
    def subscribe_invalidation(self, channel: str) -> AsyncIterator[dict]: ...
```

#### Vector Store Interface (extends `BaseVectorStore`)
```python
class BaseVectorStore(ABC):
    # EXISTING
    async def insert(self, collection: str, id: int, vector: Any, payload: dict): ...
    async def search(self, collection: str, vector: Any, query_filter: Any, limit: int, 
                     score_threshold: float, using: Optional[str] = None, **kwargs) -> List[Any]: ...
    async def delete(self, collection: str, id: int): ...
    def collection_exists(self, collection: str) -> bool: ...
    def create_collection(self, collection: str, config: Any): ...
    async def delete_matching(self, collection: str, filter_dict: Optional[dict] = None) -> int: ...
    
    # NEW for L0b/L7
    async def upsert_vectors(self, collection: str, ids: List[int], vectors: List[Any], payloads: List[dict]): ...
    async def get_vectors(self, collection: str, ids: List[int]) -> List[Optional[Any]]: ...
    async def delete_by_filter(self, collection: str, filter_dict: dict) -> int: ...
```

#### Durable Store Interface (NEW)
```python
class BaseDurableStore(ABC):
    # Project Memory Metadata
    async def upsert_file(self, project_id: str, file: FileMemory) -> None: ...
    async def get_file(self, project_id: str, path: str) -> Optional[FileMemory]: ...
    async def delete_file(self, project_id: str, path: str) -> None: ...
    async def list_files(self, project_id: str) -> List[FileMemory]: ...
    
    async def upsert_symbol(self, project_id: str, symbol: SymbolMemory) -> None: ...
    async def get_symbol(self, project_id: str, qualified_name: str) -> Optional[SymbolMemory]: ...
    async def query_symbols(self, project_id: str, filter: dict) -> List[SymbolMemory]: ...
    
    async def upsert_dependency(self, project_id: str, from_symbol: str, to_symbol: str) -> None: ...
    async def get_dependencies(self, project_id: str, symbol: str) -> List[str]: ...
    async def get_dependents(self, project_id: str, symbol: str) -> List[str]: ...
    
    async def set_git_ref(self, project_id: str, branch: str, commit_sha: str) -> None: ...
    async def get_git_ref(self, project_id: str, branch: str) -> Optional[str]: ...
    
    # Ingestion Jobs
    async def enqueue_ingestion(self, job: IngestionJob) -> str: ...
    async def get_ingestion(self, job_id: str) -> Optional[IngestionJob]: ...
    async def update_ingestion_status(self, job_id: str, status: str, result: dict) -> None: ...
    
    # Audit Log
    async def append_audit(self, event: AuditEvent) -> None: ...
    async def query_audit(self, filter: dict, limit: int) -> List[AuditEvent]: ...
```

---

### 8.4 Duplication Elimination (vs EXISTING)

| Existing Duplication | Resolution |
|---------------------|------------|
| L1 in Redis + SQLite | **Hot Store** unified interface; Redis for distributed, SQLite for embedded |
| L2/L3 in Qdrant + LanceDB | **Vector Store** unified interface; Qdrant for distributed, LanceDB for embedded |
| RAG corpus in Qdrant + L2/L3 in Qdrant | Separate collections; shared Vector Store client |
| Embeddings recomputed for L2/L3/RAG | **L0b (Vector Store)** caches embeddings by `emb:{model_fingerprint}:{text_hash}` |
| Project metadata in LanceDB + SQLite | **Durable Store** unified interface; LanceDB columnar for embedded, PostgreSQL for distributed |

---

### 8.5 New Stores Needed (PROPOSED)

1. **Durable Store Implementation**: SQLite (embedded) or PostgreSQL (distributed) for project memory metadata, ingestion queue, audit logs
2. **L0b Embedding Cache**: Vector Store table `emb:{model_fingerprint}:{text_hash}` → vector bytes (reuses Vector Store abstraction)
3. **Prompt Template Registry**: Hot Store keys `prompt:{name}:{version}` → rendered template + metadata (reuses Hot Store abstraction)

---

## 9. Integration Model

| Integration | Type | Use Case | Status |
|-------------|------|----------|--------|
| **Python SDK** | Library | Direct embedding in Python apps | EXISTING (extend) |
| **JS/TS SDK** | Library | Node.js, Browser, Deno | EXISTING (extend) |
| **REST API** | HTTP | Any language, microservices | EXISTING (extend) |
| **OpenCode Plugin** | Plugin | OpenCode agent integration | PROPOSED |
| **VS Code Extension** | Extension | IDE-integrated caching | PROPOSED |
| **Cursor Extension** | Extension | IDE-integrated caching | PROPOSED |
| **MCP Server** | MCP | Standard agent protocol | PROPOSED |
| **CLI** | Binary | Ad-hoc queries, admin | PROPOSED |
| **LLM Proxy** | Reverse Proxy | Transparent caching for any OpenAI-compatible API | PROPOSED |
| **LangChain/LlamaIndex Adapter** | Adapter | Drop-in for RAG frameworks | PROPOSED |

### SDK Extension (PROPOSED)
```python
# Python - High-level optimization layer
cache = ICOCache(
    engine=engine,
    reuse_policy=ReusePolicy.BALANCED,
    project_memory=ProjectMemory(project_id="my-repo"),
    session=SessionMemory(session_id="sess-123")
)

# Single call handles all layers
result = cache.optimize(
    query="Add dark mode",
    context=repo_context,
    generate_fn=my_agent.run
)
# Returns: OptimizationResult(action, response, metrics, decision)
```

### LLM Proxy (PROPOSED)
```
# Config: ico-cache-proxy.yaml
upstream: "https://api.openai.com/v1"
cache_engine: "redis://localhost:6379"
rules:
  - path: "/chat/completions"
    cache_layers: [L1, L9]
    key_extractor: "body.messages[-1].content + body.model"
    ttl: 3600
```

---

## 10. Security Architecture

### Threat Model

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cross-tenant cache leakage | Data exposure | Collection isolation (default) + payload filter fallback; API key → tenant binding; **tenant_id prefix on ALL layer keys (L0-L9)** |
| Stale authorization | Privilege escalation | `authz_version` in all cache keys; invalidate on policy change |
| Prompt injection via cached content | Poisoned responses | Never cache user input directly; sanitize; L1/L9 keys include prompt_version |
| Cache poisoning (malicious inserts) | Wrong answers | Write path requires auth; single-flight prevents race; hard gates on metadata |
| Malicious semantic matches | False hits | Hard gates on CRITICAL_FIELDS; confidence threshold; **AGGRESSIVE mode REMOVED** (ADR-005) |
| Repository source code storage | IP leakage | L7 stores summaries + hashes, not full source; opt-in for full text; **tenant-scoped project_id** |
| Sensitive context persistence | PII exposure | Redaction pipeline before cache write; TTL enforcement; **tenant_id + user_id scoped L8** |
| Memory poisoning (L7) | Corrupted knowledge | Git-verified commits only; signed ingestion; checksum validation |
| Cross-tenant L7 project access | IP leakage | **project_id = hash(tenant_id + repo_url + branch)**; authz check on project queries |
| Cross-tenant L8 session leakage | Conversation exposure | **L8 key = tenant_id:user_id:session_id:...**; consent_version in key |
| Cross-tenant L9 response reuse | Data exposure | **L9 key = tenant_id[:user_id]:hash(...)**; deterministic-only guard (temp=0) |

### Mandatory Security Gates

1. **Tenant Isolation**: Every cache key prefixed with `tenant_id:`; collection isolation default for all vector layers; **L7 project_id, L8 keys, L9 keys include tenant_id**
2. **Authorization Metadata**: `authz_version` in all cache keys; invalidate on policy change
3. **Prompt Versioning**: `prompt_version` in L1/L9 keys; template change = auto-invalidation
4. **Model/Provider Binding**: `model_fingerprint` (hash of model+provider+params) in L1/L2/L3/L5/L9 keys
5. **Git-Verified Project Memory**: L7 only accepts knowledge from verified commits; **tenant-scoped project_id**
6. **Redaction Pipeline**: PII/entity detection before any cache write (mandatory, not configurable) — ADR-009
7. **Audit Logging**: All cache writes/reads/invalidations logged with request_id, tenant_id, user_id; **AGGRESSIVE mode usage audit event**
8. **Gate Mode Enforcement**: Only STRICT (default) and BALANCED modes supported; **AGGRESSIVE REMOVED** (ADR-005)

---

## 11. Benchmark Architecture

### Methodology: WITH vs WITHOUT

```
┌─────────────────────────────────────────────────────────────┐
│                    BENCHMARK HARNESS                        │
├─────────────────────────────────────────────────────────────┤
│  Workload Generator                                         │
│  ├─ Chatbot: 10k queries, 1k unique intents, paraphrases   │
│  ├─ Coding Agent: 50 tasks on 10 repos, related follow-ups │
│  ├─ RAG: 5k questions on 1M docs, temporal variants        │
│  └─ Multi-Agent: 100 conversations, shared context         │
├─────────────────────────────────────────────────────────────┤
│  Two Modes (A/B):                                           │
│  ├─ BASELINE: Direct LLM/RAG calls (no ICO-Cache)          │
│  └─ OPTIMIZED: ICO-Cache layer enabled                     │
├─────────────────────────────────────────────────────────────┤
│  Metrics Collected Per Request:                             │
│  ├─ Tokens (input, output, cached, saved)                  │
│  ├─ Cost (USD, estimated)                                  │
│  ├─ Latency (total, cache, retrieval, generation)          │
│  ├─ LLM Calls (count)                                      │
│  ├─ Embedding Computations (count)                         │
│  ├─ Retrieval Calls (count)                                │
│  ├─ Repository Reads (files, bytes)                        │
│  ├─ Cache Hit Rate (per layer)                             │
│  ├─ Correctness (golden set comparison)                    │
│  └─ False Hit Rate (adversarial near-miss set)             │
└─────────────────────────────────────────────────────────────┘
```

### Correctness Benchmark (Critical)

| Test Set | Description | Expected |
|----------|-------------|----------|
| **Paraphrase Set** | 100 intents × 10 paraphrases | High SEMANTIC_REUSE |
| **Temporal Set** | Same question, different years (Apple 2024 vs 2025) | 0% false hits |
| **Entity Set** | Same metric, different entities (MSFT vs AAPL revenue) | 0% false hits |
| **Context Set** | Follow-up questions needing context | CONTEXT_REUSE > 80% |
| **Code Set** | Related coding tasks on same repo | MEMORY_RETRIEVAL > 70% |
| **Adversarial Set** | Crafted near-misses to trigger false hits | 0 false hits |

### Success Criteria

| Metric | Target |
|--------|--------|
| Token reduction | ≥ 40% |
| Cost reduction | ≥ 35% |
| Latency reduction (p50) | ≥ 50% |
| LLM call reduction | ≥ 60% |
| False hit rate | 0% (hard gate enforced) |
| Correctness (vs baseline) | ≥ 99.5% |

---

## 12. Component Ownership

> **Note**: DecisionEngine vs CacheEngine ownership is defined in **ADR-002**. DecisionEngine is the policy/orchestration layer above CacheEngine. CacheEngine retains the stable `resolve()` API for 2.x compatibility.

| Component | Owner | Interfaces |
|-----------|-------|------------|
| **DecisionEngine** | Architect + Cache Engineer | `decide(ctx) → ReuseDecision`, `register_layer(layer)` |
| **CacheEngine (L0-L9 storage)** | Cache Engineer | `get_layer(layer, key)`, `set_layer(layer, key, value, ttl)`, `invalidate_layer(layer, pattern)`, `resolve()` (legacy) |
| **Project Memory (L7)** | RAG Engineer + Agent Memory Engineer | `analyze(repo)`, `query(project_id, task)`, `invalidate(commit)` |
| **Session Memory (L8)** | Integration Engineer + Agent Memory Engineer | `get(tenant_id, user_id, session_id, scope)`, `set(tenant_id, user_id, session_id, scope, value)`, `revoke(tenant_id, user_id, session_id)` |
| **RAG Integration** | RAG Engineer | `get_retrieval(query, filters)`, `set_retrieval(...)`, `get_context(...)` |
| **Observability** | Observability Engineer | `record(event)`, `metrics()`, `traces()` |
| **Invalidation** | Cache Engineer | `publish(event)`, `subscribe(handler)` |
| **Security** | Security Engineer | `validate_write(key, value, auth)`, `redact(value)` |
| **Storage Abstraction** | Cache Engineer | `ExactStore`, `VectorStore`, `Embedder`, `GraphStore` |
| **SDKs/API/Proxy** | Integration Engineer | `optimize(query, generate_fn)`, `/query`, `/ingest` |

---

## 13. Key Interfaces & Contracts

### CacheEngine (Extended — Backward Compatible)
```python
class CacheEngine:
    # EXISTING — unchanged for 2.x compatibility
    async def resolve(query, context, meta, tenant_id) -> ResolveResult
    async def resolve_or_generate(query, context, meta, tenant_id, generate_fn) -> Result
    async def invalidate(tenant_id, filter_dict) -> InvalidationResult
    
    # PROPOSED — layer-agnostic primitives for DecisionEngine
    async def get_layer(layer: str, key: str) -> Optional[Any]
    async def set_layer(layer: str, key: str, value: Any, ttl: int) -> bool
    async def invalidate_layer(layer: str, pattern: str) -> int
```

### DecisionEngine (NEW — Phase 3)
```python
class DecisionEngine:
    def __init__(self, cache_engine: CacheEngine, policy: ReusePolicy = ReusePolicy.BALANCED):
        ...
    
    def register_layer(self, layer: CacheLayer) -> None:
        """Register a cache layer implementation (L0-L9)."""
        ...
    
    async def decide(self, ctx: DecisionContext) -> ReuseDecision:
        """Main entry point: evaluate all layers per Execution Order, return decision."""
        ...
```

### ProjectMemory (NEW)
```python
class ProjectMemory:
    async def analyze_repository(self, repo_url: str, branch: str) -> AnalysisResult
    async def update_incremental(self, changed_files: List[str]) -> UpdateResult
    async def query(self, project_id: str, task: str, commit_sha: str, 
                    max_tokens: int) -> ProjectKnowledge
    async def get_symbol(self, project_id: str, qualified_name: str) -> SymbolMemory
    async def get_dependencies(self, project_id: str, symbol: str) -> List[str]
```

### RAGIntegration (NEW)
```python
class RAGIntegration:
    def __init__(self, cache_engine: CacheEngine, rag_pipeline: RAGPipeline):
        ...
    
    async def retrieve_cached(self, query: str, filters: dict, top_k: int) -> Optional[List[Chunk]]
    async def store_retrieval(self, query: str, filters: dict, chunks: List[Chunk]) -> None
    async def construct_context_cached(self, chunks: List[Chunk], template: str, 
                                        token_budget: int, model: str) -> Optional[str]
    async def store_context(self, chunk_ids: List[str], template: str, 
                            token_budget: int, model: str, context: str) -> None
```

---

## 14. Architectural Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **False cache hits** | Medium | Critical | Hard gates on CRITICAL_FIELDS; confidence thresholds; adversarial testing |
| **Stale project memory** | High | High | Git commit SHA in every query; incremental re-analysis; staleness metrics |
| **Cache stampede** | Medium | High | Single-flight (EXISTING); probabilistic early expiration |
| **Memory bloat (L7/L8)** | Medium | Medium | TTL + LRU + git-backed pruning; max tokens per session |
| **Cross-tenant leakage** | Low | Critical | Collection isolation default; payload filter defense-in-depth; integration tests |
| **Prompt injection via cache** | Low | High | Never cache raw user input; sanitize; prompt_version in keys |
| **Complexity explosion** | High | Medium | Phased rollout; feature flags per layer; clear ownership |
| **Vector store consistency** | Medium | High | Quorum reads; async replication lag monitoring |
| **Embedding model drift** | Medium | Medium | Model version in all keys; re-embed on version change |
| **Distributed invalidation lag** | Medium | Medium | Redis Streams + worker; eventual consistency acceptable for cache |

---

## 15. ADR Recommendations

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | Adopt 10-layer cache hierarchy (L0-L9) | PROPOSED |
| ADR-002 | DecisionEngine vs CacheEngine ownership (policy above storage) | **ACCEPTED** |
| ADR-003 | Project Memory backed by Git + LanceDB + SQLite | PROPOSED |
| ADR-004 | Retrieval/Context caches (L4/L5) separate from response cache | PROPOSED |
| ADR-005 | Hard gates on CRITICAL_FIELDS always enforced — AGGRESSIVE mode REMOVED | **ACCEPTED** |
| ADR-006 | Confidence-thresholded reuse (not binary hit/miss) | PROPOSED |
| ADR-007 | LLM Proxy as optional deployment mode | PROPOSED |
| ADR-008 | MCP server for agent ecosystem integration | PROPOSED |
| ADR-009 | Redaction pipeline before cache write (mandatory) | PROPOSED |
| ADR-010 | Benchmark harness with adversarial correctness testing | PROPOSED |
| ADR-011 | Tenant isolation model for L7, L8, L9 (tenant_id in all keys) | **ACCEPTED** |
| ADR-012 | 2.x → 3.0 Migration Strategy (clean break, explicit invalidation) | **ACCEPTED** |

---

## 16. Recommended Implementation Sequence

### Phase 3A: Foundation (Weeks 1-4)
1. **Decision Engine** — Core decision logic, confidence model, hard gate extensions
2. **L0 Deterministic Cache** — Embedding cache, function result cache
3. **L4 Retrieval Cache** — Cache retrieval results with corpus versioning
4. **L5 Context Window Cache** — Cache assembled context windows
5. **Observability Extensions** — New metrics, decision tracing, cost tracking

### Phase 3B: Knowledge & Memory (Weeks 5-8)
6. **L7 Project Memory** — Repository analysis, symbol extraction, dependency graph, incremental updates
7. **L8 Session Memory** — Conversation history, fact extraction, consent management
8. **Memory Retrieval Integration** — Decision engine → project/session memory queries

### Phase 3C: Integration & Polish (Weeks 9-12)
9. **L6 Tool Execution Cache** — Idempotent tool result caching
10. **L9 LLM Response Cache** — Full response caching with strict gates
11. **SDK Extensions** — `cache.optimize()` high-level API
12. **LLM Proxy Mode** — Transparent OpenAI-compatible proxy
13. **MCP Server** — Standard protocol exposure

### Phase 3D: Hardening (Weeks 13-16)
14. **Security Hardening** — Redaction pipeline, audit logs, penetration testing
15. **Benchmark Suite** — Adversarial correctness, WITH/WITHOUT harness
16. **Documentation & Examples** — Integration guides, migration guide

### Phase 3E: Production Readiness (Weeks 17-20)
17. **Helm Chart Updates** — New components, resource tuning
18. **Multi-region / HA** — Cache replication, invalidation synchronization
19. **Load Testing** — 10k RPS, multi-tenant isolation verification
20. **Release** — Version sync, changelog, migration docs

---

## 17. Appendix: EXISTING vs PROPOSED Summary

| Area | EXISTING | PROPOSED |
|------|----------|----------|
| **Cache Layers** | L1, L2, L3 | L0a (Deterministic), L0b (Embedding), L1, L2, L3, L4, L5, L6, L7, L8, L9 |
| **Decision Logic** | Sequential L1→L2→L3 | Intelligent Decision Engine with confidence |
| **Project Memory** | None | Git-backed, incremental, symbol-level |
| **Session Memory** | None | Consent-based, fact extraction, TTL |
| **RAG Integration** | Internal RAGPipeline | Wrapper/proxy/MCP for external RAG |
| **Prompt/Context** | Implicit in L1/L3 | Explicit L4/L5/L8/L9 separation |
| **Observability** | Layer hits, latency | Decision reasoning, token/cost savings, correctness |
| **Storage** | Redis, Qdrant, LanceDB, SQLite | **3 Logical Abstractions**: Hot Store, Vector Store, Durable Store (backed by Redis/SQLite/Qdrant/LanceDB/PostgreSQL) |
| **Security** | Tenant isolation, hard gates | + AuthZ versioning, redaction, prompt_version, audit, model_fingerprint, context_hash in L1 |
| **Integrations** | Python, JS, REST API | + OpenCode, VS Code, Cursor, MCP, CLI, Proxy |
| **Benchmarks** | 5-dataset RAG bench | + Adversarial correctness, WITH/WITHOUT, coding agents |

---

*End of Phase 3 Architecture Design*