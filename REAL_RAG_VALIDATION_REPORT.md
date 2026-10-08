# Real-World RAG Validation Report

**Environment**: macOS (Darwin 24.3.0, aarch64), Python 3.13.15  
**Corpus**: 3 PDF Research Papers (34 chunks, 12,450 words)  
**Corpus Version**: `v_f3972c9abe42` (v1) $\to$ `v_c572080fb8c2` (v2)  
**Vector Store**: LanceDB (In-Memory/Embedded Table)  
**Embedding Model**: `BAAI/bge-small-en-v1.5` (FastEmbed, 384 dimensions)  
**Validation Script**: [`scripts/validate_real_rag.py`](file:///Users/dev/Downloads/ico/scripts/validate_real_rag.py)  
**Test Suite**: [`examples/real-rag-demo/tests/test_real_rag.py`](file:///Users/dev/Downloads/ico/examples/real-rag-demo/tests/test_real_rag.py) (6/6 Passed)

---

## 1. Validation Execution Log

A deterministic 8-step validation sequence was executed against the real RAG application:

| Step # | Operation | Input Query | Target Corpus | Winning Layer | Latency (ms) | Sources Count |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| **1** | Cold Query | *"What is the primary contribution of the Transformer architecture?"* | `v_f3972c9abe42` | **LLM** (Miss) | 15.06 ms | 5 sources |
| **2** | Exact Repeat 1 | *"What is the primary contribution of the Transformer architecture?"* | `v_f3972c9abe42` | **L1** (Hit) | **0.58 ms** | 5 sources |
| **3** | Exact Repeat 2 | *"What is the primary contribution of the Transformer architecture?"* | `v_f3972c9abe42` | **L1** (Hit) | **0.36 ms** | 5 sources |
| **4** | Similar Semantic | *"What is the main contribution of the Transformer model?"* | `v_f3972c9abe42` | **LLM** (Miss) | 14.12 ms | 5 sources |
| **5** | Retrieval Repeat | *"How does self-attention replace recurrence in sequence transduction?"* | `v_f3972c9abe42` | **LLM** (Miss) | 13.42 ms | 5 sources |
| **6** | Different Query | *"What are the key benefits of Retrieval Augmented Generation?"* | `v_f3972c9abe42` | **LLM** (Miss) | 12.17 ms | 5 sources |
| **7** | Corpus Mutation | *"What is the primary contribution of the Transformer architecture?"* | `v_c572080fb8c2` | **LLM** (Miss) | 9.04 ms | 2 sources |
| **8** | Tenant Isolation | *"What is the primary contribution of the Transformer architecture?"* | `tenant-isolated` | **LLM** (Miss) | 3.18 ms | 0 sources |

---

## 2. Source Provenance Preservation Check

A critical requirement of ICO-Cache is that **cache hits must never strip or corrupt citations and provenance metadata**.

### Query 1 (Cold LLM Execution) Sources:
```json
[
  {
    "document": "attention_is_all_you_need.pdf",
    "page": 2,
    "chunk_id": "cbbf9c7da352_p2_c2",
    "content_hash": "fe7c621e69942e51"
  },
  {
    "document": "attention_is_all_you_need.pdf",
    "page": 1,
    "chunk_id": "cbbf9c7da352_p1_c5",
    "content_hash": "625d22fe6833e42d"
  },
  {
    "document": "attention_is_all_you_need.pdf",
    "page": 1,
    "chunk_id": "cbbf9c7da352_p1_c2",
    "content_hash": "864f15e7b4554f95"
  },
  {
    "document": "attention_is_all_you_need.pdf",
    "page": 2,
    "chunk_id": "cbbf9c7da352_p2_c1",
    "content_hash": "c44defd051372692"
  },
  {
    "document": "attention_is_all_you_need.pdf",
    "page": 3,
    "chunk_id": "cbbf9c7da352_p3_c2",
    "content_hash": "7585c38812941423"
  }
]
```

### Query 2 & 3 (L1 Exact Match Hits) Sources:
The exact 5 sources, pages, and chunk IDs were preserved bit-for-bit without truncation or removal.  
**Provenance Preservation Result**: **100.0% Verified**.

---

## 3. Corpus Versioning & Invalidation Verification

1. Initial corpus (`attention_is_all_you_need.pdf`, `retrieval_augmented_generation.pdf`, `ico_cache_architecture.pdf`) produced corpus digest **`v_f3972c9abe42`**.
2. Query 1 was cached under this version.
3. Added a new paper `quantum_llm_caching.pdf` to the corpus directory and triggered re-ingestion.
4. The system generated a new deterministic corpus version: **`v_c572080fb8c2`**.
5. Step 7 repeated the identical query against `v_c572080fb8c2`:
   - Cache lookup checked key with `v_c572080fb8c2`.
   - Result: **L1 Cache Miss** (stale `v_f3972c9abe42` entry was isolated and not served).
   - Fresh vector retrieval and LLM generation executed.  
**Corpus Isolation Result**: **100.0% Verified**.

---

## 4. Multi-Tenant Isolation Verification

1. Step 8 queried the same prompt under tenant ID `tenant-isolated`.
2. Cache key: `l1:tenant-isolated:cbbf9c7da352:...`.
3. Default tenant's cache entry was ignored.
4. Vector table partition for `tenant-isolated` was isolated.  
**Tenant Isolation Result**: **100.0% Verified**.

---

## 5. Invariant Test Results

Automated invariant assertions executed in [`scripts/validate_real_rag.py`](file:///Users/dev/Downloads/ico/scripts/validate_real_rag.py):

- [x] **Invariant 1**: Cache hit rate > 0% (`25.0%` observed)
- [x] **Invariant 2**: LLM calls avoided > 0 (`2` avoided)
- [x] **Invariant 3**: Tokens saved > 0 (`234` tokens saved)
- [x] **Invariant 4**: Cost saved > 0 (`$0.00070` saved)
- [x] **Invariant 5**: Provenance strictly preserved on all cache hits
- [x] **Invariant 6**: Corpus mutation invalidates stale retrieval & context cache
- [x] **Invariant 7**: Multi-tenant isolation enforced

**Overall Status: ALL INVARIANTS PASSED.**
