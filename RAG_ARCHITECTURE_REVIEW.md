# RAG Engineer Review: Phase 3 Architecture Design

**Reviewer**: RAG Engineer Agent  
**Date**: 2026-10-06  
**Documents Reviewed**:
- `docs/PHASE3_ARCHITECTURE.md` (Sections 5, 6, and related)
- `TECHNICAL_ANALYSIS_REPORT.md` (Sections 1, 2, 4)
- `packages/ico-cache-py/src/ico_cache/rag/pipeline.py` (RAGPipeline)
- `packages/ico-cache-py/src/ico_cache/core/cache_engine.py` (CacheEngine)

---

## Executive Summary

The Phase 3 architecture proposes a 10-layer cache hierarchy (L0–L9) with an Intelligent Decision Engine. This review focuses on **RAG-specific concerns**: embedding cache integration, retrieval/context caching correctness, RAGPipeline integration patterns, versioning/identity requirements, and stale result prevention.

**Overall Assessment**: The design is ambitious and well-structured, but **critical gaps exist in identity/correctness guarantees for L4/L5** that could cause silent cache corruption in production RAG workloads. The current `RAGPipeline` implementation lacks the metadata needed to safely populate L4/L5 keys.

---

## 1. Embedding Cache (L0) Integration with RAG

### Current State (from TECHNICAL_ANALYSIS_REPORT.md)

> **Issue #1 (P0)**: "No embedding cache — every L2/L3 lookup re-computes embeddings"  
> **Cross-Analysis**: "L3 calls embedder 2x (query+context), RAG calls 1x (retrieval) = 3 embeddings per MISS"

### Phase 3 Proposal (Section 2, 8)

| Layer | Key Structure | Storage |
|-------|---------------|---------|
| L0 | `hash(fn_name + args + version + env_hash)` | Redis/SQLite |

**Embedding Cache Key (proposed in Section 8)**:
```
Redis hash: `emb:{model_version}:{text_hash}` → vector bytes
```

### RAG Integration Points (3 Embeddings per L3 MISS)

| Embedding | Current Call Site | L0 Cacheable? | Key Components Needed |
|-----------|-------------------|---------------|----------------------|
| Query (L2) | `cache_engine.py:288` | Yes | `query_text + model_version + embedder_config_hash` |
| Query (L3) | `cache_engine.py:352` | Yes | Same as L2 |
| Context (L3) | `cache_engine.py:353` | Yes | `context_text + model_version + embedder_config_hash` |
| Query (RAG retrieval) | `pipeline.py:62` | Yes | Same as L2 |

### Findings

| Concern | Assessment |
|---------|------------|
| **Model version in key** | ✅ Phase 3 includes `model_version` in L0 key (`emb:{model_version}:{text_hash}`) |
| **Embedder config hash** | ⚠️ **Missing** — FastEmbedder/SentenceTransformer config (pooling, normalization, truncation) affects output. Must include `embedder_config_hash` in key. |
| **Dimensionality** | ⚠️ Implicit via model_version, but explicit `embedding_dim` in key adds safety |
| **RAG retrieval embedding** | ✅ Can share same L0 cache — same embedder, same query text |
| **Cache invalidation** | ✅ Model version change → auto-miss (key includes version) |
| **Embedder swap** | ✅ Different embedder class = different model_version namespace |

### Recommendation

```python
# L0 Embedding Cache Key should be:
emb:{embedder_class}:{model_version}:{embedder_config_hash}:{text_hash}
# Where embedder_config_hash = hash(json.dumps({
#     "pooling": "mean", "normalize": true, "max_length": 512, ...
# }))
```

---

## 2. Retrieval Cache (L4) Design

### Phase 3 Proposal (Section 2, 5, 6)

| Property | Value |
|----------|-------|
| **Key** | `hash(query_embedding + metadata_filter + top_k + collection_version)` |
| **Value** | `[{chunk_id, text, score, metadata}, ...]` |
| **TTL** | 1h |
| **Storage** | Redis |
| **Invalidation** | Collection version bump on ingest/delete |

