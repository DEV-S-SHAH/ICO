# Architecture & Layer Design

ICO-Cache is an enterprise-grade multi-layer semantic caching engine designed specifically for Large Language Model and RAG workflows. It eliminates redundant generations while mathematically preventing false positives on domain-specific near-miss queries.

---

## 1. Authoritative Layer Ordering (Resolves C1)

The Phase 3 Architecture Review identified a contradiction between the conceptual layer graph and the Decision Engine evaluation sequence. **The Decision Engine evaluation sequence (Execution Order) is authoritative.** The conceptual graph shows data dependencies; the execution order shows actual evaluation sequence. They are intentionally different.

### 1.1 Four Distinct Orderings

| Ordering | Purpose | Authority |
|----------|---------|-----------|
| **Conceptual Hierarchy** | Abstraction layers from deterministic → semantic → contextual → memory → retrieval → generation | Design documentation |
| **Execution Order** | Sequence in which DecisionEngine evaluates reuse opportunities (first hit wins) | **AUTHORITATIVE** — implements "In what order does ICO-Cache actually evaluate reuse opportunities?" |
| **Dependency Order** | Data flow: what each layer requires from previous layers to function | Implementation |
| **Fallback Order** | Degradation path when layers are unavailable or confidence thresholds not met | Runtime resilience |

### 1.2 Conceptual Hierarchy (Abstraction Levels)

```
L0  Deterministic Computation      ← Pure functions, embeddings (content-addressable)
L1  Exact Prompt Match             ← Query + metadata + prompt_version (exact hash)
L2  Semantic Query Match           ← Query embedding + metadata filter (vector similarity)
L3  Context-Aware Match            ← Query emb + Context emb + merged metadata (dual-vector)
─────────────────────────────────────────────────────────────────────────────────────
L4  Retrieval Result Cache         ← RAG retrieval results (query_emb + filter + corpus_version)
L5  Context Window Cache           ← Assembled context (chunk_hashes + template + token_budget)
L6  Tool Execution Cache           ← Idempotent tool results (tool_name + args + version)
L7  Project/Repository Memory      ← Git-verified code knowledge (project_id + commit_sha)
L8  Session Memory                 ← Conversation history, facts, preferences (session-scoped)
L9  LLM Response Cache             ← Full rendered prompt + model + params (response reuse)
```

**Key Insight**: L0-L3 are **query-facing caches** (checked on incoming request). L4-L5 are **RAG-internal caches** (checked during retrieval/context construction). L6-L8 are **knowledge sources** (feed into context construction). L9 is **response-facing cache** (checked after prompt construction).

### 1.3 Execution Order (AUTHORITATIVE — DecisionEngine Evaluation Sequence)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DecisionEngine.decide(ctx)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. EXACT_REUSE (L0a → L0b → L1)                                            │
│     ├─ L0a: Check deterministic fn cache (pure fn results)                  │
│     ├─ L0b: Check embedding cache (query, context embeddings)              │
│     └─ L1: Check exact prompt match (query + meta + model_fp + prompt_ver + ctx_hash) │
│           → If hit & gates pass → RETURN EXACT_REUSE (confidence=1.0)      │
│                                                                             │
│  2. SEMANTIC_REUSE (L2)                                                     │
│     ├─ Embed query (use L0b embedding cache if available)                   │
│     ├─ Vector search with metadata filter                                   │
│     ├─ Hard gate on CRITICAL_FIELDS (tenant, model, entity, quarter, ...)  │
│     └─ If any pass & score ≥ threshold → RETURN SEMANTIC_REUSE             │
│                                                                             │
│  3. CONTEXT_REUSE (L3)                                                      │
│     ├─ Embed query + context (use L0b embedding cache)                      │
│     ├─ Dual-vector intersection search                                     │
│     ├─ Hard gate on merged query+context metadata                          │
│     └─ If hit → RETURN CONTEXT_REUSE (confidence=min(query_score, ctx_score))│
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

### 1.4 Dependency Order (Data Flow Dependencies)

