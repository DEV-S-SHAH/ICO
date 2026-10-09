#!/usr/bin/env python3
"""200-query all-layer trial against the live real-rag-demo.

Exercises every tier of the ICO-Cache cascade with deliberately difficult,
domain-grounded questions spanning the three corpus documents
(attention_is_all_you_need.pdf, ico_cache_architecture.pdf,
retrieval_augmented_generation.pdf):

  L0a  deterministic function / math / health cache
  L0b  FastEmbed embedding vector cache        (exercised implicitly in L1-L5)
  L1   exact prompt-hash match
  L2   semantic vector cosine match            (paraphrased hard questions)
  L3   context-aware dual-vector dialogue match
  L4   RAG retrieval chunk-set cache           (bypass path re-query)
  L5   assembled-context token cache           (bypass path re-query)

Exactly 200 requests. Writes a JSON report and prints a per-block summary.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("ICO_DEMO_URL", "http://127.0.0.1:8000")
MODEL = "gemini-1.5-flash"
REPORT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmark-reports",
    "trial_200_all_layers.json",
)

# ---------------------------------------------------------------------------
# Hard, domain-grounded question pools
# ---------------------------------------------------------------------------

HARD_MATH = [
    "calc: (12873 * 47 - 2934) / 7",
    "calc: 2 ** 32",
    "calc: round(1234567.891 * 3.14159, 2)",
    "calc: (98.6 - 32) * 5 / 9",
    "calc: 998244353 % 97",
    "calc: 75000 * (1.072 ** 15)",
    "calc: sum(range(1, 10001))",
    "calc: 65536 / 2 ** 8",
    "calc: (4500000 - 3200000) / 4500000",
    "calc: sqrt(1048576) + factorial(5)",
]

ATTENTION_Q = [
    "How does multi-head attention differ from single-head attention in the Transformer architecture?",
    "What is the role of positional encodings in the Transformer and why are they necessary?",
    "Explain the scaled dot-product attention formula and why the scaling factor 1/sqrt(d_k) is applied.",
    "Why does the Transformer wrap each sub-layer with residual connections and layer normalization?",
    "What is the per-layer computational complexity of self-attention in sequence length and model dimension?",
    "How do the encoder and decoder stacks differ in the Transformer architecture?",
    "What regularization techniques were applied when training the Transformer base model?",
    "Why did the Transformer outperform recurrent and convolutional sequence models?",
]

ICO_CACHE_Q = [
    "How does the ICO-Cache tiered hierarchy reduce end-to-end inference cost in production LLM systems?",
    "What mechanisms prevent cross-entity cache bleed and enforce tenant isolation in ICO-Cache?",
    "Explain how hard-gate metadata validation eliminates false-positive semantic cache hits.",
    "How does the L0b embedding cache reduce redundant vectorization work across the cascade?",
    "What is the role of single-flight coalescing during concurrent identical cache misses?",
    "How do L4 retrieval caching and L5 assembled-context caching interact in the RAG pipeline?",
    "What observability primitives does ICO-Cache expose for production monitoring?",
    "How does the decision-trace subsystem attribute cost and latency savings per cache layer?",
]

RAG_Q = [
    "How does retrieval-augmented generation reduce hallucination compared with a parametric-only LLM?",
    "What are the tradeoffs between dense and sparse retrieval for RAG grounding?",
    "Why is provenance and citation tracking important in retrieval-augmented generation?",
    "How does chunking granularity affect retrieval quality and context assembly in RAG?",
    "What is the effect of retrieved context length on generator faithfulness and latency?",
    "How can reranking improve the precision of retrieved passages in a RAG pipeline?",
    "What failure modes arise when retrieval returns noisy or irrelevant evidence?",
    "How does multi-hop retrieval support complex multi-part questions?",
]

# Semantically equivalent paraphrases of a subset of the hard questions.
PARAPHRASES = [
    ("How does the ICO-Cache tiered hierarchy reduce end-to-end inference cost in production LLM systems?",
     "In what ways does the multi-tier ICO-Cache cascade lower total inference expense for production LLM deployments?"),
    ("What mechanisms prevent cross-entity cache bleed and enforce tenant isolation in ICO-Cache?",
     "Which safeguards stop cached answers from leaking between tenants or entities in ICO-Cache?"),
    ("How does the L0b embedding cache reduce redundant vectorization work across the cascade?",
     "In what way does the L0b embedding vector cache cut down repeated embedding computation in the tier hierarchy?"),
    ("What is the role of single-flight coalescing during concurrent identical cache misses?",
     "How does single-flight request coalescing behave when multiple identical queries miss the cache simultaneously?"),
    ("How do L4 retrieval caching and L5 assembled-context caching interact in the RAG pipeline?",
     "What is the interaction between L4 retrieval chunk caching and L5 assembled context caching inside the RAG flow?"),
    ("How does retrieval-augmented generation reduce hallucination compared with a parametric-only LLM?",
     "Why does RAG grounding lower hallucination relative to relying solely on a model's parametric memory?"),
    ("What are the tradeoffs between dense and sparse retrieval for RAG grounding?",
     "Compare the pros and cons of dense versus sparse retrieval approaches when grounding a RAG system."),
    ("Why is provenance and citation tracking important in retrieval-augmented generation?",
     "What makes source provenance and citation tracking essential for retrieval-augmented generation?"),
    ("How does chunking granularity affect retrieval quality and context assembly in RAG?",
     "In what way does the granularity of document chunking influence retrieval accuracy and context construction?"),
    ("What is the effect of retrieved context length on generator faithfulness and latency?",
     "How does the amount of retrieved context impact answer faithfulness and response latency?"),
    ("Explain the scaled dot-product attention formula and why the scaling factor 1/sqrt(d_k) is applied.",
     "Describe scaled dot-product attention and the reason the 1/sqrt(d_k) scaling term is used."),
    ("What is the per-layer computational complexity of self-attention in sequence length and model dimension?",
     "What is the asymptotic per-layer cost of self-attention as a function of sequence length and embedding size?"),
    ("What failure modes arise when retrieval returns noisy or irrelevant evidence?",
     "Which failure modes can occur when a retriever supplies noisy or off-topic passages?"),
    ("What is the role of positional encodings in the Transformer and why are they necessary?",
     "Why does the Transformer require positional encodings and what purpose do they serve?"),
    ("How can reranking improve the precision of retrieved passages in a RAG pipeline?",
     "In what ways does a reranking stage increase the relevance of retrieved passages in RAG?"),
]

# Difficult multi-turn context dialogues: (context, [turn1, turn2, turn3, turn4, turn5])
DIALOGUES = [
    (
        "Production architecture review of ICO-Cache deployment covering tenant isolation and false-hit guardrails.",
        [
            "What safeguards guarantee that cached responses never leak across tenants in the ICO-Cache hierarchy?",
            "Explain how the hard-gate metadata fingerprint blocks false-positive semantic hits under multi-tenancy.",
            "How is tenant isolation enforced across L1, L2, and L3 cache partitions?",
            "What role does the timing-safe authenticated payload filter play in preventing cross-tenant bleed?",
            "Summarize the isolation guarantees that make ICO-Cache safe for regulated multi-tenant workloads.",
        ],
    ),
    (
        "Deep-dive on the Transformer attention mechanism and its computational scaling behavior.",
        [
            "How does scaled dot-product attention operate and why is the dot product divided by sqrt(d_k)?",
            "What is the asymptotic complexity of self-attention with respect to sequence length and model dimension?",
            "Why does multi-head attention increase representational capacity without changing per-head cost?",
            "How do residual connections and layer normalization stabilize training in the Transformer?",
            "Summarize the attention mechanism and its scaling limits for long sequences.",
        ],
    ),
    (
        "RAG evaluation session focused on retrieval faithfulness, provenance, and grounding quality.",
        [
            "How does retrieval-augmented generation improve factual grounding relative to a parametric-only model?",
            "Why is citation and provenance tracking essential when evaluating RAG answer faithfulness?",
            "What failure modes appear when the retriever returns noisy or weakly relevant evidence?",
            "How does reranking the retrieved passages raise precision before context assembly?",
            "Summarize the key retrieval-quality levers that determine RAG grounding faithfulness.",
        ],
    ),
    (
        "Cost engineering discussion on the ICO-Cache decision-trace and accounting subsystems.",
        [
            "How does the decision-trace subsystem attribute latency and token savings to individual cache layers?",
            "What accounting primitives does ICO-Cache expose to quantify LLM cost avoided per cache hit?",
            "How is single-flight coalescing reflected in the cost and concurrency accounting?",
            "How do L4 retrieval caching and L5 context caching contribute to measured token savings?",
            "Summarize how observability and accounting together justify the ICO-Cache cost reduction.",
        ],
    ),
    (
        "Long-context Transformer training discussion on regularization and optimization stability.",
        [
            "What regularization techniques kept the Transformer base model from overfitting during training?",
            "Why are warmup learning-rate schedules important for stable Transformer optimization?",
            "How does label smoothing affect model calibration and perplexity?",
            "Why did the Transformer scale better than recurrent architectures for long sequences?",
            "Summarize the training-regimen choices that made the Transformer converge reliably.",
        ],
    ),
    (
        "Enterprise RAG deployment review covering chunking, retrieval, and reranking tradeoffs.",
        [
            "How does chunking granularity influence retrieval quality and downstream context assembly?",
            "What are the tradeoffs between dense and sparse retrieval for enterprise RAG grounding?",
            "How does retrieved context length affect generator faithfulness and end-to-end latency?",
            "How does multi-hop retrieval answer complex multi-part enterprise questions?",
            "Summarize the retrieval-design decisions that most affect RAG answer quality.",
        ],
    ),
    (
        "Safety review of semantic caching failure modes and false-hit prevention.",
        [
            "Which false-hit failure modes can a naive vector cache introduce in production?",
            "How does hard-gate metadata validation suppress semantically close but incorrect cache hits?",
            "How does the serve-threshold similarity gate trade hit rate against correctness risk?",
            "What tenant-scoped information must be part of every cache key to prevent bleed?",
            "Summarize the guardrails that keep ICO-Cache false-hit rate at zero in evaluation.",
        ],
    ),
    (
        "Architecture review of the L0b embedding cache and vector-search economics.",
        [
            "How does the L0b FastEmbed cache eliminate redundant embedding computation?",
            "What are the latency savings attributable to caching query embeddings across the cascade?",
            "How does model-version pinning keep L0b embeddings consistent over time?",
            "Why is embedding-cache correctness critical before any semantic tier is consulted?",
            "Summarize how L0b contributes to overall cascade latency reduction.",
        ],
    ),
    (
        "RAG provenance and evaluation methodology discussion.",
        [
            "How should provenance metadata be structured to support auditable RAG answers?",
            "What evaluation methodology best measures retrieval faithfulness versus answer correctness?",
            "How does noisy retrieval evidence degrade generator faithfulness in measurable ways?",
            "Why does citation tracking matter for regulated RAG applications?",
            "Summarize a robust methodology for validating retrieval-augmented generation outputs.",
        ],
    ),
    (
        "Transformer inference efficiency discussion covering attention complexity and long sequences.",
        [
            "Why does self-attention become a bottleneck for very long input sequences?",
            "How does the quadratic attention cost scale with sequence length?",
            "What is the effect of model dimension on the constant factor of attention cost?",
            "How do the encoder and decoder stacks differ in their computational demands?",
            "Summarize the efficiency limitations of the vanilla Transformer attention mechanism.",
        ],
    ),
]

# Hard retrieval questions used to exercise the L4 retrieval cache and
# L5 assembled-context cache through the bypass path (outer L1/L2/L3 skipped).
L4_QUERIES = [
    "What exact validation steps does the hard gate perform before a semantic cache hit is served?",
    "Detail the token accounting fields recorded for every cache hit and miss in the usage tracker.",
    "How does the decision trace represent per-layer hit/miss outcomes and reuse sources?",
    "What is the precise key construction for L1 exact prompt caching across tenants and models?",
    "Describe the dual-vector scoring thresholds used by the L3 context-aware cache.",
    "How is the L4 retrieval cache key derived from the query and corpus version?",
    "What chunk-hash inputs feed the L5 assembled-context cache key?",
    "Explain how content sniffing selects a document loader for universal ingestion.",
    "What are the concurrency guarantees of single-flight coalescing under load?",
    "How does the serve-threshold parameter influence semantic cache precision?",
    "What metrics does the Prometheus endpoint expose for cache observability?",
    "How does tenant-scoped partitioning isolate vector collections in Qdrant?",
    "What role does the L0b embedding cache play before L2 vector search executes?",
    "How are cache invalidations propagated across the L1, L2, and L3 tiers?",
    "Describe the end-to-end flow from a RAG query miss to a stored L1 and L2 entry.",
]


def post_query(query, context=None, bypass=False):
    url = f"{BASE_URL}/rag/query"
    body = {"query": query, "model": MODEL}
    if context:
        body["context"] = context
    if bypass:
        body["bypass_cache"] = True
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed = (time.time() - t0) * 1000
    cache = data.get("cache", {}) or {}
    hit = bool(cache.get("hit"))
    layer = cache.get("layer") or "MISS"
    return {
        "query": query,
        "context": bool(context),
        "bypass": bypass,
        "hit": hit,
        "layer": layer if hit else "MISS",
        "similarity": cache.get("similarity"),
        "tokens_saved": cache.get("tokens_saved", 0) or 0,
        "latency_ms": round(elapsed, 1),
    }


def main():
    print("=" * 100)
    print("  ICO-CACHE: 200-QUERY ALL-LAYER TRIAL (L0a / L0b / L1 / L2 / L3 / L4 / L5)")
    print(f"  Target: {BASE_URL}   Model: {MODEL}")
    print("=" * 100)

    results = []
    idx = 0

    def run(label, query, context=None, bypass=False):
        nonlocal idx
        idx += 1
        try:
            r = post_query(query, context=context, bypass=bypass)
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx:03d}/200] [ERROR] {query[:52]:<52} {exc}")
            return
        badge = f"[{r['layer']} HIT]" if r["hit"] else "[MISS]"
        sim = f" sim={r['similarity']:.3f}" if r["similarity"] else ""
        print(
            f"[{idx:03d}/200] {label:<6} {badge:<14}{sim:<11} "
            f"{query[:50]:<50} {r['latency_ms']:7.1f}ms saved {r['tokens_saved']:>4}"
        )
        results.append(r)

    # ---- Block 1: L0a deterministic (30) ---------------------------------
    print("\n--- Block 1/6: L0a deterministic function cache (30) ---")
    for i in range(30):
        q = HARD_MATH[i % len(HARD_MATH)]
        if i >= len(HARD_MATH) and i % 3 == 0:
            q = "ping" if i % 2 == 0 else "version"
        run("L0a", q)

    # ---- Block 2: L1 exact match (30) ------------------------------------
    print("\n--- Block 2/6: L1 exact prompt-hash match (30) ---")
    l1_pool = (ICO_CACHE_Q + RAG_Q)[:15]
    for q in l1_pool:
        run("L1-miss", q)
    for q in l1_pool:
        run("L1", q)

    # ---- Block 3: L2 semantic paraphrase (30) ----------------------------
    print("\n--- Block 3/6: L2 semantic vector match on difficult paraphrases (30) ---")
    for base, _ in PARAPHRASES:
        run("L2-base", base)
    for _, para in PARAPHRASES:
        run("L2", para)

    # ---- Block 4: L3 context-aware dialogues (50) ------------------------
    print("\n--- Block 4/6: L3 context-aware multi-turn dialogues (50) ---")
    for ctx, turns in DIALOGUES:
        run("L3-base", turns[0], context=ctx)
        for turn in turns[1:]:
            run("L3", turn, context=ctx)

    # ---- Block 5: L4 retrieval cache / L5 context cache (30) -------------
    print("\n--- Block 5/6: L4 retrieval + L5 assembled-context cache via bypass path (30) ---")
    for q in L4_QUERIES:
        run("L4-base", q, bypass=True)
    for q in L4_QUERIES:
        run("L4/L5", q, bypass=True)

    # ---- Block 6: mixed verification (30) --------------------------------
    print("\n--- Block 6/6: mixed verification across tiers (30) ---")
    for i in range(10):
        run("L0a", HARD_MATH[i % len(HARD_MATH)])
    for q in l1_pool[:10]:
        run("L1", q)
    for ctx, turns in DIALOGUES[:10]:
        run("L3", turns[2], context=ctx)

    # ---- Summary ---------------------------------------------------------
    total = len(results)
    hits = sum(1 for r in results if r["hit"])
    by_layer = {}
    for r in results:
        if r["hit"]:
            by_layer[r["layer"]] = by_layer.get(r["layer"], 0) + 1
    tokens_saved = sum(r["tokens_saved"] for r in results)
    hit_lat = [r["latency_ms"] for r in results if r["hit"]]
    miss_lat = [r["latency_ms"] for r in results if not r["hit"]]
    avg = lambda xs: (sum(xs) / len(xs)) if xs else 0.0  # noqa: E731

    # Pull the internal-layer metrics (L0b / L4 / L5).
    layer_metrics = {}
    try:
        with urllib.request.urlopen(f"{BASE_URL}/v1/cache/metrics", timeout=10) as resp:
            layer_metrics = json.loads(resp.read().decode("utf-8")).get("layers", {})
    except Exception:  # noqa: BLE001
        pass

    print("\n" + "=" * 100)
    print("  200-QUERY ALL-LAYER TRIAL SUMMARY")
    print("=" * 100)
    print(f"  Total requests       : {total}")
    print(f"  Cache hits           : {hits} ({hits / total * 100:.1f}%)")
    print(f"  Cache misses (LLM)   : {total - hits}")
    print(f"  Tokens saved         : {tokens_saved}")
    print(f"  Avg hit latency      : {avg(hit_lat):.1f} ms")
    print(f"  Avg miss latency     : {avg(miss_lat):.1f} ms")
    print("  Winning-layer hits:")
    for layer in ("L0a", "L1", "L2", "L3"):
        print(f"    - {layer:<4}: {by_layer.get(layer, 0)}")
    print("  Internal cascade metrics (cumulative):")
    for layer in ("L0b", "L4", "L5"):
        m = layer_metrics.get(layer, {})
        print(
            f"    - {layer:<4}: {m.get('requests', 0)} reqs, "
            f"hitRate {m.get('hitRate', 0):.3f}, "
            f"latencySaved {m.get('latencySaved', 0)} ms"
        )
    print("=" * 100)

    report = {
        "summary": {
            "total": total,
            "hits": hits,
            "misses": total - hits,
            "hit_rate": round(hits / total, 4) if total else 0.0,
            "tokens_saved": tokens_saved,
            "avg_hit_latency_ms": round(avg(hit_lat), 1),
            "avg_miss_latency_ms": round(avg(miss_lat), 1),
            "winning_layer_hits": by_layer,
            "internal_layers": {
                k: layer_metrics.get(k, {}) for k in ("L0b", "L4", "L5")
            },
        },
        "results": results,
    }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