### Current Implementation Reality (pipeline.py)

```python
async def retrieve(self, query: str, meta: Optional[dict] = None, 
                   tenant_id: str = "default", top_k: int = 30, **kwargs) -> List[dict]:
    dense_vec = await _run_sync(self.dense_embedder.embed, query)
    # Builds filter from self.metadata_filter_keys + meta
    # Searches tenant-specific collection
    # Returns raw payloads (dicts with text, meta, source_file, page_or_section, etc.)
```

### Identity Analysis: What L4 Key MUST Capture

| Identity Factor | In L4 Key? | Required? | Risk if Missing |
|-----------------|------------|-----------|-----------------|
| Query embedding | ✅ `query_embedding` | Yes | Different queries collide |
| Metadata filter | ✅ `metadata_filter` | Yes | Cross-entity/quarter contamination |
| top_k | ✅ `top_k` | Yes | Different result sets |
| Collection version | ✅ `collection_version` | Yes | **Critical** — stale docs after ingest |
| **Embedding model/version** | ❌ | **Yes** | Different embedder → meaningless vectors |
| **Embedding dimensions** | ❌ | **Yes** | Dimension mismatch = silent corruption |
| **Chunking configuration** | ❌ | **Yes** | Different chunking = different chunks |
| **Reranker presence/version** | ❌ | **Yes** | Reranked vs non-reranked results differ |
| **Retrieval score_threshold** | ❌ | Yes | Different thresholds = different results |
| **Vector store index params** | ❌ | Yes | HNSW ef_search, quantization affect results |
| **Tenant isolation mode** | ❌ | Yes | Collection vs payload mode = different results |
| **Distance metric** | ❌ | Yes | Cosine vs Dot vs Euclidean |

### Critical Gaps in Proposed L4 Key

```python
# PROPOSED (INSUFFICIENT):
L4_key = hash(query_emb + filter + top_k + collection_version)

# REQUIRED (MINIMUM):
L4_key = hash(
    query_emb +
    filter +
    top_k +
    collection_version +
    embedder_fingerprint +        # model + config + dims
    chunking_fingerprint +        # strategy + size + overlap
    reranker_fingerprint +        # model + version or "none"
    retrieval_config_fingerprint  # threshold, distance_metric, hnsw_params
)
```

### Can Cached Retrieval Results Be Safely Reused?

**Answer: Only if ALL identity factors are captured in the key.**

Current design **fails** this test. The proposed L4 key misses 7+ critical identity factors. Without them:
- Swapping embedder (e.g., `BAAI/bge-small` → `sentence-transformers/all-MiniLM-L6-v2`) returns stale vectors matched against new queries → **semantic nonsense**
- Changing chunk size (512 → 1024) returns chunks that no longer exist in corpus → **missing/ghost citations**
- Enabling/disabling reranker changes result order and content → **different context fed to LLM**

---

## 3. Context Window Cache (L5) Design

### Phase 3 Proposal (Section 2, 5)

| Property | Value |
|----------|-------|
| **Key** | `hash(sorted(chunk_ids) + template_version + token_budget + model)` |
| **Value** | `{context_string, token_count, chunk_mapping}` |
| **TTL** | 1h |
| **Storage** | Redis |
| **Invalidation** | Any chunk_id version change, template change |

### Identity Analysis: What L5 Key MUST Capture

| Identity Factor | In L5 Key? | Required? | Risk if Missing |
|-----------------|------------|-----------|-----------------|
| Retrieved chunk IDs | ✅ `sorted(chunk_ids)` | Yes | Different chunks = different context |
| Chunk content versions | ❌ | **Yes** | Chunk updated → stale context |
| Template version | ✅ `template_version` | Yes | Template change = different prompt |
| Token budget | ✅ `token_budget` | Yes | Different budget = different truncation |
| Model | ✅ `model` | Partially | Model affects tokenizer → different truncation |
| **Tokenizer/encoding** | ❌ | **Yes** | Different tokenizer = different token counts |
| **Context construction logic** | ❌ | **Yes** | Prompt template changes (citations format, ordering) |
| **Chunk ordering strategy** | ❌ | Yes | Reranked vs original order = different context |
| **Citation format** | ❌ | Yes | `[1]` vs `[source_file:page]` |

