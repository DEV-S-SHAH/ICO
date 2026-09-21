# LangGraph RAG with Intelligent Cache & Google Gemini

A complete Retrieval-Augmented Generation (RAG) system built with **[LangGraph](https://github.com/langchain-ai/langgraph)**, utilizing **[intelligent-cache](https://github.com/DEVSHAH16/dev)** as an exact + semantic caching layer and powered by **Google Gemini**.

---

## 1. System Architecture

```
User Query
    │
    ▼
[ LangGraph Workflow ]
    │
    ├──> 1. Retrieve Node (SimpleVectorRetriever)
    │        Extracts relevant documents from downloaded dataset
    │
    └──> 2. Generate Node (Google Gemini with Intelligent Cache)
             │
             ├── Exact Hash Match?  ──[HIT]──> Return in 0.2 ms
             │
             ├── Semantic Vector Match? (Cosine Sim >= 0.75) ──[HIT]──> Return in 2.3 ms
             │
             └── [MISS] ──> Google Gemini API Call ──> Store in Cache
```

---

## 2. Benchmark Results (With vs Without Cache)

Tested on macOS with Python 3.11:

| Test Case | Scenario | Without Cache (Direct API) | With Cache (`intelligent-cache`) | Speedup |
| :--- | :--- | :--- | :--- | :--- |
| **Query 1** | Initial Cold Query | `1,921.8 ms` | `5,016.9 ms` (Cold Miss + Index) | 1.0x |
| **Query 2** | Exact Duplicate Query | `5,927.9 ms` | **`0.2 ms`** (Exact Hash Hit) | **28,228x** |
| **Query 3** | Semantic Equivalent Query | `10,040.1 ms` | **`2.3 ms`** (Cosine Similarity Hit) | **4,309x** |
| **Query 4** | New Topic (Quantum Computing) | `4,092.4 ms` | `10,848.9 ms` (Cold Miss) | 1.0x |

### Cache Metrics
* **Total Requests:** 4
* **Hit Rate:** 50%
* **Exact Hits:** 1
* **Semantic Hits:** 1
* **Total Latency Saved:** > 10,000 ms

---

## 3. Running the Project

### Virtual Environment (Python 3.11)
```bash
source .venv/bin/activate
```

### Download the Knowledge Dataset
```bash
python download_dataset.py
```

### Run the RAG Benchmark
```bash
python run_rag_demo.py
```
