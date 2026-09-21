# ⚡ LangGraph RAG + Intelligent Multi-Level Caching

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Framework-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Model](https://img.shields.io/badge/LLM-Google%20Gemini-green.svg)](https://ai.google.dev/)
[![Cache](https://img.shields.io/badge/Caching-Exact%20%2B%20Semantic-purple.svg)](https://github.com/DEV-S-SHAH/ICO)

An optimized, minimal, and high-performance **RAG pipeline** built with **LangGraph** and **Google Gemini**, supercharged by **`intelligent-cache`** (Exact Hash + Semantic Cosine Caching).

---

## 🚀 Performance & Cost Impact (50-Query Benchmark)

Evaluated on a multi-format technical corpus (**ArXiv Research PDF** + **Wikipedia TXT**):

| Metric | Without Cache (Direct API) | With Cache (`intelligent-cache`) | Improvement |
| :--- | :--- | :--- | :--- |
| **Total Wall Clock Time** | `289.29 s` (~4.8 min) | **`11.31 s`** | **96.1% Faster** (25.6x speedup) |
| **Average Query Latency** | `5,785.0 ms` | **`225.6 ms`** | **96.1% Lower Latency** |
| **Total Tokens Consumed** | `37,751` tokens | **`3,679`** tokens | **90.3% Token Reduction** |
| **Total LLM API Cost (USD)** | `$0.003350` | **`$0.000330`** | **90.1% Cost Savings** |
| **Overall Cache Hit Rate** | `0.0%` | **`88.0%`** (44 / 50 hits) | 6 Exact, 38 Semantic |

---

## 🏛️ System Architecture

```
User Query
    │
    ▼
[ LangGraph Workflow ]
    │
    ├──> 1. Retrieve: Fetches top-k passages from multi-source PDF & TXT corpus
    │
    └──> 2. Generate (Gemini + Intelligent Cache):
             │
             ├── Exact SHA-256 Match?  ──[HIT]──> Return in 0.05 ms ($0.00)
             │
             ├── Cosine Sim >= 0.75?   ──[HIT]──> Return in 2.30 ms ($0.00)
             │
             └── [MISS] ──> Gemini 3.1 Flash API ──> Store & Index Response
```

---

## 📂 Minimal Project Layout

```
.
├── benchmark_results/        # Exported 50-query execution data (JSON & CSV)
├── data/complex_dataset/     # Downloaded ArXiv PDF + TXT chunks
├── src/                      # Core application modules
│   ├── graph.py              # Compiled LangGraph StateGraph workflow
│   ├── retriever.py          # Multi-format document retriever (PDF + TXT)
│   ├── download_data.py      # Automated dataset downloader & chunker
│   ├── evaluator.py          # Quality evaluator (Faithfulness, Relevance, ROUGE)
│   └── diff.py               # Response drift & side-by-side comparator
├── intelligent_cache/        # The caching library
├── benchmark.py              # 50-query benchmark & cost analysis runner
├── evaluate.py               # Response quality evaluation runner
└── requirements.txt          # Python dependencies
```

---

## ⚡ Quickstart

### 1. Setup Environment
```bash
# Create and activate Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 2. Configure API Key
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

### 3. Download the Dataset
Downloads the ArXiv PDF research paper and technical TXT articles:
```bash
python src/download_data.py
```

### 4. Run the 50-Query Benchmark
Runs the 50-query workload, prints cost and latency comparisons, and saves results:
```bash
python benchmark.py
```
* Results are exported to:
  * `benchmark_results/responses_50_queries.json`
  * `benchmark_results/responses_50_queries.csv`

### 5. Run the Quality Evaluation Suite
Evaluates Faithfulness, Answer Relevance, and ROUGE parity between direct and cached responses:
```bash
python evaluate.py
```