### Current RAGPipeline Context Construction (pipeline.py:125-144)

```python
context = "\n\n".join([f"[{p.get('page_or_section','')}] {p.get('text','')}" for s, p in top_chunks])
citations = [p.get("source_file", "") for s, p in top_chunks]
prompt = f"""Answer using the provided context below.
Context:
{context}

Question: {query}
Answer:"""
```

### Findings

| Concern | Assessment |
|---------|------------|
| **Chunk versioning** | ❌ **Critical gap** — `chunk_ids` alone insufficient; need `chunk_content_hash` or `chunk_version` |
| **Template versioning** | ✅ Proposed but `PromptTemplate` registry not implemented |
| **Tokenizer alignment** | ⚠️ Model in key helps, but tokenizer can differ for same model (e.g., `gpt-4o` vs `gpt-4o-2024-08-06`) |
| **Construction logic version** | ❌ Missing — any change to prompt template format invalidates cache |
| **Citation stability** | ⚠️ Citation format hardcoded; changes would corrupt L5 |

### Can L5 Context Be Safely Reused?

**Answer: Only with chunk content hashes in key.**

Current design uses `chunk_ids` but **chunks are mutable** in vector store (re-ingestion updates payload). Without `chunk_content_hash` in L5 key:
- Document updated → chunk text changes → L5 returns stale context with new chunk_ids → **hallucinated citations**

---

## 4. RAGPipeline Integration Patterns

### Phase 3 Patterns (Section 6)

| Pattern | Description | Coupling |
|---------|-------------|----------|
| **A: SDK Wrapper** | `cache.optimize(query, generate_fn=rag.query)` | Low — wraps existing RAG |
| **B: Proxy Mode** | Sidecar/gateway between client and RAG API | Medium — requires API standardization |
| **C: MCP** | Standard protocol exposure | Low — protocol-based |
| **D: Library Integration** | Embed `CacheEngine` inside RAG pipeline | High — modifies RAG internals |

### Current RAGPipeline Coupling

```python
# pipeline.py:95-184 — generate() calls retrieve() internally
async def generate(self, query: str, meta: Optional[dict] = None, 
                   tenant_id: str = "default", llm_generate_fn=None, model: Optional[str] = None):
    retrieved_payloads = await self.retrieve(query, meta, tenant_id=tenant_id, top_k=30)
    # ... rerank, build context, call LLM
```

### Integration Analysis

| Pattern | L4/L5 Access | Pros | Cons |
|---------|--------------|------|------|
| **A: SDK Wrapper** | ❌ Cannot cache retrieval/context — only caches final LLM response (L9) | Non-invasive | Misses 60%+ of optimization (retrieval + context) |
| **B: Proxy Mode** | ❌ Same as A — only sees full request/response | Transparent | Same limitation |
| **C: MCP** | ⚠️ Possible via `tools/cache_retrieval` | Standard | Requires MCP adoption |
| **D: Library Integration** | ✅ Full L4/L5 access via `RAGIntegration` class | Maximum optimization | Requires RAG framework cooperation |

### Critical Finding

**Pattern A (SDK Wrapper) — the "Recommended" pattern — CANNOT leverage L4/L5.**

The `generate_fn` callback is a black box. The cache only sees:
- Input: `query, context, meta`
- Output: `generated_response`

It **cannot** intercept:
- Retrieval results (for L4)
- Constructed context (for L5)
- Embeddings (for L0)

To enable L4/L5, the RAG pipeline **must expose retrieval and context construction as separate callable stages** — i.e., Pattern D (Library Integration) or a modified Pattern A with structured callbacks.

