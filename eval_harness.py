import argparse
import json
import os
import sys
import numpy as np
from fastembed import TextEmbedding
from qdrant_client import QdrantClient

from ico_cache.core.metadata_guard import hard_gate
from examples.universal_schema import extract_fields as universal_extract_fields, universal_schema
from examples.financial_schema import extract_fields as financial_extract_fields

embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def load_jsonl(filepath):
    data = []
    if not os.path.exists(filepath):
        return data
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def get_embedding(text):
    return list(embedder.embed([text]))[0].tolist()


def ingest_corpus_into_tenant(tenant_id: str = "eval_tenant"):
    """Ingests all three corpus types (text, structured, code) into a single tenant."""
    from ico_cache.loaders.auto_loader import AutoLoader
    from ico_cache.core.cache_engine import CacheEngine
    from ico_cache.backends.vector.lancedb_store import LanceDBStore
    from ico_cache.backends.exact.sqlite_store import SQLiteStore
    from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
    import asyncio

    test_dir = "/tmp/ico_cache_eval_tenant"
    os.makedirs(test_dir, exist_ok=True)
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=os.path.join(test_dir, "lancedb")),
        exact_store=SQLiteStore(db_path=os.path.join(test_dir, "exact.db")),
        schema=universal_schema,
    )
    auto_loader = AutoLoader(schema=universal_schema)

    corpus_paths = [
        "examples/test-corpus/text/standard.txt",
        "examples/test-corpus/structured/standard.jsonl",
        "examples/test-corpus/code/standard.py",
    ]
    total_ingested = 0
    for path in corpus_paths:
        if os.path.exists(path):
            chunks = auto_loader.load(path)
            for c in chunks:
                dummy_resp = {"content": c.text[:200], "source": c.source_file}
                engine.set_l1(c.text[:100], dummy_resp, meta=c.metadata, tenant_id=tenant_id)
                asyncio.run(engine.async_write_l2(c.text[:100], dummy_resp, meta=c.metadata, tenant_id=tenant_id))
                total_ingested += 1
    return total_ingested


