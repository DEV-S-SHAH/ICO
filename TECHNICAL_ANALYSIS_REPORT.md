# ICO-Cache Technical Analysis Report
## Read-Only Baseline for Phase 3 Architecture

---

## 1. Current Capability Matrix

| Capability | Exists | Partial | Missing | Evidence |
|------------|--------|---------|---------|----------|
| **Exact Cache (L1)** | ✅ | | | `CacheEngine.get_l1/set_l1` (cache_engine.py:250-275); RedisStore/SQLiteStore backends |
| **Semantic Cache (L2)** | ✅ | | | `CacheEngine.get_l2/async_write_l2` (cache_engine.py:281-331); vector search with metadata hard gate |
| **Context-Aware Cache (L3)** | ✅ | | | `CacheEngine.get_l3/async_write_l3` (cache_engine.py:337-441); dual-vector (query+context) intersection |
| **Embedding Cache** | | | ❌ | No embedding-level cache; every L2/L3 lookup calls `embedder.embed()` (cache_engine.py:288,352,353,418,419) |
| **Retrieval Cache** | | ✅ | | RAGPipeline caches retrieved chunks in `last_retrieved_chunks` but no persistent retrieval cache (pipeline.py:127-137) |
| **Tool Cache** | | | ❌ | No tool/function call caching |
| **Prompt Reuse** | | ✅ | | Context reused in L3 cache key; system prompt not cached |
| **Context Reuse** | | ✅ | | L3 cache uses context vector; RAG context built from retrieved chunks |
| **Repository Memory** | | ✅ | | Documents ingested into vector store; async ingestion populates L1/L2 (async_ingest.py:169-184) |
| **Session Memory** | | | ❌ | No conversation/session history persistence |
| **Token Accounting** | | | ❌ | No token counting; `record_generation` only tracks latency (metrics.py:64-68) |
| **Cost Accounting** | | | ❌ | No cost calculation; stats endpoint returns hardcoded values (main.py:478-487) |
| **Observability** | ✅ | | | Prometheus metrics, OpenTelemetry tracing, structured logging (telemetry/) |
| **MCP** | | | ❌ | No MCP server/integration |
| **NPX** | | | ❌ | JS SDK exists but no NPX entry point |
| **IDE Integration** | | | ❌ | No VS Code/Cursor extension |

---

## 2. Current Data Flow

```
Request (query, context, meta, tenant_id)
  ↓
CacheEngine.resolve()
  ├─→ L1: Exact Match (Redis/SQLite)
  │     key = sha256(normalize(query) + canonical_meta_suffix(meta))
  │     TTL = 3600s (configurable)
  │     → HIT: return response
  │     → MISS: continue
  ↓
  ├─→ L2: Semantic Vector Match (Qdrant/LanceDB)
  │     embed(query) → vector
  │     search(collection="tenant_l2_cache", vector, filter=meta, threshold=0.85)
  │     hard_gate(incoming_meta, cached_meta) → HIT: return response
  │     → MISS: continue
  ↓
  ├─→ L3: Dual-Context Match (Qdrant/LanceDB named vectors)
  │     embed(query) → v_query
  │     embed(context) → v_context
  │     search query_vector + context_vector, intersect IDs
  │     hard_gate(merged_meta) → HIT: return response
  │     → MISS: continue
  ↓
MISS → resolve_or_generate()
  ├─→ Single-flight lock per L1 key
  ├─→ generate_fn() → LLM call (via RAGPipeline.generate)
  │     → RAGPipeline.retrieve() → vector search on rag_corpus
  │     → reranker (optional)
  │     → build prompt + context
  │     → litellm.completion() → LLM
  │     → return answer, citations, score
  ├─→ _is_cacheable() guard (blocks errors/refusals)
  ├─→ Conditional L1 write (nx=True)
  ├─→ async_write_l2()
  └─→ async_write_l3() (if context provided)
  ↓
Response {source: "L1|L2|L3|MISS", response: {...}}
```

---

## 3. Current Storage Map

| Storage System | Purpose | Backend(s) | Collections/Tables |
|----------------|---------|------------|-------------------|
| **Redis** | L1 exact cache, invalidation streams, rate limiting | `RedisStore` (redis_store.py) | Keys: `{tenant}:l1:{hash}`; Streams: `cache_invalidation` |
| **SQLite** | L1 exact cache (embedded mode) | `SQLiteStore` (sqlite_store.py) | Table: `cache (key PRIMARY KEY, value BLOB)`; WAL mode |
| **Qdrant** | L2/L3 vector cache, RAG corpus | `QdrantStore` (qdrant_store.py) | Collections: `{tenant}_l2_cache`, `{tenant}_l3_cache` (dual vectors), `{tenant}_ico_corpus` |
| **LanceDB** | L2/L3 vector cache, RAG corpus (embedded) | `LanceDBStore` (lancedb_store.py) | Tables: `{tenant}_l2_cache`, `{tenant}_l3_cache` (multi-vector), `{tenant}_ico_corpus` |
| **PostgreSQL** | ❌ Not used | — | — |
| **Filesystem** | Document uploads, LanceDB data files | Local/volume | `INGEST_ROOT/uploads/`, `./lancedb/` |