### Recommended Integration Interface

```python
# Phase 3 proposes (Section 13):
class RAGIntegration:
    async def retrieve_cached(self, query: str, filters: dict, top_k: int) -> Optional[List[Chunk]]
    async def store_retrieval(self, query: str, filters: dict, chunks: List[Chunk]) -> None
    async def construct_context_cached(self, chunks: List[Chunk], template: str, 
                                        token_budget: int, model: str) -> Optional[str]
    async def store_context(self, chunk_ids: List[str], template: str, 
                            token_budget: int, model: str, context: str) -> None

# RAGPipeline MUST be refactored to support:
class RAGPipeline:
    async def retrieve_only(self, query, meta, tenant_id, top_k) -> List[Chunk]
    async def rerank(self, query, chunks) -> List[Chunk]
    async def construct_context(self, chunks, template, token_budget, model) -> str
    async def generate_from_context(self, context, query, model) -> str
```

---

## 5. Collection Versioning & Document Versioning

### Phase 3 Proposal (Section 2, 5, 8)

| Layer | Versioning Mechanism |
|-------|---------------------|
| L4 | `collection_version` in key → auto-miss on corpus change |
| L5 | `chunk_ids` + implicit version via chunk content hash |
| L7 | `commit_sha` + `file_hashes` (git-backed) |

### Current Implementation

| Component | Versioning |
|-----------|------------|
| Qdrant/LanceDB collections | ❌ No version tracking |
| Document chunks | ❌ No content hash stored in payload |
| Ingestion | `async_ingest.py` upserts chunks — no version bump |
| Invalidation | `CacheEngine.invalidate()` deletes by filter — manual |

### Gap Analysis

| Requirement | Current | Needed |
|-------------|---------|--------|
| **Collection version** | ❌ | Monotonic counter or hash of (doc_count, last_ingest_timestamp, schema_version) |
| **Chunk content hash** | ❌ | Store `sha256(chunk_text)` in payload; use for L5 key |
| **Document version** | ❌ | Track `doc_id + doc_hash + chunk_count` per document |
| **Schema version** | ❌ | Metadata schema changes must bump collection version |
| **Automatic version bump** | ❌ | Ingestion pipeline must increment collection version |

### Implementation Sketch

```python
# In vector store payload for each chunk:
{
    "text": "...",
    "meta": {...},
    "chunk_hash": "sha256(text)",      # NEW: for L5 invalidation
    "doc_id": "doc_123",
    "doc_version": 5,                   # NEW: document version
    "collection_version": 42,           # NEW: collection-level version
    "ingested_at": "2026-10-06T12:00:00Z"
}

# L4 key includes collection_version (from collection metadata)
# L5 key includes chunk_hash for each chunk_id
```

---

## 6. Chunk Identity & Embedding Model Identity

### Current Chunk Identity (pipeline.py:127-137)

```python
self.last_retrieved_chunks = [
    {
        "source": p.get("source_file", ""),
        "section": p.get("page_or_section", ""),
        "loader_type": p.get("loader_type") or p.get("loader") or "text",
        "extraction_method": p.get("extraction_method") or ...,
        "metadata": p.get("meta") if isinstance(p.get("meta"), dict) else {},
        "content": p.get("text", "")[:300],
    }
    for s, p in top_chunks
]
```

**No stable chunk ID** — relies on `source_file + page_or_section` which is not unique across re-ingestions.

### Required Chunk Identity

```python
@dataclass
class ChunkIdentity:
    chunk_id: str              # Stable UUID (generated at ingestion)
    content_hash: str          # sha256(text) — changes when text changes
    doc_id: str                # Stable document identifier
    doc_version: int           # Incremented on document update
    chunk_index: int           # Position within document
    embedding_model: str       # Model that produced the vector
    embedding_dim: int         # Vector dimensions
    chunking_config_hash: str  # Hash of chunking params (size, overlap, strategy)
    ingested_at: datetime
    collection_version: int    # Corpus version at ingestion time
```