```
L0b (embedding cache) ───┬──→ L2 (needs query embedding)
                         ├──→ L3 (needs query + context embeddings)
                         └──→ L4 (needs query embedding for retrieval key)
                            │
L0a (deterministic fn) ───┤  (independent — pure functions, token counting, etc.)
                            │
L1 (exact match) ─────────┤  (independent — checked first, no deps)
                            │
L7 (project memory) ──────┼──→ L5 (project knowledge feeds context construction)
                            │
L8 (session memory) ──────┤  (session context feeds context construction)
                            │
L4 (retrieval cache) ─────┼──→ L5 (retrieval results are input to context window)
                            │
L5 (context window) ───────┼──→ L9 (assembled context + prompt = L9 key)
                            │
L6 (tool cache) ───────────┤  (tools execute during generation; results cached)
                            │
L9 (response cache) ───────┘  (final layer — full prompt hash)
```

**Rule**: A layer's dependencies must be resolvable before that layer can be evaluated. L0b is the root dependency for embeddings (L2, L3, L4, L7-vectors). L0a is independent (deterministic functions). L7/L8 are independent knowledge sources. L4→L5→L9 is a linear chain.

### 1.5 Fallback Order (Degradation Path)

| Trigger | Fallback Action |
|---------|-----------------|
| Vector store (Qdrant/LanceDB) unavailable | Skip L2, L3, L4, L7(vectors) → Degrade to L1 → L5(if chunks cached) → L7(SQLite) → L8 → L9 → PARTIAL → FULL |
| Redis unavailable | Skip L0, L1, L4, L5, L6, L8, L9 → Degrade to L2/L3 (Qdrant) → L7(LanceDB) → PARTIAL → FULL |
| Embedder unavailable | Skip L0, L2, L3, L4, L7(vectors) → Degrade to L1 → L5(if chunks cached) → L7(SQLite) → L8 → L9 → FULL |
| Project memory stale (commit_sha mismatch) | L7 confidence -= 0.2; if below threshold → skip L7, continue to L8 |
| Confidence < policy threshold (STRICT=0.95, BALANCED=0.80) | Skip current layer, continue to next |
| Hard gate conflict (CRITICAL_FIELD mismatch) | Skip current layer, continue to next (never degrade confidence) |
| Partial recompute fails | Fall back to FULL_LLM_CALL |
| Generation fails (LLM error) | Return error; do NOT cache; invalidate single-flight lock |

**Principle**: Correctness > Availability. A layer that cannot execute safely is skipped, not approximated.

---

## 2. The 3-Tier Cache Hierarchy (EXISTING — 2.x Compatible)

```mermaid
flowchart TD
    Q(["Incoming Query + Context + Metadata"]) --> L1{"L1: Exact Key Match<br/>(Redis / SQLite)"}
    L1 -- Hit (<1ms) --> R1["Return Exact Match Response"]
    L1 -- Miss --> L2{"L2: Semantic Vector Match<br/>(Qdrant / LanceDB)<br/>Cosine Sim >= 0.85"}
    L2 -- Sim Matched --> G2{"Metadata Hard Gate<br/>(Entity/Quarter/Topic)"}
    G2 -- Pass (~25ms) --> R2["Return L2 Semantic Response"]
    G2 -- Conflict --> L3
    L2 -- Below Thresh --> L3{"L3: Dual-Context Search<br/>Query Vector + Context Vector"}
    L3 -- Intersection Matched --> G3{"Context Hard Gate<br/>(Merged Metadata Check)"}
    G3 -- Pass (~45ms) --> R3["Return L3 Context Response"]
    G3 -- Conflict / Miss --> MISS["MISS: Fallback to LLM / RAG<br/>(Async Population of L1, L2, L3)"]
```

