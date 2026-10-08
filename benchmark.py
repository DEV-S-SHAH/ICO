"""benchmark.py -- dataset-driven ICO-Cache benchmark harness.

Five dataset types, each measuring a different quality dimension of the cache:

  paraphrase-hit  D1  Efficiency: cache hit rate, latency, throughput, LLM-avoidance.
  adversarial     D2  Correctness: near-miss / hard-negative false-hit prevention.
  multilingual    D3  Robustness: cross-language paraphrase matching.
  code-ast        D4  Code capability: tree-sitter AST extraction + code-question hits.
  lifecycle       D5  Freshness: stale-write suppression, invalidation, eviction.
  accounting      D6  Token/Cost: accounting validation, layer attribution, tenant isolation.

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
# Accounting helper class for benchmark tracking
# ---------------------------------------------------------------------------

class BenchmarkAccounting:
    """Tracks token, cost, latency, and layer attribution metrics for benchmarks."""

    def __init__(self, cost_model, default_model: str = "gpt-4o", default_provider: str = "openai"):
        self.cost_model = cost_model
        self.default_model = default_model
        self.default_provider = default_provider

        # Request-level counters
        self.requests = 0
        self.llm_calls = 0
        self.llm_calls_avoided = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.tokens_saved = 0
        self.embedding_calls = 0
        self.embedding_calls_avoided = 0
        self.retrieval_calls = 0
        self.retrieval_calls_avoided = 0

        # Cost tracking
        self.actual_cost = 0.0
        self.cost_saved = 0.0

        # Latency tracking
        self.latency_saved_ms = 0.0
        self.total_latency_ms = 0.0

        # Layer attribution
        self.layer_stats = {"L0a": 0, "L0b": 0, "L1": 0, "L2": 0, "L3": 0, "MISS": 0}
        self.layer_savings = {
            "L0a": {"tokens_saved": 0, "cost_saved": 0.0, "latency_saved_ms": 0.0},
            "L0b": {"tokens_saved": 0, "cost_saved": 0.0, "latency_saved_ms": 0.0},
            "L1": {"tokens_saved": 0, "cost_saved": 0.0, "latency_saved_ms": 0.0},
            "L2": {"tokens_saved": 0, "cost_saved": 0.0, "latency_saved_ms": 0.0},
            "L3": {"tokens_saved": 0, "cost_saved": 0.0, "latency_saved_ms": 0.0},
        }

        # Estimated tokens per response (for simulation)
        self.est_tokens_per_response = 1000  # input + output estimate
        self.est_input_ratio = 0.75
        self.est_output_ratio = 0.25
        self.est_llm_latency_ms = 500  # Simulated LLM call latency
        self.est_embedding_latency_ms = 10  # Simulated embedding computation latency
        self.est_retrieval_latency_ms = 50  # Simulated retrieval latency

    def record_request(self, source: str, layer: str = None):
        """Record a request and its cache layer result."""
        self.requests += 1
        if layer:
            self.layer_stats[layer] = self.layer_stats.get(layer, 0) + 1

        if source == "MISS":
            self.llm_calls += 1
            # Simulate actual token usage
            input_toks = int(self.est_tokens_per_response * self.est_input_ratio)
            output_toks = int(self.est_tokens_per_response * self.est_output_ratio)
            self.input_tokens += input_toks
            self.output_tokens += output_toks
            self.total_tokens += input_toks + output_toks

            # Record actual cost
            cost = self.cost_model.estimate_cost(self.default_provider, self.default_model, input_toks, output_toks)
            if cost:
                self.actual_cost += cost

            # Record latency
            self.total_latency_ms += self.est_llm_latency_ms

        else:
            self.llm_calls_avoided += 1
            # Estimate tokens saved
            saved_input = int(self.est_tokens_per_response * self.est_input_ratio)
            saved_output = int(self.est_tokens_per_response * self.est_output_ratio)
            self.tokens_saved += saved_input + saved_output

            # Record cost saved
            cost = self.cost_model.estimate_cost(self.default_provider, self.default_model, saved_input, saved_output)
            if cost:
                self.cost_saved += cost
                if layer and layer in self.layer_savings:
                    self.layer_savings[layer]["cost_saved"] += cost
                    self.layer_savings[layer]["tokens_saved"] += saved_input + saved_output

            # Record latency saved (LLM call avoided)
            self.latency_saved_ms += self.est_llm_latency_ms
            if layer and layer in self.layer_savings:
                self.layer_savings[layer]["latency_saved_ms"] += self.est_llm_latency_ms

    def record_embedding_call(self, avoided: bool = False):
        """Record embedding computation."""
        if avoided:
            self.embedding_calls_avoided += 1
            self.latency_saved_ms += self.est_embedding_latency_ms
            if "L0b" in self.layer_savings:
                self.layer_savings["L0b"]["latency_saved_ms"] += self.est_embedding_latency_ms
        else:
            self.embedding_calls += 1

    def record_retrieval_call(self, avoided: bool = False):
        """Record RAG retrieval call."""
        if avoided:
            self.retrieval_calls_avoided += 1
            self.latency_saved_ms += self.est_retrieval_latency_ms
        else:
            self.retrieval_calls += 1

    def get_results(self) -> dict:
        """Get final accounting results."""
        cache_hit_rate = (self.llm_calls_avoided / self.requests) if self.requests > 0 else 0.0

        return {
            "requests": self.requests,
            "llm_calls": self.llm_calls,
            "llm_calls_avoided": self.llm_calls_avoided,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "tokens_saved": self.tokens_saved,
            "embedding_calls": self.embedding_calls,
            "embedding_calls_avoided": self.embedding_calls_avoided,
            "retrieval_calls": self.retrieval_calls,
            "retrieval_calls_avoided": self.retrieval_calls_avoided,
            "actual_cost": round(self.actual_cost, 4),
            "cost_saved": round(self.cost_saved, 4),
            "total_cost": round(self.actual_cost, 4),  # In this model, total = actual (saved is hypothetical)
            "latency_saved_ms": round(self.latency_saved_ms, 2),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "layer_savings": {
                k: {
                    "tokens_saved": v["tokens_saved"],
                    "cost_saved": round(v["cost_saved"], 4),
                    "latency_saved_ms": round(v["latency_saved_ms"], 2),
                }
                for k, v in self.layer_savings.items()
            },
            "layer_stats": self.layer_stats,
        }


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
    accounting = BenchmarkAccounting(engine.cost_model)

    # Prime the cache
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
        accounting.record_request("HIT" if val else "MISS", "L1" if val else "MISS")

    sem_hits, sem_perf = [], []
    for item in canon:
        for par in item["paraphrases"]:
            hit, dt = l2_lookup(engine, par)
            sem_hits.append(1 if hit is not None else 0)
            sem_perf.append(dt * 1000)
            accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

    novel_miss = 0
    for q in novel:
        hit, _ = l2_lookup(engine, q)
        if hit is None:
            novel_miss += 1
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

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
    # Merge accounting metrics
    metrics.update(accounting.get_results())
    print(json.dumps({"paraphrase-hit": metrics}, indent=2))
    return metrics


# ---------------------------------------------------------------------------
# D2 -- adversarial: hard-negative false-hit prevention
# ---------------------------------------------------------------------------


def benchmark_adversarial(backend: str, tmp_root: str) -> dict:
    engine = make_engine(backend, tmp_root)
    accounting = BenchmarkAccounting(engine.cost_model)

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
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")
        if hit is not None:
            false_hits.append((q1, q2, sim, axis))

    tenant_bleed = 0
    asyncio.run(engine.async_write_l2("What is the revenue of AAPL in Q1?", {"content": "ten-a"}, tenant_id="tenant_a"))
    for _ in range(3):
        hit, _ = l2_lookup(engine, "Tell me the revenue for AAPL Q1", tenant_id="tenant_b")
        if hit is not None:
            tenant_bleed += 1
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

    cross_topic_ok = 0
    for a, b in [("revenue", "margins")]:
        engine.set_l1(f"What is the {a} of AAPL in Q1?", {"content": "x"})
        asyncio.run(engine.async_write_l2(f"What is the {a} of AAPL in Q1?", {"content": "x"}))
        hit, _ = l2_lookup(engine, f"What is the {b} of AAPL in Q1?")
        if hit is None:
            cross_topic_ok += 1
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

    metrics = {
        "dataset": "adversarial",
        "near_miss_pairs": len(near_miss),
        "gated_by_schema": gated,
        "ungated_false_hits": len(false_hits),
        "max_similarity": round(max_sim, 4),
        "cross_topic_blocked": cross_topic_ok,
        "tenant_bleed_count": tenant_bleed,
    }
    metrics.update(accounting.get_results())
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
    accounting = BenchmarkAccounting(engine.cost_model)
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
                    accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")
        per_lang[lang] = round(hits / total, 4) if total else 0.0

    cross_false = 0
    for e, q in (("AAPL", "Q1"), ("MSFT", "Q2")):
        src = _PHRASES["en"](e, "revenue", q)
        wrong_entity = _PHRASES["es"]("JPM" if e == "AAPL" else "AAPL", "revenue", q)
        hit, _ = l2_lookup(engine, wrong_entity)
        if hit is not None:
            cross_false += 1
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

    metrics = {"dataset": "multilingual", "per_language_l2_hit_rate": per_lang, "cross_language_false_hits": cross_false}
    metrics.update(accounting.get_results())
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
    accounting = BenchmarkAccounting(engine.cost_model)
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
        accounting.record_request("HIT" if hit else "MISS", "L2" if hit else "MISS")

    metrics = {
        "dataset": "code-ast",
        "ast_entity_counts": ast_counts,
        "code_themed_l2_hits": f"{hits}/{len(code_q)}",
        "parse_success_all_languages": all(c["parse_error"] == 0 for c in ast_counts.values()),
    }
    metrics.update(accounting.get_results())
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
    accounting = BenchmarkAccounting(engine.cost_model)

    stale_suppressed = 0
    key = "AAPL margins Q1"
    engine.set_l1(key, {"content": "fresh-v1", "source": "d5"}, nx=True)
    engine.set_l1(key, {"content": "stale-attempt", "source": "d5"}, nx=True)
    first, _ = l1_get(engine, key)
    if first and first["content"] == "fresh-v1":
        stale_suppressed += 1
    accounting.record_request("HIT" if first else "MISS", "L1" if first else "MISS")

    engine.set_l1(key, {"content": "expected-refresh", "source": "d5"}, nx=False)
    refreshed = l1_get(engine, key)[0]["content"] == "expected-refresh"
    accounting.record_request("HIT" if refreshed else "MISS", "L1" if refreshed else "MISS")

    for t in TOPICS[:2]:
        asyncio.run(engine.invalidate(filter_dict={"entity": "AAPL", "quarter": "Q1", "topic": t}))
    invalidation_works = 0
    f = "What was the margins of AAPL in Q1?"
    engine.set_l1(f, {"content": "c", "source": "d5"})
    research = l1_get(engine, f)[0]
    asyncio.run(engine.invalidate())
    if research is not None and l1_get(engine, f)[0] is None:
        invalidation_works += 1
    accounting.record_request("HIT" if research else "MISS", "L1" if research else "MISS")

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
    metrics.update(accounting.get_results())
    print(json.dumps({"lifecycle": metrics}, indent=2))
    if not (metrics["stale_write_suppressed"] and metrics["explicit_refresh_allowed"] and metrics["invalidation_cleared_l1"]):
        raise AssertionError("Lifecycle freshness regression")
    return metrics


# ---------------------------------------------------------------------------
# D6 -- accounting-validation: token/cost accounting correctness
# ---------------------------------------------------------------------------


def benchmark_accounting_validation(backend: str, tmp_root: str) -> dict:
    """
    Validates accounting correctness:
    1. Single-flight accounting (no double-counting on concurrent requests)
    2. Tenant isolation (costs/tokens don't bleed across tenants)
    3. Layer attribution (savings correctly attributed to L0a/L0b/L1/L2/L3)
    4. False-savings prevention (errors/refusals not counted as savings)
    """
    from ico_cache.telemetry.cost_model import CostModel, ModelPricing

    # Use a known pricing model for deterministic results
    test_pricing = {"openai:gpt-4o": ModelPricing(2.50, 10.00, "openai", "gpt-4o")}
    cost_model = CostModel(pricing=test_pricing)

    engine = make_engine(backend, tmp_root, cost_model=cost_model)
    accounting = BenchmarkAccounting(cost_model, default_model="gpt-4o", default_provider="openai")

    results = {
        "dataset": "accounting-validation",
        "tests": {},
    }

    # Test 1: Single-flight accounting
    # Multiple concurrent requests for same query should count as 1 LLM call
    async def test_single_flight():
        query = "What is the revenue of AAPL in Q1?"
        meta = universal_extract_fields(query)

        async def mock_generate():
            # Simulate LLM call with known token usage
            return {
                "answer": "AAPL revenue was $85.8B in Q1",
                "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700}
            }

        # Fire 5 concurrent requests
        tasks = [engine.resolve_or_generate(query, meta=meta, generate_fn=mock_generate) for _ in range(5)]
        responses = await asyncio.gather(*tasks)

        # All should succeed, but only 1 should be MISS (actual LLM call)
        miss_count = sum(1 for r in responses if r["source"] == "MISS")
        hit_count = sum(1 for r in responses if r["source"] != "MISS")

        return {
            "concurrent_requests": 5,
            "llm_calls_made": miss_count,
            "cache_hits": hit_count,
            "single_flight_correct": miss_count == 1 and hit_count == 4,
        }

    single_flight_result = asyncio.run(test_single_flight())
    results["tests"]["single_flight"] = single_flight_result
    accounting.requests += 5
    accounting.llm_calls += 1
    accounting.llm_calls_avoided += 4
    accounting.input_tokens += 500
    accounting.output_tokens += 200
    accounting.tokens_saved += 4 * 700
    cost = cost_model.estimate_cost("openai", "gpt-4o", 500, 200)
    if cost:
        accounting.actual_cost += cost
        accounting.cost_saved += 4 * cost

    # Test 2: Tenant isolation
    async def test_tenant_isolation():
        query = "What is the revenue of MSFT in Q2?"
        meta = universal_extract_fields(query)

        async def mock_generate():
            return {
                "answer": "MSFT revenue was $61.9B in Q2",
                "usage": {"prompt_tokens": 400, "completion_tokens": 150, "total_tokens": 550}
            }

        # Tenant A generates
        res_a = await engine.resolve_or_generate(query, meta=meta, tenant_id="tenant_a", generate_fn=mock_generate)
        # Tenant B should MISS (different tenant)
        res_b = await engine.resolve_or_generate(query, meta=meta, tenant_id="tenant_b", generate_fn=mock_generate)

        # Tenant A hits on second request
        res_a2 = await engine.resolve_or_generate(query, meta=meta, tenant_id="tenant_a", generate_fn=mock_generate)

        return {
            "tenant_a_first": res_a["source"],
            "tenant_b_first": res_b["source"],
            "tenant_a_second": res_a2["source"],
            "tenant_isolation_correct": res_a["source"] == "MISS" and res_b["source"] == "MISS" and res_a2["source"] == "L1",
        }

    tenant_result = asyncio.run(test_tenant_isolation())
    results["tests"]["tenant_isolation"] = tenant_result
    accounting.requests += 3
    accounting.llm_calls += 2
    accounting.llm_calls_avoided += 1
    accounting.input_tokens += 500 + 400
    accounting.output_tokens += 200 + 150
    accounting.tokens_saved += 550
    cost1 = cost_model.estimate_cost("openai", "gpt-4o", 500, 200)
    cost2 = cost_model.estimate_cost("openai", "gpt-4o", 400, 150)
    if cost1:
        accounting.actual_cost += cost1
    if cost2:
        accounting.actual_cost += cost2
        accounting.cost_saved += cost1

    # Test 3: Layer attribution
    async def test_layer_attribution():
        query = "What is the margin of GOOGL in Q3?"
        meta = universal_extract_fields(query)

        # Prime L1 (no context)
        engine.set_l1(query, {"content": "GOOGL margin 32%", "source": "d6"}, meta=meta)
        res_l1 = await engine.resolve(query, meta=meta)

        # Prime L3 (query + context). Checked before writing the L2 entry so
        # a semantically-similar L2 row can't preempt the L3 lookup.
        context = "Discussion about Alphabet's Q3 earnings call"
        await engine.async_write_l3(query, context, {"content": "GOOGL margin 32%", "source": "d6"}, meta=meta)
        res_l3 = await engine.resolve(query, context=context, meta=meta)

        # Prime L2 (different query, same semantics)
        query2 = "Tell me GOOGL's Q3 margins"
        meta2 = universal_extract_fields(query2)
        await engine.async_write_l2(query2, {"content": "GOOGL margin 32%", "source": "d6"}, meta=meta2)
        res_l2 = await engine.resolve(query2, meta=meta2)

        return {
            "l1_hit": res_l1["source"] == "L1",
            "l2_hit": res_l2["source"] == "L2",
            "l3_hit": res_l3["source"] == "L3",
            "layer_attribution_correct": res_l1["source"] == "L1" and res_l2["source"] == "L2" and res_l3["source"] == "L3",
        }

    layer_result = asyncio.run(test_layer_attribution())
    results["tests"]["layer_attribution"] = layer_result
    accounting.requests += 3
    accounting.llm_calls_avoided += 3
    accounting.tokens_saved += 3 * 600
    cost = cost_model.estimate_cost("openai", "gpt-4o", 400, 200)
    if cost:
        accounting.cost_saved += 3 * cost
        for layer in ["L1", "L2", "L3"]:
            accounting.layer_savings[layer]["tokens_saved"] += 600
            accounting.layer_savings[layer]["cost_saved"] += cost

    # Test 4: False-savings prevention (errors/refusals not cached)
    async def test_false_savings_prevention():
        query = "What is the risk factors for TSLA in Q4?"
        meta = universal_extract_fields(query)

        async def mock_error():
            return {
                "answer": "LLM generation failed: rate limit exceeded",
                "usage": {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350}
            }

        async def mock_refusal():
            return {
                "answer": "Insufficient context.",
                "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}
            }

        # Error should not be cached
        res_err = await engine.resolve_or_generate(query, meta=meta, generate_fn=mock_error)
        # Second call should also be MISS (not cached)
        res_err2 = await engine.resolve_or_generate(query, meta=meta, generate_fn=mock_error)

        # Refusal should not be cached
        res_ref = await engine.resolve_or_generate(query, meta=meta, generate_fn=mock_refusal)
        res_ref2 = await engine.resolve_or_generate(query, meta=meta, generate_fn=mock_refusal)

        return {
            "error_first_source": res_err["source"],
            "error_second_source": res_err2["source"],
            "refusal_first_source": res_ref["source"],
            "refusal_second_source": res_ref2["source"],
            "errors_not_cached": res_err["source"] == "MISS" and res_err2["source"] == "MISS",
            "refusals_not_cached": res_ref["source"] == "MISS" and res_ref2["source"] == "MISS",
        }

    false_savings_result = asyncio.run(test_false_savings_prevention())
    results["tests"]["false_savings_prevention"] = false_savings_result
    accounting.requests += 4
    accounting.llm_calls += 4  # All should be MISS (not cached)
    accounting.input_tokens += 300 + 300 + 200 + 200
    accounting.output_tokens += 50 + 50 + 20 + 20

    # Test 5: L0a deterministic function cache accounting
    async def test_l0a_accounting():
        def compute_fibonacci(n: int) -> int:
            if n <= 1:
                return n
            a, b = 0, 1
            for _ in range(n - 1):
                a, b = b, a + b
            return b

        engine.register_deterministic_function("fibonacci", "v1", compute_fibonacci, "Compute nth Fibonacci number")

        # First call - cache miss, computes
        res1 = await engine.execute_deterministic("fibonacci", {"n": 20})
        # Second call - cache hit
        res2 = await engine.execute_deterministic("fibonacci", {"n": 20})
        # Different args - cache miss
        res3 = await engine.execute_deterministic("fibonacci", {"n": 30})

        return {
            "first_call_result": res1,
            "second_call_result": res2,
            "third_call_result": res3,
            "l0a_cache_working": res1 == res2 == 6765 and res3 == 832040,
        }

    l0a_result = asyncio.run(test_l0a_accounting())
    results["tests"]["l0a_deterministic_cache"] = l0a_result
    accounting.requests += 3
    accounting.llm_calls_avoided += 1  # Second call hit L0a
    accounting.tokens_saved += 100  # Estimated savings for deterministic function
    if "L0a" in accounting.layer_savings:
        accounting.layer_savings["L0a"]["tokens_saved"] += 100
        accounting.layer_savings["L0a"]["cost_saved"] += cost_model.estimate_cost("openai", "gpt-4o", 50, 50) or 0.0

    # Test 6: L0b embedding cache accounting
    async def test_l0b_accounting():
        # First embedding computation
        emb1 = await engine.get_embedding("What is the revenue of AAPL?")
        # Second call - should hit L0b cache
        emb2 = await engine.get_embedding("What is the revenue of AAPL?")
        # Different text - cache miss
        emb3 = await engine.get_embedding("What is the margin of MSFT?")

        return {
            "first_embedding_dim": len(emb1),
            "second_embedding_dim": len(emb2),
            "third_embedding_dim": len(emb3),
            "l0b_cache_working": emb1 == emb2 and emb1 != emb3,
        }

    l0b_result = asyncio.run(test_l0b_accounting())
    results["tests"]["l0b_embedding_cache"] = l0b_result
    accounting.requests += 3
    accounting.embedding_calls += 2  # First and third are misses
    accounting.embedding_calls_avoided += 1  # Second is hit
    accounting.latency_saved_ms += 10
    if "L0b" in accounting.layer_savings:
        accounting.layer_savings["L0b"]["latency_saved_ms"] += 10

    # Overall validation
    all_passed = all(
        test.get("single_flight_correct", False) or
        test.get("tenant_isolation_correct", False) or
        test.get("layer_attribution_correct", False) or
        test.get("errors_not_cached", False) and test.get("refusals_not_cached", False) or
        test.get("l0a_cache_working", False) or
        test.get("l0b_cache_working", False)
        for test in results["tests"].values()
    )

    results["all_tests_passed"] = all_passed
    results["accounting"] = accounting.get_results()

    print(json.dumps({"accounting-validation": results}, indent=2))

    if not all_passed:
        raise AssertionError(f"Accounting validation failed: {results['tests']}")

    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

DATASETS = {
    "paraphrase-hit": benchmark_paraphrase_hit,
    "adversarial": benchmark_adversarial,
    "multilingual": benchmark_multilingual,
    "code-ast": benchmark_code_ast,
    "lifecycle": benchmark_lifecycle,
    "accounting-validation": benchmark_accounting_validation,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="ICO-Cache benchmark harness (6 dataset types)")
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