### Embedding Model Identity

```python
@dataclass
class EmbedderFingerprint:
    embedder_class: str        # e.g., "FastEmbedder", "SentenceTransformerEmbedder"
    model_name: str            # e.g., "BAAI/bge-small-en-v1.5"
    model_version: str         # Model card version or commit
    config_hash: str           # Hash of {pooling, normalize, max_length, ...}
    dimensions: int            # Output vector size
```

**Every vector in vector store must carry `embedding_model_fingerprint`** — otherwise cross-embedder search is meaningless.

---

## 7. Retrieval Configuration Caching

### Current Retrieval Config (RAGPipeline.__init__)

```python
def __init__(
    self,
    dense_embedder: BaseEmbedder,
    vector_store: BaseVectorStore,
    metadata_filter_keys: Optional[List[str]] = None,
    filtered_threshold: float = -8.50,
    unfiltered_threshold: float = 0.10,
    collection_name: str = "rag_corpus",
    reranker: Any = None,
    # ... LLM params
):
```

### Config Factors Affecting Retrieval Results

| Config | Affects Results? | Must Be in L4 Key? |
|--------|------------------|-------------------|
| `metadata_filter_keys` | Yes — determines which filters applied | ✅ |
| `filtered_threshold` / `unfiltered_threshold` | Yes — score cutoff | ✅ |
| `collection_name` | Yes — different corpus | ✅ (via collection_version) |
| `reranker` (presence + model) | Yes — reorders + filters | ✅ |
| `top_k` (passed at call time) | Yes — result count | ✅ |
| `vector_store.search` params (`using`, `score_threshold`) | Yes — search behavior | ✅ |
| `dense_embedder` (model + config) | Yes — query vector | ✅ (via embedder_fingerprint) |

### Finding

**Retrieval configuration is currently implicit in RAGPipeline instance.** No serialization, no versioning, no hash. To safely cache retrieval results (L4), the **entire retrieval configuration must be fingerprinted** and included in the L4 key.

---

## 8. Stale Retrieval Results Prevention

### Phase 3 Invalidation Strategy (Section 2)

| Layer | Invalidation Trigger | Mechanism |
|-------|---------------------|-----------|
| L4 | Corpus version change (new ingest, delete) | Collection version in key → auto-miss |
| L5 | Chunk version change, template change | Chunk hashes in key → auto-miss |

### Current Invalidation (cache_engine.py:648-714)

```python
async def invalidate(self, tenant_id: str = "default", filter_dict: Optional[dict] = None):
    # Purges L1 by prefix, L2/L3 by filter or collection delete
    # NO collection version bump
    # NO chunk-level invalidation
```

### Stale Result Scenarios

| Scenario | Current Behavior | Phase 3 Design | Gap |
|----------|------------------|----------------|-----|
| Document re-ingested (updated) | L2/L3 invalidated by filter; L4/L5 **not invalidated** | L4: collection_version bump → auto-miss<br>L5: chunk_hash change → auto-miss | **Collection version not implemented** |
| Document deleted | Same as above | Same | **Collection version not implemented** |
| Chunking strategy changed | Old chunks remain in corpus | L4: collection_version bump<br>L5: chunk_hash mismatch | **Collection version not implemented** |
| Embedder changed | New vectors incompatible with old | L0: model_version in key → auto-miss<br>L4: embedder_fingerprint in key → auto-miss | **embedder_fingerprint not in L4 key** |
| Reranker added/removed | Results differ | L4: reranker_fingerprint in key → auto-miss | **reranker_fingerprint not in L4 key** |
| Metadata schema changed | Hard gate may pass incorrectly | L4: filter equivalence check | **Schema version not in collection_version** |

### Critical Gap: **No Automatic Collection Version Bump**

The Phase 3 design assumes `collection_version` exists and increments on ingest. **Current codebase has no such mechanism.** Without it:
- L4 cache **never invalidates** on corpus changes
- Stale retrieval results served indefinitely
- **Silent corruption** — user gets cached chunks from deleted/updated documents