### Layer 1: Exact Hash Matching (L1)
- **Engine Backends**: Redis (Distributed) or SQLite (Embedded)
- **Key Derivation**: `tenant_id:l1:sha256(normalize(query) + "|" + model_fingerprint + "|" + prompt_version + "|" + context_hash + "|" + canonical_meta_suffix(meta))`
- **Latency**: `< 1ms`
- **Purpose**: Instantly resolves exact repetitive queries. The metadata canonical suffix guarantees that identical query text executed across different entities (e.g. "What was Q1 revenue?" for MSFT vs AAPL) generates separate isolated slots.
- **Identity Components (ALL REQUIRED per C4)**:
  - `tenant_id` — Cross-tenant isolation (CRITICAL)
  - `normalized_query` — Case/whitespace normalized query text
  - `model_fingerprint` — SHA256 of model config + tokenizer + provider config (12-char prefix)
  - `provider` — openai, anthropic, ollama, gemini, etc.
  - `prompt_version` — Semver or content hash of rendered system prompt + few-shots
  - `context_hash` — SHA256(context)[:16] if context provided, else `empty`
  - `canonical_meta_suffix` — Sorted k=v pairs for all non-None metadata fields (entity, quarter, topic, etc.)
- **Under exactly what conditions is an L1 exact result safe to reuse?**
  > An L1 cached response is safe to reuse IF AND ONLY IF all of the following hold:
  > 1. Same tenant (`tenant_id` identical)
  > 2. Same normalized query text
  > 3. Same model fingerprint (model weights + tokenizer + config)
  > 4. Same provider (OpenAI vs Anthropic vs Ollama etc.)
  > 5. Same prompt template version (system prompt + few-shots + instructions)
  > 6. Same context hash (empty context ≠ no context)
  > 7. All gated metadata fields match (entity, quarter, topic, and any custom `required_in_gate` fields)
  > 8. The cached entry was generated with deterministic params (temperature=0, enforced at write time)

### Layer 2: Single-Turn Semantic Matching (L2)
- **Engine Backends**: Qdrant (Distributed) or LanceDB (Embedded)
- **Vector Model**: `BAAI/bge-small-en-v1.5` (FastEmbed local ONNX runtime, 384 dimensions)
- **Latency**: `~15 - 30ms`
- **Matching Rule**: Cosine similarity $\ge 0.85$ subject to the **Metadata Hard Gate**.
- **Purpose**: Catches paraphrased, reordered, or synonymous queries asking the exact same question.

### Layer 3: Dual-Context Vector Matching (L3)
- **Engine Backends**: Qdrant (named vector collections) or LanceDB
- **Vectors**: Dual dense embeddings: $v_{\text{query}}$ (dim 384) + $v_{\text{context}}$ (dim 384)
- **Latency**: `~30 - 50ms`
- **Matching Rule**: Finds documents in the intersection of top query hits and top context hits, gated against both query metadata and context metadata.
- **Purpose**: Resolves conversational and context-dependent queries (e.g., "What were their risk factors?" when the context is "Walmart 2026-Q2").

---

## 3. The Metadata Guardrail (0% False-Hit Baseline)

Standard vector similarity caches fail in high-precision domains because embedding vectors for opposite entities or different financial quarters are cosine-adjacent (e.g., "What was Microsoft's revenue in Q1?" is over 93% cosine similar to "What was Apple's revenue in Q1?").

ICO-Cache enforces hard metadata gating across all three layers:
- **Centralized Extraction**: `extract_fields()` extracts `entity`, `quarter`, and canonicalized `topic` (`revenue`, `R&D`, `margins`, etc.) from incoming queries and contexts.
- **Hard Gate Rule**: If both the incoming request and the cached record contain a value for an extracted field, and those values differ, the hit is **unconditionally blocked** regardless of vector cosine similarity score.
- **CRITICAL_FIELDS** (always enforced, never fuzzy): `tenant_id`, `model`, `provider`, `entity`, `quarter`, `prompt_version`, `tool_version`, `collection_version`, `embedding_model_version`, `reranker_version`, `authz_version`
- **Result**: Evaluated on benchmark near-miss sets with 0 / 100 false hits (0% false hit rate).
- **Serving Gate**: beyond the metadata guard, `serve_threshold` (default `0.90`) blocks L2/L3 serves when cosine similarity to the logged question falls below the gate — guarding against near-identical but differently-worded questions that share metadata. L2/L3 re-serves also expire via `l2_l3_ttl` (default 3600 s) and L2 entries bind to the `in_context` they were written under.

---