**Tenant Isolation Modes:**
- `collection` (default): Separate collections per tenant (`tenant_a_l2_cache`)
- `payload`: Shared collections with `tenant_id` filter in payload

---

## 4. Optimization Opportunities

### P0 — Correctness/Safety Issues

| # | Issue | Location | Risk |
|---|-------|----------|------|
| 1 | **No embedding cache** — every L2/L3 lookup re-computes embeddings | `cache_engine.py:288,352,353,418,419` | High latency, redundant compute |
| 2 | **No token/cost observability** — cannot measure savings | `metrics.py`, `main.py:478-487` | Blind to ROI; hardcoded stats |
| 3 | **Single-flight key ignores context** — L1 key excludes context | `cache_engine.py:190-194` | Context-dependent queries may collide |
| 4 | **L3 context not in L1 key** — context change doesn't create new L1 entry | `cache_engine.py:190-194` | Stale L1 hits for different contexts |
| 5 | **No model/provider fingerprint in cache key** — model switch returns stale cache | `cache_engine.py:190-194` | Wrong model responses cached |
| 6 | **RAG retrieval not cached** — every MISS re-retrieves | `pipeline.py:95-98` | Redundant vector search + embedding |
| 7 | **No cache versioning for schema changes** — metadata schema change = silent corruption | `metadata_guard.py` | False hits after schema evolution |

### P1 — High Token/Cost Reduction

| # | Opportunity | Impact |
|---|-------------|--------|
| 1 | **Embedding cache** — cache `embed(query)` and `embed(context)` | 50-80% embedding call reduction |
| 2 | **Retrieval cache** — cache RAG retrieval results by query+filters | Avoids vector search + rerank on repeat |
| 3 | **Prompt prefix cache** — cache system prompt + few-shot tokens | Reduces input tokens per LLM call |
| 4 | **Response compression** — store minimal response, reconstruct | Reduces L1/L2 storage |

### P2 — Latency Improvements

| # | Opportunity | Impact |
|---|-------------|--------|
| 1 | **Async embedding batch** — batch L2/L3 embeddings | Reduces embedder calls from 3→1 per L3 lookup |
| 2 | **L1 prefetch on L2 hit** — populate L1 when L2 hits | Subsequent exact hits <1ms |
| 3 | **Connection pooling** — reuse Qdrant/Redis connections | Already partially done in QdrantStore |

### P3 — Developer Experience

| # | Opportunity | Impact |
|---|-------------|--------|
| 1 | **NPX CLI** — `npx ico-cache query "..."` | Zero-install usage |
| 2 | **MCP server** — expose cache as MCP tool | AI agent integration |
| 3 | **VS Code extension** — inline cache hit indicators | Debugging visibility |
| 4 | **Better stats endpoint** — real token/cost metrics | `main.py:478-487` currently hardcoded |

---

## 5. Baseline Metrics

| Metric | Current Measurability | Value/Notes |
|--------|----------------------|-------------|
| **LLM calls** | ❌ Not tracked | Only `inflight_generations` gauge |
| **Input tokens** | ❌ Not tracked | No token counting in `litellm.completion` path |
| **Output tokens** | ❌ Not tracked | No token counting |
| **Total tokens** | ❌ Not tracked | — |
| **Embedding calls** | ❌ Not tracked | Each L2/L3 lookup = 1-2 embed calls |
| **Retrieval calls** | ❌ Not tracked | RAGPipeline.retrieve() not instrumented |
| **Latency** | ✅ Tracked | Prometheus `ico_cache_lookup_seconds`, `ico_cache_generation_seconds` |
| **Cache hits** | ✅ Tracked | Prometheus `ico_cache_lookups_total{layer,result}` |
| **Cache misses** | ✅ Tracked | Same counter |
| **Cache hit rate** | ✅ Computed | `CacheEngine.get_metrics()` + Prometheus |
| **Cost** | ❌ Not tracked | Hardcoded in `/stats` endpoint |
| **LLM calls avoided** | ❌ Not tracked | Derivable from hit rate × requests, but not exposed |
| **Embedding calls avoided** | ❌ Not tracked | — |
| **Retrieval calls avoided** | ❌ Not tracked | — |

**Benchmark Infrastructure:** Exists in `benchmark.py` with 5 datasets (paraphrase-hit, adversarial, multilingual, code-ast, lifecycle). Run with:
```bash
PYTHONPATH=packages/ico-cache-py/src:. python benchmark.py --dataset all --backend embedded
```
Reports written to `benchmark-reports/`.

---

## 6. Highest-Risk Future Problems

