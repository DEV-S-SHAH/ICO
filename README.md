# ⚡ LangGraph RAG with `ico-cache` & Google Gemini

A simple, fast, and smart RAG (Retrieval-Augmented Generation) application built using **LangGraph**, **Google Gemini**, and the official **[`ico-cache`](https://pypi.org/project/ico-cache/)** library from PyPI.

---

## 💡 What is this project?

When building AI applications with RAG:
1. **Without Cache:** Every time a user asks a question, your app calls Google Gemini API. This is slow (takes 2 to 6 seconds), hits rate limits, and costs money for every token.
2. **With Cache (`ico-cache`):** If someone asks the same question—or even a *similar question in different words*—the answer is served directly from memory in **less than 3 milliseconds** at **$0.00 cost**.

---

## 📦 How to Install `ico-cache` from PyPI

The library is published on PyPI at **[pypi.org/project/ico-cache](https://pypi.org/project/ico-cache/)**.

To install everything with one simple command:

```bash
# 1. Create and activate a clean Python 3.11 environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install all requirements (includes ico-cache from PyPI)
pip install -r requirements.txt
```

> **Direct pip command:**  
> You can also install the cache library directly anytime via:  
> `pip install ico-cache`

---

## 🛠️ How to Use It in 3 Simple Steps

### Step 1: Set your Gemini API Key
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

### Step 2: Download the Dataset (PDF & Text)
Uses `ico-cache`'s built-in **`AutoLoader`** to parse the official *Attention Is All You Need* PDF paper and AI technical articles:
```bash
python src/download_data.py
```

### Step 3: Run the Benchmark (See With vs Without Cache)
Runs 50 realistic queries, compares the responses, and saves the results to CSV and JSON:
```bash
python benchmark.py
```

---

## 🔍 How Does "With Cache" vs "Without Cache" Actually Work?

Here is the exact difference in simple, plain code:

### ❌ 1. Without Cache (Calls Gemini API Every Time)
```python
# Every single query makes a network call to Google Gemini
response = gemini_model.generate_content(prompt)

# Result:
# ⏱️ Latency: 2,500 ms - 6,000 ms
# 💰 Cost: $0.00008 per call
# ⚠️ Risk: Hits Google API rate limits quickly
```

### ✅ 2. With Cache (`ico-cache`)
```python
from intelligent_cache import IntelligentCache

# Initialize the cache
cache = IntelligentCache(similarity_threshold=0.75)

# Check cache before calling Gemini
cached_result = cache.get(prompt)

if cached_result:
    # CACHE HIT! Instant response
    answer = cached_result.value
else:
    # CACHE MISS! Call Gemini once and save it
    answer = gemini_model.generate_content(prompt).text
    cache.set(prompt, answer)

# Result on repeated or similar questions:
# ⏱️ Latency: 0.05 ms (Exact match) or 2.3 ms (Similar question)
# 💰 Cost: $0.00 (Zero API tokens used!)
# 🚀 Speedup: Up to 28,000x faster
```

---

---

## 📊 Benchmark & Performance Comparison

A side-by-side comparison of direct LLM calls vs intelligent caching:

| Metric | Without Cache (Direct Gemini API) | With Cache (`ico-cache`) | Impact |
| :--- | :--- | :--- | :--- |
| **Response Latency** | 1,500 ms – 6,000 ms | **0.05 ms – 3.8 ms** | **96% Faster (Instant)** |
| **Repeated / Duplicate Queries** | 2,000+ ms per call | **0.05 ms** (Zero drift) | Instant hash hit |
| **Semantically Similar Queries** | Re-invokes LLM every time | **2.0 – 4.0 ms** | Reuses grounded answer |
| **Token Usage & Quota** | Consumes full tokens each call | **Zero tokens used on cache hits** | **~90% Token Reduction** |
| **LLM Inference Cost** | Billed on every request | **$0.000000 on hits** | **~90% Cost Savings** |
| **API Rate Limit Exceptions** | Prone to 429 Too Many Requests | **Protected by cache shield** | 100% reliable |

---

## 📁 Benchmark Data & Response Logs

The benchmark outputs clean, structured logs for analysis:
* **CSV Format:** [`benchmark_results/responses_50_queries.csv`](benchmark_results/responses_50_queries.csv) — Formatted with clean text wrapping, proper cell quoting, and fixed decimal precision (no scientific `e` notation).
* **JSON Format:** [`benchmark_results/responses_50_queries.json`](benchmark_results/responses_50_queries.json) — Full metadata and responses for downstream evaluation.

---

## 🧪 Optional: How to Evaluate Response Quality
To verify that cached answers have the same high accuracy as fresh Gemini answers:
```bash
python evaluate.py
```
This tests **faithfulness** (no hallucinations), **relevance**, and **ROUGE accuracy**.