## 4. Observability & Profiling

- **Embedded Mode**: Uses `structlog` to emit structured JSON/key-value logs covering each layer's latency and hit/miss decisions.
- **Distributed Mode**: Integrates with FastAPI request middleware (`X-Request-ID`), OpenTelemetry, and Langfuse tracing.

---

## 5. Phase 3 Extension: 10-Layer Intelligent Optimization Layer

> **Reference**: See `docs/PHASE3_ARCHITECTURE.md` for full Phase 3 target architecture including L0, L4-L9, DecisionEngine, Project Memory, Session Memory, and integration patterns.

### 5.1 Layer Specifications (Phase 3)

| Layer | Name | Key Structure | Hard Gates | TTL | Storage | Latency Target |
|-------|------|---------------|------------|-----|---------|----------------|
| **L0a** | **Deterministic Computation Cache** | `hash(fn_name + args + fn_version + env_hash)` | Function version, input hash, env hash | ∞ (content-addressable) | Hot Store (Redis/SQLite) | <1ms |
| **L0b** | **Embedding Cache** | `emb:{model_fingerprint}:{text_hash}` | Model fingerprint, text hash | 30 days | Vector Store (LanceDB/Qdrant) | <5ms |
| **L1** | **Exact Prompt Match** | `tenant_id:l1:sha256(norm(query) + "|" + model_fp + "|" + prompt_ver + "|" + ctx_hash + "|" + canon_meta)` | tenant_id, model_fingerprint, provider, prompt_version, context_hash, entity, quarter, topic | 1h default | Hot Store (Redis/SQLite) | <1ms |
| **L2** | **Semantic Query Match** | Vector(query_emb) | Metadata hard gate + semantic threshold (≥0.85) | 24h | Vector Store (Qdrant/LanceDB) | ~15ms |
| **L3** | **Context-Aware Match** | Vector(query_emb) + Vector(context_emb) | Merged query+context metadata + dual thresholds | 24h | Vector Store (Qdrant/LanceDB) | ~30ms |
| **L4** | **Retrieval Result Cache** | `hash(query_emb + filter + top_k + collection_version)` | Collection version, filter equivalence | 1h | Hot Store (Redis) | <5ms |
| **L5** | **Context Window Cache** | `hash(sorted(chunk_hashes) + template_ver + token_budget + model)` | Chunk versions, template version, token budget | 1h | Hot Store (Redis) | <5ms |
| **L6** | **Tool Execution Cache** | `hash(tool_name + args + tool_version)` | Tool version, arg hash, idempotency key | Configurable | Hot Store (Redis) | <1ms |
| **L7** | **Project/Repository Memory** | `project_id + file_hash + symbol_path` | Git commit SHA, file hash, dependency graph | ∞ (git-backed) | Vector Store + Durable Store | ~10ms |
| **L8** | **Session Memory** | `session_id + turn_id + scope` | Session isolation, user consent | Session TTL | Hot Store (Redis) | <1ms |
| **L9** | **LLM Response Cache** | `hash(full_prompt + model + provider + params + prompt_version)` | Model, provider, params, prompt version | 1h | Hot Store (Redis) | <1ms |

### 5.2 Hard Gates Per Layer (Phase 3)

| Layer | Required Gates | Confidence Model |
|-------|----------------|------------------|
| L0a | Function version, input hash, env hash | 1.0 (deterministic) |
| L0b | Embedding model fingerprint, text hash | 0.99 (version-pinned) |
| L1 | tenant_id, model_fingerprint, provider, prompt_version, context_hash, entity, quarter, topic | 1.0 (exact) |
| L2 | Metadata filter keys + semantic_threshold | 0.85-0.95 (adaptive) |
| L3 | Merged query+context metadata + dual thresholds | 0.75-0.90 |
| L4 | Collection version + filter equivalence | 0.95 (retrieval determinism) |
| L5 | Chunk content hashes + template version + token_budget | 0.90 |
| L6 | Tool version + arg hash + idempotency | 1.0 (if idempotent) |
| L7 | Git commit SHA + file hash + dependency closure | 1.0 (git-verified) |
| L8 | Session ID + user consent flag | 0.8 (contextual) |
| L9 | Model + provider + params + prompt_version | 0.95 |

