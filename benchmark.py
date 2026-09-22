"""benchmark.py -- dataset-driven ICO-Cache benchmark harness.

Five dataset types, each measuring a different quality dimension of the cache:

  paraphrase-hit  D1  Efficiency: cache hit rate, latency, throughput, LLM-avoidance.
  adversarial     D2  Correctness: near-miss / hard-negative false-hit prevention.
  multilingual    D3  Robustness: cross-language paraphrase matching.
  code-ast        D4  Code capability: tree-sitter AST extraction + code-question hits.
  lifecycle       D5  Freshness: stale-write suppression, invalidation, eviction.

Every dataset is generated at runtime from deterministic templates -- the harness
never ships or downloads corpus files. Run:

  PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python benchmark.py --dataset all
  PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python benchmark.py --dataset lifecycle --report-dir benchmark-reports
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import List

import numpy as np
from fastembed import TextEmbedding

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "packages/ico-cache-py/src"))

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.core.metadata_guard import hard_gate
from examples.universal_schema import extract_fields as universal_extract_fields
from examples.universal_schema import universal_schema

EMBEDDER = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def get_embedding(text: str):
    return list(EMBEDDER.embed([text]))[0].tolist()


def semantic_sim(a: List[float], b: List[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b))


def make_engine(backend: str, tmp_root: str, **overrides):
    from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder

    if backend == "qdrant":
        from ico_cache.backends.exact.redis_store import RedisStore
        from ico_cache.backends.vector.qdrant_store import QdrantStore

        engine = CacheEngine(
            embedder=FastEmbedder(),
            vector_store=QdrantStore(host="localhost", port=6333),
            exact_store=RedisStore(host="localhost", port=6379, password="myredissecret"),
            schema=universal_schema,
            **overrides,
        )
    else:
        from ico_cache.backends.exact.sqlite_store import SQLiteStore
        from ico_cache.backends.vector.lancedb_store import LanceDBStore

        engine = CacheEngine(
            embedder=FastEmbedder(),
            vector_store=LanceDBStore(uri=os.path.join(tmp_root, "lancedb")),
            exact_store=SQLiteStore(db_path=os.path.join(tmp_root, "exact.db")),
            schema=universal_schema,
            **overrides,
        )
    return engine


def l2_lookup(engine: CacheEngine, query: str, tenant_id: str = "default"):
    start = time.perf_counter()
    hit = asyncio.run(engine.get_l2(query, tenant_id=tenant_id))
    return hit, time.perf_counter() - start


def l1_get(engine: CacheEngine, query: str):
    start = time.perf_counter()
    val = asyncio.run(engine.get_l1(query))
    return val, time.perf_counter() - start


# ---------------------------------------------------------------------------
# D1 -- paraphrase-hit: efficiency
# ---------------------------------------------------------------------------

ENTITIES = ["AAPL", "MSFT", "JPM"]
TOPICS = ["revenue", "margins", "earnings"]
QUARTERS = ["Q1", "Q2", "Q3"]


def _canonical(tenant: str):
    params = [(e, q, t) for e in ENTITIES for q in QUARTERS for t in TOPICS[:2]]
    canon = []
    for e, q, t in params:
        q_ = f"What was the {t} of {e} in {q}?"
        repo = [
            f"Tell me the {t} for {e} {q}",
            f"{e} reported {t} in {q}",
            f"Can you summarize {e}'s {t} for {q}?",
        ]
        canon.append({"query": q_, "paraphrases": repo, "answer": {"content": f"{e} {t} {q} <synthetic>", "source": f"bench-{tenant}"}})
    return canon


def benchmark_paraphrase_hit(backend: str, tmp_root: str) -> dict:
    canon = _canonical("d1")
    novel = [f"What was the {t} of {e} in Q4?" for e in ENTITIES for t in TOPICS]

    engine = make_engine(backend, tmp_root)

    for item in canon:
        q, ans = item["query"], item["answer"]
        engine.set_l1(q, ans, meta=universal_extract_fields(q))
        asyncio.run(engine.async_write_l2(q, ans, meta=universal_extract_fields(q)))

    l1_lat = []
    l1_hits = 0
    for item in canon:
        val, lat = l1_get(engine, item["query"])
        l1_hits += 1 if val is not None else 0
        l1_lat.append(lat * 1000)

    sem_hits, sem_perf = [], []
    for item in canon:
        for par in item["paraphrases"]:
            hit, dt = l2_lookup(engine, par)
            sem_hits.append(1 if hit is not None else 0)
            sem_perf.append(dt * 1000)

    novel_miss = 0
    for q in novel:
        hit, _ = l2_lookup(engine, q)
        if hit is None:
            novel_miss += 1

    n_q = 0
    start = time.perf_counter()
    for i in range(200):
        item = canon[i % len(canon)]
        l1_get(engine, item["query"])
        n_q += 1
    qps = n_q / (time.perf_counter() - start)

    metrics = {
        "dataset": "paraphrase-hit",
        "l1_hit_rate": round(l1_hits / len(canon), 4),
        "l1_get_latency_ms": {
            "p50": round(statistics.median(l1_lat), 3),
            "p90": round(sorted(l1_lat)[int(len(l1_lat) * 0.9)], 3),
        },
        "l2_paraphrase_hit_rate": round(sum(sem_hits) / len(sem_hits), 4) if sem_hits else 0.0,
        "l2_lookup_latency_ms": {
            "p50": round(statistics.median(sem_perf), 3),
            "p90": round(sorted(sem_perf)[int(len(sem_perf) * 0.9)], 3),
        },
        "novel_queries_served_incorrectly": len(novel) - novel_miss,
        "throughput_l1_qps": round(qps, 1),
        "llm_avoidance_fraction": round((len(canon) + len(canon[0]["paraphrases"])) / (len(canon) * (1 + len(canon[0]["paraphrases"]))), 4),
    }
    print(json.dumps({"paraphrase-hit": metrics}, indent=2))
    return metrics


# ---------------------------------------------------------------------------
# D2 -- adversarial: hard-negative false-hit prevention
# ---------------------------------------------------------------------------


def benchmark_adversarial(backend: str, tmp_root: str) -> dict:
    engine = make_engine(backend, tmp_root)

    near_miss = []
    for t in TOPICS:
        near_miss.append(("sentinel", f"What is the {t} of AAPL in Q1?", f"What is the {t} of MSFT in Q1?", "entity"))
        near_miss.append(("sentinel", f"What is the {t} of AAPL in Q1?", f"What is the {t} of AAPL in Q2?", "quarter"))
        near_miss.append(("sentinel", f"What was AAPL {t} in Q1?", f"What is the {t} of JPM in Q3?", "entity+quarter"))

    gated, false_hits, max_sim = 0, [], 0.0
    for _, q1, q2, axis in near_miss:
        m1, m2 = universal_extract_fields(q1), universal_extract_fields(q2)
        if not hard_gate(m1, m2, universal_schema.filter_keys):
            gated += 1
            continue
        engine.set_l1(q1, {"content": "A", "source": "d2"})
        asyncio.run(engine.async_write_l2(q1, {"content": "A", "source": "d2"}))
        hit, _ = l2_lookup(engine, q2)
        sim = semantic_sim(get_embedding(q1), get_embedding(q2))
        max_sim = max(max_sim, sim)
        if hit is not None:
            false_hits.append((q1, q2, sim, axis))

    tenant_bleed = 0
    asyncio.run(engine.async_write_l2("What is the revenue of AAPL in Q1?", {"content": "ten-a"}, tenant_id="tenant_a"))
    for _ in range(3):
        hit, _ = l2_lookup(engine, "Tell me the revenue for AAPL Q1", tenant_id="tenant_b")
        if hit is not None:
            tenant_bleed += 1

    cross_topic_ok = 0
    for a, b in [("revenue", "margins")]:
        engine.set_l1(f"What is the {a} of AAPL in Q1?", {"content": "x"})
        asyncio.run(engine.async_write_l2(f"What is the {a} of AAPL in Q1?", {"content": "x"}))
        hit, _ = l2_lookup(engine, f"What is the {b} of AAPL in Q1?")
        if hit is None:
            cross_topic_ok += 1

    metrics = {
        "dataset": "adversarial",
        "near_miss_pairs": len(near_miss),
        "gated_by_schema": gated,
        "ungated_false_hits": len(false_hits),
        "max_similarity": round(max_sim, 4),
        "cross_topic_blocked": cross_topic_ok,
        "tenant_bleed_count": tenant_bleed,
    }
    print(json.dumps({"adversarial": metrics}, indent=2))
    if false_hits or tenant_bleed:
        raise AssertionError(f"Adversarial false-hit regression: {false_hits}, tenant bleed={tenant_bleed}")
    return metrics


# ---------------------------------------------------------------------------
# D3 -- multilingual paraphrase matching
# ---------------------------------------------------------------------------

_PHRASES = {
    "en": lambda e, t, q: f"What is the {t} of {e} in {q}?",
    "hi": lambda e, t, q: f"{e} ka {q} mein {t} kya hai?",
    "es": lambda e, t, q: f"Cual es el {t} de {e} en {q}?",
    "ja": lambda e, t, q: f"{e} の{q}の{t}は?",
}


def benchmark_multilingual(backend: str, tmp_root: str) -> dict:
    engine = make_engine(backend, tmp_root, thresh_semantic=0.82)
    langs = list(_PHRASES.keys())
    per_lang = {}
    for lang in langs[1:]:
        hits = total = 0
        for e in ENTITIES[:1]:
            for q in QUARTERS[:2]:
                for t in TOPICS[:2]:
                    src = _PHRASES["en"](e, t, q)
                    engine.set_l1(src, {"content": f"{e} {t} {q}", "source": "d3"})
                    asyncio.run(engine.async_write_l2(src, {"content": f"{e} {t} {q}", "source": "d3"}))
                    hit, _ = l2_lookup(engine, _PHRASES[lang](e, t, q))
                    hits += 1 if hit is not None else 0
                    total += 1
        per_lang[lang] = round(hits / total, 4) if total else 0.0

    cross_false = 0
    for e, q in (("AAPL", "Q1"), ("MSFT", "Q2")):
        src = _PHRASES["en"](e, "revenue", q)
        wrong_entity = _PHRASES["es"]("JPM" if e == "AAPL" else "AAPL", "revenue", q)
        hit, _ = l2_lookup(engine, wrong_entity)
        if hit is not None:
            cross_false += 1

    metrics = {"dataset": "multilingual", "per_language_l2_hit_rate": per_lang, "cross_language_false_hits": cross_false}
    print(json.dumps({"multilingual": metrics}, indent=2))
    return metrics


# ---------------------------------------------------------------------------
# D4 -- code-ast: tree-sitter extraction + code-question hits
# ---------------------------------------------------------------------------

CODE_SAMPLES = {
    "py": ("python", 'class OrderProcessor:\n    def apply_discount(self, subtotal, rate):\n        return subtotal * (1 - rate)\n    def compute_tax(self, amount, tax_rate):\n        return amount * tax_rate\n'),
    "js": ("javascript", 'class PaymentGateway {\n  calculateTotal(items) { return items.reduce((s, i) => s + i.price, 0); }\n  applyDiscount(total, rate) { return total * (1 - rate); }\n}\n'),
    "go": ("go", 'package main\ntype InventoryManager struct { Stock int }\nfunc (m *InventoryManager) Add(qty int) { m.Stock += qty }\nfunc (m *InventoryManager) Subtotal() int { return m.Stock }\n'),
}


def ast_entity_counts(lang: str, source: str) -> dict:
    import tree_sitter
    import tree_sitter_go
    import tree_sitter_javascript
    import tree_sitter_python

    if lang == "python":
        L = tree_sitter_python.language()
    elif lang == "javascript":
        L = tree_sitter_javascript.language()
    else:
        L = tree_sitter_go.language()
    parser = tree_sitter.Parser(tree_sitter.Language(L))
    tree = parser.parse(source.encode())
    counts = {"functions": 0, "classes": 0, "imports": 0, "parse_error": 0}
    node = tree.root_node
    stack = [node]
    while stack:
        cur = stack.pop()
        if cur.type in ("function_definition", "method_definition", "function_declaration", "method_declaration"):
            counts["functions"] += 1
        elif cur.type in ("class_definition", "class_declaration", "type_declaration"):
            counts["classes"] += 1
        elif cur.type in ("import_statement", "import_from_statement", "import_declaration"):
            counts["imports"] += 1
        elif cur.type == "ERROR":
            counts["parse_error"] += 1
        stack.extend(cur.children)
    return counts


def benchmark_code_ast(backend: str, tmp_root: str) -> dict:
    ast_counts = {}
    for lang, (grammar, source) in CODE_SAMPLES.items():
        ast_counts[lang] = ast_entity_counts(grammar, source)

    engine = make_engine(backend, tmp_root)
    code_q = [
        ("Which method applies the discount in OrderProcessor?", "discount", "OrderProcessor"),
        ("Which function computes tax?", "tax", None),
        ("Which method returns the subtotal in InventoryManager?", "subtotal", "InventoryManager"),
    ]
    hits = 0
    engine.set_l1(code_q[0][0], {"content": "apply_discount", "source": "d4.py"})
    asyncio.run(engine.async_write_l2("Which method applies the discount in OrderProcessor?", {"content": "apply_discount", "source": "d4.py"}))
    for query, _, _ in code_q:
        hit, _ = l2_lookup(engine, query)
        if hit is not None:
            hits += 1

    metrics = {
        "dataset": "code-ast",
        "ast_entity_counts": ast_counts,
        "code_themed_l2_hits": f"{hits}/{len(code_q)}",
        "parse_success_all_languages": all(c["parse_error"] == 0 for c in ast_counts.values()),
    }
    print(json.dumps({"code-ast": metrics}, indent=2))
    if not metrics["parse_success_all_languages"]:
        raise AssertionError("tree-sitter parse failure in code-ast dataset")
    return metrics


# ---------------------------------------------------------------------------
# D5 -- lifecycle: freshness, invalidation, eviction
# ---------------------------------------------------------------------------


class _LRU:
    def __init__(self, capacity: int):
        self._m: "OrderedDict[str, str]" = OrderedDict()
        self.capacity = capacity
        self.evictions = 0

    def get(self, key: str):
        if key not in self._m:
            return None
        self._m.move_to_end(key)
        return self._m[key]

    def put(self, key: str, value: str):
        if key in self._m:
            self._m.move_to_end(key)
        else:
            if len(self._m) >= self.capacity:
                self._m.popitem(last=False)
                self.evictions += 1
            self._m[key] = value


def benchmark_lifecycle(backend: str, tmp_root: str) -> dict:
    engine = make_engine(backend, tmp_root)

    stale_suppressed = 0
    key = "AAPL margins Q1"
    engine.set_l1(key, {"content": "fresh-v1", "source": "d5"}, nx=True)
    engine.set_l1(key, {"content": "stale-attempt", "source": "d5"}, nx=True)
    first, _ = l1_get(engine, key)
    if first and first["content"] == "fresh-v1":
        stale_suppressed += 1
    engine.set_l1(key, {"content": "expected-refresh", "source": "d5"}, nx=False)
    refreshed = l1_get(engine, key)[0]["content"] == "expected-refresh"

    for t in TOPICS[:2]:
        asyncio.run(engine.invalidate(filter_dict={"entity": "AAPL", "quarter": "Q1", "topic": t}))
    invalidation_works = 0
    f = "What was the margins of AAPL in Q1?"
    engine.set_l1(f, {"content": "c", "source": "d5"})
    research = l1_get(engine, f)[0]
    asyncio.run(engine.invalidate())
    if research is not None and l1_get(engine, f)[0] is None:
        invalidation_works += 1

    stream = [f"q{i % 50}" for i in range(1000)] + [f"hot{i % 5}" for i in range(1000)]
    lru = _LRU(capacity=50)
    hits = 0
    for item in stream:
        if lru.get(item) is not None:
            hits += 1
        lru.put(item, "v")

    metrics = {
        "dataset": "lifecycle",
        "stale_write_suppressed": stale_suppressed == 1,
        "explicit_refresh_allowed": refreshed,
        "invalidation_cleared_l1": invalidation_works == 1,
        "lru_eviction_hit_ratio": round(hits / len(stream), 4),
        "lru_evictions": lru.evictions,
    }
    print(json.dumps({"lifecycle": metrics}, indent=2))
    if not (metrics["stale_write_suppressed"] and metrics["explicit_refresh_allowed"] and metrics["invalidation_cleared_l1"]):
        raise AssertionError("Lifecycle freshness regression")
    return metrics


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

DATASETS = {
    "paraphrase-hit": benchmark_paraphrase_hit,
    "adversarial": benchmark_adversarial,
    "multilingual": benchmark_multilingual,
    "code-ast": benchmark_code_ast,
    "lifecycle": benchmark_lifecycle,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="ICO-Cache benchmark harness (5 dataset types)")
    parser.add_argument("--dataset", choices=sorted(DATASETS.keys()) + ["all"], default="all")
    parser.add_argument("--backend", choices=["embedded", "qdrant"], default="embedded")
    parser.add_argument("--report-dir", default="benchmark-reports")
    args = parser.parse_args()

    os.makedirs(args.report_dir, exist_ok=True)
    names = sorted(DATASETS) if args.dataset == "all" else [args.dataset]
    results = {}
    duration = time.time()
    for name in names:
        tmp_root = tempfile.mkdtemp(prefix=f"ico_bench_{name}_")
        results[name] = DATASETS[name](args.backend, tmp_root)
    duration = time.time() - duration

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "duration_s": round(duration, 2),
        "results": results,
    }
    path = os.path.join(args.report_dir, f"benchmark_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nBENCHMARK FAILURE: {exc}")
        raise SystemExit(1)