---

## 9. Key Questions Answered

### Q1: Can cached retrieval results be safely reused?

**Conditional YES — only if:**
1. L4 key includes: `query_embedding + filter + top_k + collection_version + embedder_fingerprint + chunking_fingerprint + reranker_fingerprint + retrieval_config_fingerprint`
2. `collection_version` is **automatically bumped** on every ingestion/deletion
3. Vector store payloads include `chunk_hash` for L5 validation
4. Hard gates enforce metadata filter equivalence (not just filter keys)

**Current design: NO — key is insufficient, versioning not implemented.**

---

### Q2: What identity is required for safe reuse?

| Layer | Minimum Required Identity |
|-------|---------------------------|
| **L0 (Embedding)** | `embedder_class + model_version + config_hash + text_hash` |
| **L1 (Exact)** | `normalized_query + canonical_meta + prompt_version + model + provider` |
| **L2 (Semantic)** | `query_embedding + metadata_filter + semantic_threshold + embedder_fingerprint` |
| **L3 (Context)** | `query_emb + context_emb + merged_metadata_filter + dual_thresholds + embedder_fingerprint` |
| **L4 (Retrieval)** | `query_emb + filter + top_k + collection_version + embedder_fingerprint + chunking_fingerprint + reranker_fingerprint + retrieval_config_fingerprint` |
| **L5 (Context Window)** | `sorted(chunk_content_hashes) + template_version + token_budget + tokenizer_fingerprint + context_construction_version` |
| **L9 (LLM Response)** | `full_rendered_prompt + model + provider + params_hash + prompt_version` |

---

### Q3: Does the L4 key (`hash(query_emb + filter + top_k + collection_version)`) capture all necessary identity?

**NO. Missing (at minimum):**
- `embedder_fingerprint` (model, config, dimensions)
- `chunking_fingerprint` (strategy, size, overlap)
- `reranker_fingerprint` (model, version, or "none")
- `retrieval_config_fingerprint` (thresholds, distance metric, HNSW params)
- `tenant_isolation_mode` (collection vs payload)

**Risk**: Silent semantic corruption when any of these change.

---

### Q4: Does the L5 key (`hash(chunk_ids + template + token_budget + model)`) capture all necessary identity?

**NO. Missing:**
- `chunk_content_hashes` (not just IDs — chunks are mutable)
- `tokenizer_fingerprint` (model ≠ tokenizer; same model can have tokenizer updates)
- `context_construction_version` (prompt template format, citation style, chunk ordering)
- `reranker_fingerprint` (affects which chunks selected and their order)

**Risk**: Stale context with updated chunks → hallucinated citations.

---

### Q5: How does the embedding cache (L0) integrate with the 3 embeddings per L3 miss?

**Current flow (3 embeddings per L3 MISS):**
```
L3 MISS → 
  1. embed(query) for L2 search          [cacheable via L0]
  2. embed(query) for L3 query vector    [cacheable via L0 — SAME as #1]
  3. embed(context) for L3 context vector [cacheable via L0]
  4. embed(query) for RAG retrieval      [cacheable via L0 — SAME as #1]
  → Total unique embeddings: 2 (query + context)
```

**With L0 embedding cache:**
```
L3 MISS →
  1. L0.get(query) → hit? use cached : embed(query) → L0.set(query)
  2. L0.get(context) → hit? use cached : embed(context) → L0.set(context)
  3. RAG retrieval uses same L0.get(query)
  → Embedding calls reduced from 3→2 (or 2→1 if context also cached)
```

**Integration requirement**: `CacheEngine` must expose `get_embedding(text)` / `set_embedding(text, vector)` that `RAGPipeline` and L2/L3 lookup both use.

---

## 10. Cross-Cutting Risks