---

### 5.3 L0a: Deterministic Computation Cache — Detailed Specification (Resolves C3)

**Purpose**: Cache mathematically verifiable deterministic function results where identical inputs **always** produce identical outputs (1.0 confidence). Examples: token counting, hash computation, AST parsing, schema validation, prompt template rendering, JSON serialization.

**Input**: 
- Function name/identifier (stable, versioned)
- Function arguments (serialized deterministically)
- Function version (semver or content hash of function body)
- Environment hash (Python version, dependency versions, OS) — optional but recommended for cross-env reproducibility

**Output**: Serialized function return value (bytes)

**Identity**: `fn_name + args_hash + fn_version + env_hash` — content-addressable, collision-resistant

**Key Format**: `det:{fn_name}:{fn_version}:{args_hash}:{env_hash}` (Hot Store string key)

**TTL**: Infinite (content-addressable — never expires unless explicitly invalidated). Optional TTL for memory pressure (e.g., 30 days LRU).

**Storage**: **Hot Store (Redis primary, SQLite embedded fallback)** — sub-millisecond latency, high throughput, TTL support for LRU eviction.

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
- On Hot Store failure: degrade to direct function execution (no cache)
- On serialization failure: log error, execute function, do not cache
- **Never** return stale result — key mismatch = miss

---

### 5.4 L0b: Embedding Cache — Detailed Specification (Resolves C3)

**Purpose**: Cache embedding vectors for text inputs to avoid redundant embedding model calls. Same text + same embedding model version = same vector (~0.99 confidence). Model upgrades change outputs → must not reuse across versions.

**Input**:
- Text string (query, context, document chunk, etc.)
- Embedding model identifier + fingerprint (e.g., `bge-small-en-v1.5@sha256:abc123...`)
- Optional: embedding parameters (normalize, truncate, pooling) — folded into model fingerprint

**Output**: Embedding vector (float32 array, typically 384-1536 dimensions)

**Identity**: `model_fingerprint + text_hash` — model-version-pinned

**Key Format**: `emb:{model_fingerprint}:{sha256(text)[:16]}` (Vector Store table key)

**TTL**: 30 days (embeddings are expensive to recompute but model upgrades invalidate). Configurable per model.

**Storage**: **Vector Store (LanceDB primary, Qdrant distributed)** — columnar storage optimized for vector payloads, efficient bulk reads, supports metadata filtering.

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
- On Vector Store failure: degrade to direct embedder call
- On dimension mismatch: treat as miss (model changed)
- **Never** return embedding from different model version

---

### 5.5 Why Embeddings Are Not Ordinary Deterministic Computation (Resolves C3)

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

### 5.6 L1 Exact Prompt Match — Complete Key Contract (Resolves C4)

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

---

## 6. Component Ownership (Resolves C2)

Per **ADR-002**, ownership is split between DecisionEngine (policy) and CacheEngine (storage/execution):

| Component | Owner | Responsibilities |
|-----------|-------|------------------|
| **DecisionEngine** | Architect + Cache Engineer | Evaluate reuse opportunity, policies, hard gates, confidence; select reuse action; determine fallback; explain decision; register layer implementations |
| **CacheEngine** | Cache Engineer | Cache storage interaction (Redis, SQLite, Qdrant, LanceDB); L1/L2/L3 lookup/write; single-flight deduplication; backend abstraction; invalidation execution; stable `resolve()` API |
| **Project Memory (L7)** | RAG Engineer + Agent Memory Engineer | Repository analysis, symbol extraction, dependency graph, incremental updates, git-verified knowledge |
| **Session Memory (L8)** | Integration Engineer | Conversation history, fact extraction, consent management, TTL enforcement |
| **RAG Integration** | RAG Engineer | Retrieval cache (L4), context window cache (L5), RAG pipeline wrapping |
| **Observability** | Observability Engineer | Decision tracing, token/cost metrics, gate evaluation counters, confidence histograms |
| **Invalidation** | Cache Engineer | Redis Streams publisher, consumer protocol, cross-layer invalidation |
| **Security** | Security Engineer | Write validation, redaction pipeline, audit logging, tenant isolation enforcement |
| **Storage Abstraction** | Cache Engineer | `HotStore`, `VectorStore`, `DurableStore`, `Embedder` interfaces |
| **SDKs/API/Proxy** | Integration Engineer | `optimize()` high-level API, REST endpoints, LLM Proxy, MCP server |