def eval_harness(loader_type: str = "text"):
    print(f"Loading datasets for loader-type: {loader_type}...")

    # Determine query directory
    corpus_query_dir = os.path.join("examples/test-corpus/queries", loader_type)
    if not os.path.exists(corpus_query_dir) or not os.listdir(corpus_query_dir):
        base_dir = "examples/sec-filings-corpus/datasets/queries"
    else:
        base_dir = corpus_query_dir

    if loader_type in ["structured", "code", "mixed"]:
        extract_fn = universal_extract_fields
        filter_keys = universal_schema.filter_keys
    else:
        extract_fn = financial_extract_fields
        filter_keys = ["entity", "quarter", "topic"]

    paraphrases = load_jsonl(os.path.join(base_dir, "paraphrases.jsonl"))
    near_miss = load_jsonl(os.path.join(base_dir, "near_miss_negatives.jsonl"))
    context_dep = load_jsonl(os.path.join(base_dir, "context_dependent.jsonl"))

    print(f"Loaded {len(paraphrases)} paraphrases, {len(near_miss)} near_miss, {len(context_dep)} context_dep queries.")

    print(f"Evaluating L2 Semantic [{loader_type}]...")
    true_l2, false_l2 = [], []
    failed_l2_pairs = []

    for item in paraphrases:
        meta1 = extract_fn(item["query_1"])
        meta2 = extract_fn(item["query_2"])
        if not hard_gate(meta1, meta2, filter_keys):
            true_l2.append(0.0)  # blocked by gate
            continue

        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        sim = float(np.dot(q1_emb, q2_emb))
        true_l2.append(sim)

    for item in near_miss:
        meta1 = extract_fn(item["query_1"])
        meta2 = extract_fn(item["query_2"])
        if not hard_gate(meta1, meta2, filter_keys):
            false_l2.append(0.0)  # blocked by gate -> successfully handled near miss!
            continue

        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        sim = float(np.dot(q1_emb, q2_emb))
        false_l2.append(sim)
        if sim >= 0.85:
            failed_l2_pairs.append((item["query_1"], item["query_2"], sim, meta1, meta2))

    print(f"Evaluating L3 Context [{loader_type}]...")
    true_l3, false_l3 = [], []
    failed_l3_pairs = []

    for item in paraphrases:
        meta1 = extract_fn(item["query_1"])
        meta2 = extract_fn(item["query_2"])
        ctx_text = "Context is AAPL" if loader_type == "text" else "Context is standard record"
        meta_c1 = extract_fn(ctx_text)
        meta_c2 = extract_fn(ctx_text)

        meta_in = {**meta2, **meta_c2}
        meta_cache = {**meta1, **meta_c1}

        if not hard_gate(meta_in, meta_cache, filter_keys):
            true_l3.append(0.0)
            continue

        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        c_emb = np.array(get_embedding(ctx_text))

        q_score = float(np.dot(q1_emb, q2_emb))
        c_score = float(np.dot(c_emb, c_emb))
        true_l3.append(min(q_score, c_score))

    for item in context_dep:
        if item.get("label", False) is True:
            continue
        meta1 = extract_fn(item["query"])
        meta2 = extract_fn(item["query"])
        meta_c1 = extract_fn(item["context_1"])
        meta_c2 = extract_fn(item["context_2"])

        meta_in = {**meta2, **meta_c2}
        meta_cache = {**meta1, **meta_c1}

        if not hard_gate(meta_in, meta_cache, filter_keys):
            false_l3.append(0.0)
            continue

        q_emb = np.array(get_embedding(item["query"]))
        c1_emb = np.array(get_embedding(item["context_1"]))
        c2_emb = np.array(get_embedding(item["context_2"]))

        q_score = float(np.dot(q_emb, q_emb))
        c_score = float(np.dot(c1_emb, c2_emb))
        sim = min(q_score, c_score)
        false_l3.append(sim)
        if sim >= 0.85:
            failed_l3_pairs.append((item["query"], item["context_1"], item["context_2"], sim, meta_in, meta_cache))

    print("\n--- RESULTS ---")

    l2_thresh = max(false_l2) + 0.01 if false_l2 and max(false_l2) > 0.85 else 0.85
    print(f"L2 Recommended Threshold (max negative + margin): {l2_thresh:.3f}")
    print(f"L2 True Matches > Thresh: {sum(1 for x in true_l2 if x >= l2_thresh)}/{len(true_l2)}")
    l2_false_hits = sum(1 for x in false_l2 if x >= l2_thresh)
    print(f"L2 False Hits > Thresh: {l2_false_hits}/{len(false_l2)}")

    l3_thresh = max(false_l3) + 0.01 if false_l3 and max(false_l3) > 0.85 else 0.85
    print(f"L3 Recommended Threshold (max negative + margin): {l3_thresh:.3f}")
    print(f"L3 True Matches > Thresh: {sum(1 for x in true_l3 if x >= l3_thresh)}/{len(true_l3)}")
    l3_false_hits = sum(1 for x in false_l3 if x >= l3_thresh)
    print(f"L3 False Hits > Thresh: {l3_false_hits}/{len(false_l3)}")

    print("\nSample False Hit Scores (L2 negatives):", sorted(false_l2, reverse=True)[:5])
    print("Sample True Match Scores (L2 positives):", sorted(true_l2)[:5])

    if l2_false_hits > 0 or l3_false_hits > 0:
        if failed_l2_pairs:
            print("\n[FAILED L2 QUERY PAIRS]")
            for p1, p2, sim, m1, m2 in failed_l2_pairs[:5]:
                print(f"  Q1: {p1}\n  Q2: {p2}\n  Sim: {sim:.4f}\n  M1: {m1}, M2: {m2}\n")
        if failed_l3_pairs:
            print("\n[FAILED L3 QUERY PAIRS]")
            for q, c1, c2, sim, m1, m2 in failed_l3_pairs[:5]:
                print(f"  Q: {q}\n  C1: {c1}\n  C2: {c2}\n  Sim: {sim:.4f}\n  M1: {m1}, M2: {m2}\n")
        raise AssertionError(
            f"False-hit regression detected for loader-type '{loader_type}'! "
            f"L2={l2_false_hits}/{len(false_l2)}, L3={l3_false_hits}/{len(false_l3)}. Baseline is 0%."
        )

    return {
        "loader_type": loader_type,
        "l2_false_hits": l2_false_hits,
        "l2_total": len(false_l2),
        "l3_false_hits": l3_false_hits,
        "l3_total": len(false_l3),
        "l2_true_matches": sum(1 for x in true_l2 if x >= l2_thresh),
        "l2_true_total": len(true_l2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ICO-Cache Evaluation Harness")
    parser.add_argument(
        "--loader-type",
        choices=["text", "structured", "code", "mixed"],
        default="text",
        help="Corpus loader type to evaluate (text, structured, code, mixed)",
    )
    parser.add_argument(
        "--ingest-tenant",
        action="store_true",
        help="Ingest all three corpus types into one tenant before evaluation",
    )
    args = parser.parse_args()

    if args.ingest_tenant:
        print("Ingesting all three corpus types into tenant 'eval_unified_tenant'...")
        n = ingest_corpus_into_tenant("eval_unified_tenant")
        print(f"Ingested {n} chunks into 'eval_unified_tenant'.")

    eval_harness(loader_type=args.loader_type)