| Risk | Severity | Description |
|------|----------|-------------|
| **Insufficient L4/L5 key identity** | 🔴 Critical | Silent cache corruption when embedder/chunking/reranker/config changes |
| **No collection versioning** | 🔴 Critical | L4/L5 never invalidate on corpus updates |
| **No chunk content hashing** | 🔴 Critical | L5 serves stale context after document updates |
| **Pattern A (SDK Wrapper) cannot use L4/L5** | 🟠 High | Recommended integration pattern misses major optimization |
| **Retrieval config not fingerprinted** | 🟠 High | L4 key cannot capture retrieval behavior |
| **Embedder config not in L0 key** | 🟠 High | Embedder config change → wrong vectors from cache |
| **Tokenizer not in L5 key** | 🟡 Medium | Token budget truncation differs across tokenizer versions |
| **No retrieval config serialization** | 🟡 Medium | Cannot reproduce retrieval behavior for debugging/audit |

---

## 11. Recommendations (Priority Order)

### P0 — Must Fix Before L4/L5 Implementation

1. **Implement collection versioning** in vector store (monotonic counter + schema hash)
2. **Add `chunk_hash` to every chunk payload** (sha256 of text content)
3. **Define `EmbedderFingerprint`** and store in vector payload + use in L0/L4 keys
4. **Define `ChunkingFingerprint`** and store in collection metadata + use in L4 key
5. **Define `RetrievalConfigFingerprint`** for RAGPipeline + use in L4 key
6. **Add automatic collection_version bump** in ingestion pipeline (`async_ingest.py`)

### P1 — Required for Correct L4/L5

7. **Extend L4 key** to include all fingerprint components
8. **Extend L5 key** to use `chunk_content_hashes` not `chunk_ids`
9. **Refactor RAGPipeline** to expose `retrieve_only()`, `construct_context()` for Pattern D integration
10. **Implement `PromptTemplate` registry** with versioning for L5/L9 keys

### P2 — Integration & Observability

11. **Add L0 embedding cache methods** to `CacheEngine` (`get_embedding`, `set_embedding`)
12. **Instrument RAGPipeline** with retrieval/context cache hooks
13. **Add token counting** to L5 context construction (for metrics)
14. **Benchmark L4/L5 hit rates** with adversarial corpus change tests

---

## 12. Files to Modify (Scope)

| File | Changes Needed |
|------|----------------|
| `packages/ico-cache-py/src/ico_cache/rag/pipeline.py` | Add `retrieve_only()`, `construct_context()`, `RetrievalConfig` dataclass, fingerprint methods |
| `packages/ico-cache-py/src/ico_cache/core/cache_engine.py` | Add L0 embedding cache, L4/L5 methods, collection version tracking |
| `packages/ico-cache-py/src/ico_cache/backends/embedding/` | Add `fingerprint()` method to `BaseEmbedder` |
| `packages/ico-cache-py/src/ico_cache/backends/vector/` | Add `collection_version` property, `chunk_hash` in payloads |
| `examples/universal_schema.py` / `financial_schema.py` | Add chunk metadata fields (`chunk_hash`, `doc_version`, `collection_version`) |
| `packages/ico-cache-py/src/ico_cache/ingestion/async_ingest.py` | Bump collection_version on ingest, compute chunk hashes |

---

## 13. Conclusion

The Phase 3 architecture provides a **strong conceptual framework** for multi-layer RAG optimization. However, the **L4/L5 key designs are insufficient for production safety** — they omit 7+ critical identity factors that would cause silent cache corruption when embedders, chunking, rerankers, or retrieval configs change.

**The current `RAGPipeline` cannot support L4/L5 via the recommended Pattern A (SDK Wrapper)** — it must be refactored to expose retrieval and context construction as separable stages (Pattern D).

**Priority**: Implement collection versioning, chunk hashing, and embedder/config fingerprinting **before** building L4/L5 cache layers. Without these foundations, L4/L5 will introduce correctness regressions that violate the design's core principle: *"Correctness > Hit Rate."*

---

*End of Review*