---

## 7. Key Interfaces & Contracts

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
    
    # PROPOSED — storage abstraction accessors
    @property
    def hot_store(self) -> BaseHotStore: ...
    @property
    def vector_store(self) -> BaseVectorStore: ...
    @property
    def durable_store(self) -> BaseDurableStore: ...
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

### ReuseDecision (Output)
```python
@dataclass
class ReuseDecision:
    action: ReuseAction  # EXACT_REUSE, SEMANTIC_REUSE, CONTEXT_REUSE, 
                         # MEMORY_RETRIEVAL, RAG_RETRIEVAL, 
                         # PARTIAL_RECOMPUTE, FULL_LLM_CALL
    confidence: float    # 0.0 - 1.0
    layer: str           # Which layer hit (L0-L9)
    cache_key: Optional[str]
    reasoning: str       # Human-readable explanation
    required_recompute: List[str]  # What must be recomputed if PARTIAL
    metadata_gates_passed: List[str]
    metadata_gates_failed: List[str]
    fallback_reason: Optional[str]  # If not REUSE
```

---

## 8. Storage Abstraction Layer (Resolves C7)

The architecture consolidates 7+ physical backends into **3 logical storage abstractions**. Each abstraction defines a clear contract; physical backends implement the contract.

### 8.1 Logical Storage Abstractions

| Logical Abstraction | Responsibility | Latency Target | Durability | Consistency Model | Multi-Tenancy |
|---------------------|----------------|----------------|------------|-------------------|---------------|
| **Hot Store** (Exact/Operational Cache) | L0a deterministic fn cache, L1 exact prompt cache, L4 retrieval cache, L5 context window cache, L6 tool cache, L8 session memory, L9 LLM response cache, invalidation events, prompt template registry | <1ms (p99 <5ms) | Optional (TTL-based eviction acceptable) | Eventual (async replication OK); read-after-write for single-flight | Key prefix `tenant_id:`; Redis: key pattern; SQLite: row tenant_id column |
| **Vector Store** (Semantic/Vector Cache) | L0b embedding cache, L2/L3 semantic/context cache, L7 project memory vectors, RAG corpus | ~5-50ms (p99 <100ms) | Required (persisted to disk) | Strong for metadata filters; eventual for vector index refresh | Collection-per-tenant (default) OR shared collection + payload filter |
| **Durable Store** (Relational/Metadata Memory) | L7 project memory metadata (files, symbols, dependencies, git refs), ingestion job queue, audit logs, analytics/metrics aggregates | ~1-10ms | Required (ACID) | Strong (serializable for metadata) | Row-level tenant_id; PostgreSQL RLS or SQLite per-tenant file |

**Ownership**:
- **Hot Store**: Cache Engineer — all exact-match, TTL-based, high-throughput cache layers
- **Vector Store**: Cache Engineer + RAG Engineer — all vector search, embedding cache, semantic layers
- **Durable Store**: RAG Engineer + Agent Memory Engineer — project memory metadata, ingestion, audit

### 8.2 Physical Backend Mapping

