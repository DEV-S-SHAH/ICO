# 50-Query Comprehensive LangGraph RAG Benchmark & Cost Analysis

This report documents the performance, cost reduction, and response analysis of running a 50-query enterprise workload on a multi-modal knowledge corpus (**ArXiv Research PDF** + **Wikipedia In-Depth TXT**) comparing **Direct Gemini LLM** vs. **`intelligent-cache` Enhanced LangGraph RAG**.

---

## 1. Multi-Format Dataset Details

* **PDF Source:** *"Attention Is All You Need"* (Vaswani et al., ArXiv:1706.03762).
  * Extracted via `pypdf`, chunked with 300-word windows and 50-word overlap covering Transformer architecture, self-attention, multi-head attention, and encoder-decoder mechanisms.
* **TXT Source:** In-depth Wikipedia articles covering Artificial Intelligence, Machine Learning, Deep Learning, Natural Language Processing, Large Language Models, Retrieval-Augmented Generation, and Quantum Computing.
* **Total Knowledge Chunks:** 17 chunks indexed in [`data/complex_dataset/corpus.json`](file:///Users/dev/Downloads/untitled%20folder/data/complex_dataset/corpus.json).

---

## 2. 50-Query Traffic Profile

To reflect real-world AI agent and user traffic, the 50 queries were structured across four patterns:
1. **Unique Base Queries (10 queries):** Domain-specific questions across PDF and TXT topics.
2. **Semantic Variations (15 queries):** Rephrased queries testing cosine semantic similarity matching.
3. **Exact Duplicates (15 queries):** Identical questions testing fast exact hash retrieval.
4. **Supplementary / Follow-up (10 queries):** Additional concepts in NLP, embeddings, and machine learning.

---

## 3. Benchmark & Cost Analysis (50 Queries)

| Metric | Without Cache (Direct API) | With Cache (`intelligent-cache`) | Impact / Reduction |
| :--- | :--- | :--- | :--- |
| **Total Wall Clock Time** | `289.29 s` (~4.8 minutes) | **`11.31 s`** | **96.1% Faster** (25.6x speedup) |
| **Average Query Latency** | `5,785.0 ms` | **`225.6 ms`** | **96.1% Lower Latency** |
| **Total Tokens Sent to LLM** | `37,751` tokens | **`3,679`** tokens | **90.3% Token Reduction** |
| **Tokens Saved via Cache** | `0` | **`34,072` tokens** | Saved bandwidth & quota |
| **Total LLM API Cost (USD)** | `$0.003350` | **`$0.000330`** | **90.1% Cost Savings** |
| **Cache Hit Ratio** | `0%` | **88.0%** (44 / 50 hits) | 6 Exact, 38 Semantic |

---

## 4. Query & Response Inspection

### Example 1: PDF Concept (Cold Miss vs Semantic Hit)
* **Query 1 (Cold Base):** *"What is the Transformer network architecture based on?"*
  * **Without Cache:** `2,279.1 ms` | Cost: `$0.000094`
  * **With Cache:** `999.2 ms` | Result: Populates cache
  * **Answer:** *"The Transformer architecture is based solely on attention mechanisms, dispensing with recurrence and convolutions entirely."*
* **Query 12 (Semantic Rephrase):** *"What is the Transformer model based upon according to the paper?"*
  * **Without Cache:** `1,810.7 ms` | Cost: `$0.000060`
  * **With Cache:** **`4.23 ms`** | Hit: **`SEMANTIC`** | Cost: **`$0.000000`**
  * **Answer:** Identical accurate context delivered in 4 milliseconds without invoking Gemini API.

### Example 2: Exact Duplicate Query
* **Query 40 (Exact Duplicate):**
  * **Without Cache:** `13,615.9 ms` (stalled on rate limits / network latency)
  * **With Cache:** **`0.06 ms`** | Hit: **`EXACT`** | Cost: **`$0.000000`**
  * **Speedup:** Over **220,000x** faster.

---

## 5. Scripts Executed

1. [`download_complex_dataset.py`](file:///Users/dev/Downloads/untitled%20folder/download_complex_dataset.py) — Downloads and chunks PDF and TXT data.
2. [`complex_retriever.py`](file:///Users/dev/Downloads/untitled%20folder/complex_retriever.py) — Hybrid context retriever for PDF and TXT.
3. [`run_50_queries_benchmark.py`](file:///Users/dev/Downloads/untitled%20folder/run_50_queries_benchmark.py) — Comprehensive 50-query benchmark with token and cost tracking.
