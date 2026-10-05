---
name: rag-optimization
description: Optimize RAG retrieval and context construction. Covers chunking strategy, embedding selection, reranking, context packing, retrieval quality metrics, and grounding validation. Distinguishes retrieval optimization from response caching.
---

# RAG Optimization Skill

## Purpose

Optimize the retrieval and context construction pipeline to maximize grounding quality while minimizing token usage and latency.

## When to Use

- Tuning retrieval parameters (top-k, thresholds, filters)
- Designing chunking strategies for new document types
- Selecting/comparing embedding models
- Configuring reranking
- Optimizing context window packing
- Validating grounding quality

## When NOT to Use

- For response caching (L1/L2/L3) — use cache-analysis skill
- For token optimization in generation — use token-optimization skill
- For implementation without retrieval quality measurement

## Workflow

### 1. Measure Baseline Retrieval Quality

```python
# Key metrics per query set:
# - Recall@k (relevant docs in top-k)
# - MRR (Mean Reciprocal Rank)
# - NDCG (Normalized Discounted Cumulative Gain)
# - Precision@k
# - Grounding rate (citations supported by retrieved chunks)
```

### 2. Optimize Chunking Strategy

| Document Type | Strategy | Parameters |
| --- | --- | --- |
| Code | AST-based (functions, classes) | Max 500 tokens, overlap 50 |
| Financial (SEC) | Section-aware (Item 1A, 7, 8) | Preserve headers, tables |
| Legal | Clause-based | Preserve definitions, references |
| General text | Recursive character | 512 tokens, 10% overlap |
| Conversational | Turn-based | Speaker + utterance |

**Validation:** Chunk retrieval recall vs. full-document retrieval.

### 3. Embedding Model Selection

```python
# Compare models on domain-specific eval set
models = [
    "BAAI/bge-small-en-v1.5",    # 384-dim, fast, good general
    "BAAI/bge-base-en-v1.5",     # 768-dim, better quality
    "BAAI/bge-large-en-v1.5",    # 1024-dim, best quality
    "sentence-transformers/all-MiniLM-L6-v2",  # 384-dim, very fast
    # Domain-specific when available
]

# Metrics: Recall@10, latency, memory, index size
```

### 4. Reranking Configuration

```python
# Cross-encoder reranker (more accurate, slower)
# Use for top-50 → top-5 reduction
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# When to rerank:
# - High-stakes queries (financial, legal, medical)
# - Low initial recall@k
# - Ambiguous queries needing precision
```

### 5. Context Construction & Packing

```python
# Hierarchical packing for context window:
# 1. Query-relevant summary (100-200 tokens)
# 2. Top-k chunks with citations (fit remaining budget)
# 3. Metadata for grounding verification

def pack_context(chunks, max_tokens=4000):
    # Reserve tokens for prompt template + query + response
    budget = max_tokens - estimate_prompt_overhead()
    
    # Sort by relevance score
    chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
    
    packed = []
    used = 0
    for chunk in chunks:
        chunk_tokens = count_tokens(chunk.text)
        if used + chunk_tokens > budget:
            break
        packed.append(chunk)
        used += chunk_tokens
    return packed
```

### 6. Validate Grounding

```python
# Every generated answer must trace to retrieved chunks
def validate_grounding(answer, citations, retrieved_chunks):
    for citation in citations:
        assert any(citation in chunk.source_file for chunk in retrieved_chunks)
    # Check for hallucination: claims not in retrieved chunks
    claims = extract_claims(answer)
    for claim in claims:
        assert any(claim in chunk.text for chunk in retrieved_chunks)
```

## Inputs

- Document corpus (type, volume, structure)
- Query workload (types, complexity, domain)
- Current retrieval config (chunking, embedding, top-k, filters)
- Quality requirements (recall, latency, cost)
- Context window constraints

## Outputs

- Optimized chunking configuration per document type
- Embedding model recommendation with benchmarks
- Reranking strategy (when, which model, threshold)
- Context packing algorithm and token budget allocation
- Retrieval quality metrics (before/after)
- Grounding validation results

## Validation

- **Retrieval benchmarks** — Recall@k, MRR, NDCG on eval sets
- **Generation quality** — Human eval or LLM-judge on answer quality
- **Grounding audit** — Citation accuracy, hallucination rate
- **Latency budget** — Retrieval + rerank + pack < 100ms (p95)
- **Token efficiency** — Context tokens per answer quality unit

## Failure Conditions

- Reduced recall (missed relevant documents)
- Increased hallucination (poor grounding)
- Context window overflow (packing bug)
- Reranking latency exceeds budget
- Embedding model regression on domain queries
- Chunking loses critical structure (tables, code blocks)

## Retrieval vs Cache Boundary

| Aspect | RAG Retrieval | Response Cache (L2/L3) |
| --- | --- | --- |
| **What** | Finds source documents | Stores LLM responses |
| **Key** | Query vector (+ filters) | Query + context + metadata |
| **Reuse** | Re-read documents | Return cached answer |
| **Optimization** | Better retrieval, less tokens | More hits, faster response |
| **Invalidation** | Document update | TTL, explicit, source change |