| Physical Backend | Implements Abstraction | Deployment Mode | Collections/Tables |
|------------------|------------------------|-----------------|-------------------|
| **Redis** | Hot Store (primary) | Distributed | Keys: `{tenant}:l1:*`, `{tenant}:l4:*`, `{tenant}:l5:*`, `{tenant}:l6:*`, `{tenant}:l8:*`, `{tenant}:l9:*`, `inv:*`, `prompt:*` |
| **SQLite** | Hot Store (embedded fallback) + Durable Store (embedded) | Embedded | Tables: `cache_l1`, `cache_l4`, `cache_l5`, `cache_l6`, `cache_l8`, `cache_l9`, `invalidation_events`, `project_files`, `project_symbols`, `project_deps`, `ingestion_jobs`, `audit_log` |
| **Qdrant** | Vector Store (primary) | Distributed | Collections: `{tenant}_l2_cache`, `{tenant}_l3_cache`, `{tenant}_l0b_embeddings`, `{tenant}_l7_vectors`, `{tenant}_ico_corpus` |
| **LanceDB** | Vector Store (embedded) + Durable Store (embedded, columnar) | Embedded | Tables: `{tenant}_l2_cache`, `{tenant}_l3_cache`, `{tenant}_l0b_embeddings`, `{tenant}_l7_vectors`, `{tenant}_ico_corpus`, `project_metadata` |
| **PostgreSQL** | Durable Store (distributed) | Distributed | Tables: `project_files`, `project_symbols`, `project_dependencies`, `git_refs`, `ingestion_jobs`, `audit_log`, `prompt_templates` (with RLS) |
| **Filesystem** | (Not a store) — LanceDB data files, document uploads | Local/Volume | `./lancedb/`, `INGEST_ROOT/uploads/` |

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

### 8.4 Duplication Elimination (vs EXISTING)

| Existing Duplication | Resolution |
|---------------------|------------|
| L1 in Redis + SQLite | **Hot Store** unified interface; Redis for distributed, SQLite for embedded |
| L2/L3 in Qdrant + LanceDB | **Vector Store** unified interface; Qdrant for distributed, LanceDB for embedded |
| RAG corpus in Qdrant + L2/L3 in Qdrant | Separate collections; shared Vector Store client |
| Embeddings recomputed for L2/L3/RAG | **L0b (Vector Store)** caches embeddings by `emb:{model_fingerprint}:{text_hash}` |
| Project metadata in LanceDB + SQLite | **Durable Store** unified interface; LanceDB columnar for embedded, PostgreSQL for distributed |

---

## 9. Migration Strategy (Resolves C8)

Per **ADR-012**, 2.x → 3.0 is a **clean-break migration with explicit invalidation**:

- **Existing 2.x cache entries CANNOT be safely reused** — key formats fundamentally changed (model_fingerprint, provider, prompt_version, collection_version, tenant_id in all keys)
- **All 2.x cache data MUST be purged on upgrade** — enforced by migration script `ico-cache migrate purge-2x-cache`
- **2.x APIs preserved** — `CacheEngine.resolve()`, `resolve_or_generate()`, `invalidate()` work unchanged
- **Feature flags gate all Phase 3 layers** — default OFF, enable incrementally
- **Rollback is instant** — 2.x namespaces preserved during canary; flip feature flag to revert

See `docs/adr/ADR-012-migration-strategy-2x-to-30.md` for complete details.

---

## 9. Architectural Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **False cache hits** | Medium | Critical | Hard gates on CRITICAL_FIELDS; confidence thresholds; adversarial testing |
| **Stale project memory** | High | High | Git commit SHA in every query; incremental re-analysis; staleness metrics |
| **Cache stampede** | Medium | High | Single-flight (EXISTING); probabilistic early expiration |
| **Memory bloat (L7/L8)** | Medium | Medium | TTL + LRU + git-backed pruning; max tokens per session |
| **Cross-tenant leakage** | Low | Critical | Collection isolation default; payload filter defense-in-depth; integration tests |
| **Prompt injection via cache** | Low | High | Never cache raw user input; sanitize; prompt_version in keys |
| **Complexity explosion** | High | Medium | Phased rollout; feature flags per layer; clear ownership (ADR-002) |
| **Vector store consistency** | Medium | High | Quorum reads; async replication lag monitoring |
| **Embedding model drift** | Medium | Medium | Model version in all keys; re-embed on version change |
| **Distributed invalidation lag** | Medium | Medium | Redis Streams + worker; eventual consistency acceptable for cache |

---

*This document reflects the authoritative architecture as of 2026-10-06, incorporating resolutions for Phase 3 Architecture Review blocking conditions C1, C2, C3, C4, C7, and C8.*