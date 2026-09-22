# ico-cache

[![PyPI](https://img.shields.io/pypi/v/ico-cache.svg)](https://pypi.org/project/ico-cache/)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)](https://pypi.org/project/ico-cache/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/DEV-S-SHAH/ICO/actions/workflows/ci.yml/badge.svg)](https://github.com/DEV-S-SHAH/ICO/actions/workflows/ci.yml)

**Fast, 3-tier semantic cache for LLM applications.**

`ico-cache` saves API token costs and cuts response latency by caching model responses so repeat or rephrased prompts don't hit the LLM again. It sits between your application and any model API — OpenAI, Anthropic, Gemini, Ollama, or anything LiteLLM supports — and serves semantically equivalent queries from a sub-millisecond cache instead of re-inferring.

---

## 🚀 Quick Install

```bash
pip install ico-cache
```

*Optional extras for universal document parsing (PDF, OCR, Office, ASTs) & distributed tracing:*
```bash
pip install "ico-cache[loaders,observability]"
```

---

## ⚡ 30-Second Quickstart (Zero Setup Needed)

No Docker, Redis, or external databases required. LanceDB, SQLite, and local FastEmbed embeddings run embedded out of the box:

```python
import asyncio
from ico_cache import CacheEngine

async def main():
    # 1. Initialize embedded zero-infra cache
    engine = CacheEngine.embedded()

    # 2. Your prompt
    prompt = "What does the fetch_user(id) function return?"

    # 3. Check cache before calling LLM
    hit = await engine.resolve(prompt)

    if hit["source"] == "MISS":
        # Cache MISS: call your LLM
        answer = {"text": "It returns the user record matching id, or None if not found."}
        print("Generated from LLM:", answer["text"])

        # Save to L1 (exact) and L2 (semantic) cache
        engine.set_l1(prompt, answer)
        await engine.async_write_l2(prompt, answer)
    else:
        print(f"Cache HIT via {hit['source']}:", hit["response"]["text"])

    # 4. Paraphrased query — instantly matches via L2 semantic cache!
    reworded_prompt = "what is the return value of fetch_user with an id?"
    semantic_hit = await engine.resolve(reworded_prompt)
    print(f"Reworded query hit via {semantic_hit['source']} in <20ms:", semantic_hit["response"]["text"])

asyncio.run(main())
```

---

## 💡 How It Works (The 3 Caching Tiers)

| Layer | Technique | How It Works | Speed |
| :--- | :--- | :--- | :--- |
| **L1** | **Exact** | Hashes normalized prompt + metadata fingerprint | `< 1 ms` |
| **L2** | **Semantic** | Cosine vector similarity (matches rephrased queries asking the same thing) | `15–30 ms` |
| **L3** | **Context-Aware** | Dual-vector matching for multi-turn chats & dialog context | `30–50 ms` |

### 💰 Measured Impact (11-corpus benchmark, warm cache)

> Caching with `ico-cache` eliminates **74–100% of LLM calls** at **0 answer regressions**. In a real 50-query Gemini RAG run the same guarantee meant: mean latency **4217 ms → 2253 ms**, total inference cost **−41.7%**, and the only cost paid was for genuinely novel queries.

### 🛡️ 0.00% False-Hit Safety
Unlike basic vector caches that confuse queries from different quarters, topics, or tenants, `ico-cache` has a built-in `hard_gate` metadata guard that prevents cross-topic and cross-entity false positives, plus a `serve_threshold` (default `0.90`) semantic gate that only serves a cached answer when the rephrased question is sufficiently similar. Recommended for RAG pipelines:

```python
engine = CacheEngine.embedded(serve_threshold=0.90, bind_context_to_l1=True)
```

### 🧠 What Else Is Inside
- **Never serves stale/wrong answers**: near-identical but differently-worded questions are gated by `serve_threshold`; L2/L3 entries expire via `l2_l3_ttl` and bind to the `in_context` they were written under.
- **Single-flight coalescing** — concurrent identical misses collapse into one generation (`resolve_or_generate`).
- **Universal ingestion** — content-sniffed loaders for PDF, OCR, Office (DOCX/XLSX/PPTX), ODF, TXT, CSV/JSON, HTML, and code ASTs.
- **Multi-tenancy** — isolated partitions via dedicated collections or timing-safe authenticated payload filters.
- **Observability** — Prometheus metrics, OpenTelemetry/Langfuse tracing, structured JSON logs, `/v1/ready` probes.
- **Cross-platform** — verified on Linux, Windows, and macOS.

### 🧪 Testing & Evaluation

The package ships with a 3-layer safety net, all running in CI on every push:

| Layer | Test | What it guards |
| :--- | :--- | :--- |
| Unit | `pytest packages/ico-cache-py/tests/` | exact/semantic/context tiers, backends, invalidation, multitenancy, security hardening, version sync |
| Baseline | `eval_harness.py` | **0% false-hit baseline** across text/structured/code/mixed + adversarial tenants |
| Cost | `scripts/cost_analysis.py` | cost & latency invariant on a committed 50-query benchmark — verifies the report stays in sync and **caching never costs more than no-caching** |

Run them yourself:

```bash
pip install "ico-cache[dev] @ ."
pytest packages/ico-cache-py/tests/
python eval_harness.py
python scripts/cost_analysis.py
```

---

## 📄 Ingest Documents & Text

Easily load and chunk PDFs, code, text, CSVs, Office files, and scanned images:

```python
from ico_cache import ingest

# Ingest any file by content (automatic extension sniffing + OCR fallback)
chunks = ingest(path="quarterly_report.pdf")
print(f"Extracted {len(chunks)} chunks ready for caching or RAG.")
```

---

## 🌐 Full Production Mode (Redis + Qdrant)

When scaling to distributed microservices:

```python
from ico_cache import CacheEngine
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

engine = CacheEngine(
    embedder=FastEmbedder(),
    vector_store=QdrantStore(host="localhost", port=6333),
    exact_store=RedisStore(host="localhost", port=6379, password="myredissecret"),
    adaptive_threshold=True,
)
```

---

## 🔗 Links & Resources

- **GitHub Repository**: [https://github.com/DEV-S-SHAH/ICO](https://github.com/DEV-S-SHAH/ICO)
- **Architecture & Layer Design**: [Detailed Architecture Guide](https://github.com/DEV-S-SHAH/ICO/blob/main/docs/ARCHITECTURE.md)
- **JavaScript / TypeScript SDK**: [`ico-cache-js` on npm](https://www.npmjs.com/package/ico-cache-js)
- **Issues & Contributions**: [GitHub Issues](https://github.com/DEV-S-SHAH/ICO/issues)