| Risk | Description | Mitigation Needed |
|------|-------------|-------------------|
| **False cache hits (semantic)** | Near-miss queries (e.g., "AAPL Q1 revenue" vs "MSFT Q1 revenue") have >0.93 cosine similarity | Hard gate already blocks at L2/L3; must extend to any future embedding cache |
| **False cache hits (context)** | L3 uses context vector; different contexts with similar embeddings could intersect | Hard gate on merged metadata (query+context) already implemented |
| **Stale data** | Document updates not auto-invalidated; cached answers reflect old corpus | Invalidation API exists (`/invalidate`, worker); needs change detection |
| **Temporal mismatch** | Quarterly/annual queries cached without time boundary | Quarter/topic in metadata gate; needs explicit temporal field |
| **Entity mismatch** | Hard gate blocks on entity/quarter/topic diff; but new entities not in schema pass gate | Schema must be comprehensive; `required_in_gate` controls |
| **Model mismatch** | Cache key lacks model/provider fingerprint; switching models returns wrong cache | Add `model_fingerprint` to L1/L2/L3 keys |
| **Provider mismatch** | Same — OpenAI vs Gemini vs Ollama responses differ | Same as above |
| **Repository changes** | Ingested documents updated; cache not invalidated | Watch filesystem / webhook → publish invalidation |
| **Tenant bleed (payload mode)** | Filter-based isolation; bug in filter = cross-tenant leak | Tests verify (`test_multitenancy.py:120-170`); needs defense-in-depth |
| **Authorization context mismatch** | API key → tenant mapping; cache key uses tenant_id only | Current design correct; must not add user_id to cache key without authz check |
| **Prompt injection via cached data** | Malicious document content cached → returned to other users | L1/L2/L3 store generated answers, not raw docs; but RAG context from corpus |
| **Memory poisoning** | Bad generation cached → perpetuated | `_is_cacheable()` blocks errors/refusals; but not hallucinations |
| **Secret handling** | API keys in env vars; no secret scanning in cache | `audit.py` scans for secrets; cache never stores keys |

---

## Cross-Analysis: Contradictions & Resolutions

| Area | Finding | Contradiction | Resolution |
|------|---------|---------------|------------|
| **Cache Engineer** | L1/L2/L3 fully implemented with hard gates | — | Baseline solid |
| **RAG Engineer** | Embeddings generated at 3 points per L3 lookup (query, context, retrieval) | Cache Engineer shows L2/L3 each call embedder | Confirmed: L3 calls embedder 2x (query+context), RAG calls 1x (retrieval) = 3 embeddings per MISS |
| **LLM Engineer** | Token counting absent; LiteLLM returns usage but ignored | Observability Engineer shows Prometheus metrics exist | Metrics track latency only; token usage available in LiteLLM response but not captured |
| **Observability Engineer** | OpenTelemetry spans for cache layers + RAG fallback | Security Engineer notes no authz context in spans | Spans have `tenant_id` but not `user_id` or API key hash |
| **Security Engineer** | Tenant isolation via collection OR payload filter | Integration Engineer shows JS SDK doesn't pass tenant | JS SDK `resolve()` doesn't send tenant_id; relies on API key auth at server |
| **Integration Engineer** | Python SDK = CacheEngine class; JS SDK = HTTP wrapper | Testing Engineer shows tests use CacheEngine directly | JS SDK is thin HTTP client; not feature-parity with Python |
| **Testing Engineer** | Tests cover L1/L2/L3 hits, invalidation, concurrency, multitenancy | Benchmark Engineer shows benchmarks test hit rates, false hits | Benchmarks are separate from unit tests; both pass |
| **Benchmark Engineer** | 5 datasets measure hit rate, false hits, latency | Cache Engineer shows adaptive threshold adjusts hit rate | Benchmarks run with fixed thresholds; adaptive disabled in benchmarks |

---

## Summary: What Exists vs. What Phase 3 Needs

| Component | Current State | Phase 3 Gap |
|-----------|---------------|-------------|
| **L1 Exact Cache** | ✅ Complete | Add model fingerprint to key |
| **L2 Semantic Cache** | ✅ Complete | Add embedding cache layer |
| **L3 Context Cache** | ✅ Complete | Add embedding cache; fix L1 key to include context |
| **Embedding Cache** | ❌ Missing | **New layer** — cache embeddings by text+model |
| **Retrieval Cache** | ❌ Missing | **New layer** — cache RAG retrieval results |
| **Token/Cost Accounting** | ❌ Missing | **New** — integrate LiteLLM usage, Prometheus counters |
| **Observability** | ✅ Good | Add token/cost dashboards; MCP metrics |
| **Security** | ✅ Strong | Add model fingerprint; secret scanning in cache |
| **Integration (Python)** | ✅ Complete | — |
| **Integration (JS/TS)** | ⚠️ Thin HTTP wrapper | Need full SDK parity + NPX |
| **MCP/IDE/NPX** | ❌ Missing | **New** integration layer |

---

*Report generated from read-only analysis of ICO-Cache repository at commit HEAD. No code was modified.*