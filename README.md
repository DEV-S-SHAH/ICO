# ⚡ LangGraph RAG with Intelligent Cache & Google Gemini

A simple, fast, and smart RAG (Retrieval-Augmented Generation) application built using **LangGraph**, **Google Gemini**, and the **`intelligent-cache`** library.

---

## 💡 What is this project?

When building AI applications with RAG:
1. **Without Cache:** Every time a user asks a question, your app calls Google Gemini API. This is slow (takes 2 to 6 seconds) and costs money for every token.
2. **With Cache (`intelligent-cache`):** If someone asks the same question—or even a *similar question in different words*—the answer comes directly from memory in **less than 3 milliseconds** at **$0.00 cost**.

---

## 📦 How to Install the Cache Library

The library **`intelligent-cache`** is included directly inside this repository.

To install it so Python can use it anywhere in your terminal:

```bash
# Step 1: Create and activate a clean Python environment
python3.11 -m venv .venv
source .venv/bin/activate

# Step 2: Install required packages (LangGraph, Google Gemini, etc.)
pip install -r requirements.txt

# Step 3: INSTALL THE CACHE LIBRARY ITSELF
pip install -e .
```

> **What does `pip install -e .` do?**  
> It reads `pyproject.toml` in this folder and installs `intelligent-cache` into your Python environment. Once installed, you can import it in any script using:  
> `from intelligent_cache import IntelligentCache`

---

## 🛠️ How to Use It in 3 Simple Steps

### Step 1: Set your Gemini API Key
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

### Step 2: Download the Dataset (PDF & Text)
This downloads the official *Attention Is All You Need* PDF paper and AI knowledge articles from the web:
```bash
python src/download_data.py
```

### Step 3: Run the Benchmark (See With vs Without Cache)
This runs 50 realistic queries, compares the responses, and saves the results to a CSV and JSON file:
```bash
python benchmark.py
```

---

## 🔍 How Does "With Cache" vs "Without Cache" Actually Work?

Here is the exact difference in simple code:

### ❌ 1. Without Cache (Direct API Call)
```python
# Every single query makes a network call to Google Gemini
response = gemini_model.generate_content(prompt)

# Result:
# ⏱️ Latency: 2,500 ms - 6,000 ms
# 💰 Cost: $0.00008 per call
# ⚠️ Risk: Hits Google API rate limits quickly
```

### ✅ 2. With Cache (`intelligent-cache`)
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

## 📊 Results Summary (50 Queries Test)

| Metric | Without Cache | With Cache | Difference |
| :--- | :--- | :--- | :--- |
| **Total Time** | 289 seconds (~5 mins) | **11 seconds** | **96% Faster** |
| **Average Latency** | 5,785 ms | **225 ms** | **Instant answers** |
| **Tokens Used** | 37,751 tokens | **3,679 tokens** | **90% Token Reduction** |
| **API Cost** | $0.0034 | **$0.0003** | **90% Money Saved** |
| **Repeated Questions** | Takes 5+ seconds | **Takes 0.05 ms** | Zero delay |
| **Rephrased Questions** | Calls API again | **Reuses answer (2 ms)** | Smart similarity hit |

---

## 📁 Where are the Saved Responses?

After running `python benchmark.py`, all 50 query questions and answers are saved here:
* **JSON format:** [`benchmark_results/responses_50_queries.json`](benchmark_results/responses_50_queries.json)
* **CSV format (Excel):** [`benchmark_results/responses_50_queries.csv`](benchmark_results/responses_50_queries.csv)

---

## 🧪 Optional: How to Evaluate Response Quality
To verify that cached answers have the same high quality and accuracy as fresh Gemini answers:
```bash
python evaluate.py
```
This tests **faithfulness** (no hallucinations), **relevance**, and **ROUGE accuracy**.
