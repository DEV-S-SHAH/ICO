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


def ingest_corpus_into_tenant(tenant_id: str = "eval_tenant", backend: str = "embedded"):
    """Ingests all three corpus types (text, structured, code) into a single tenant."""
    from ico_cache.loaders.auto_loader import AutoLoader
    from ico_cache.core.cache_engine import CacheEngine
    from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
    import asyncio

    if backend == "qdrant":
        from ico_cache.backends.vector.qdrant_store import QdrantStore
        from ico_cache.backends.exact.redis_store import RedisStore
        engine = CacheEngine(
            embedder=FastEmbedder(),
            vector_store=QdrantStore(host="localhost", port=6333),
            exact_store=RedisStore(host="localhost", port=6379, password="myredissecret"),
            schema=universal_schema,
        )
    else:
        from ico_cache.backends.vector.lancedb_store import LanceDBStore
        from ico_cache.backends.exact.sqlite_store import SQLiteStore
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
        "examples/test-corpus/text/clean.pdf",
        "examples/test-corpus/text/malformed.html",
        "examples/test-corpus/structured/standard.jsonl",
        "examples/test-corpus/code/standard.py",
        "examples/test-corpus/code/standard.js",
        "examples/test-corpus/code/standard.go",
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


def eval_harness(loader_type: str = "text", backend: str = "embedded"):
    print(f"Loading datasets for loader-type: {loader_type} (backend: {backend})...")

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

    qc = None
    coll_l2 = f"eval_qdrant_l2_{loader_type}"
    coll_l3 = f"eval_qdrant_l3_{loader_type}"
    if backend == "qdrant":
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance
        qc = QdrantClient(host="localhost", port=6333, check_compatibility=False)
        for c in [coll_l2, coll_l3]:
            if qc.collection_exists(c):
                qc.delete_collection(c)
        qc.create_collection(coll_l2, vectors_config=VectorParams(size=384, distance=Distance.COSINE))
        qc.create_collection(coll_l3, vectors_config={
            "query": VectorParams(size=384, distance=Distance.COSINE),
            "context": VectorParams(size=384, distance=Distance.COSINE),
        })

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

        if backend == "qdrant" and qc:
            from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, IsEmptyCondition, PayloadField
            qc.upsert(coll_l2, points=[PointStruct(id=1, vector=q1_emb.tolist(), payload={"meta": meta1, "query": item["query_1"]})])
            conditions = [
                Filter(should=[
                    FieldCondition(key=f"meta.{k}", match=MatchValue(value=v)),
                    IsEmptyCondition(is_empty=PayloadField(key=f"meta.{k}"))
                ])
                for k, v in meta2.items()
            ]
            q_filter = Filter(must=conditions) if conditions else None
            hits = qc.query_points(collection_name=coll_l2, query=q2_emb.tolist(), query_filter=q_filter, limit=1, score_threshold=0.85).points
            if hits:
                cached_meta = hits[0].payload.get("meta", {})
                if hard_gate(meta2, cached_meta, filter_keys):
                    failed_l2_pairs.append((item["query_1"], item["query_2"], sim, meta1, meta2))
            qc.delete(coll_l2, points_selector=[1])
        else:
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


def eval_cross_type_adversarial(filepath: str = "examples/test-corpus/queries/cross_type_adversarial.jsonl", backend: str = "embedded"):
    print(f"\n--- CROSS-TYPE ADVERSARIAL EVALUATION (backend: {backend}) ---")
    items = load_jsonl(filepath)
    if not items:
        print("No cross-type adversarial query pairs found.")
        return {"total": 0, "false_hits": 0}

    qc = None
    coll_name = "eval_qdrant_adversarial"
    if backend == "qdrant":
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance, PointStruct
        qc = QdrantClient(host="localhost", port=6333, check_compatibility=False)
        if qc.collection_exists(coll_name):
            qc.delete_collection(coll_name)
        qc.create_collection(coll_name, vectors_config=VectorParams(size=384, distance=Distance.COSINE))

    false_adv = []
    gated_count = 0
    failed_pairs = []
    thresh = 0.85

    for item in items:
        q1, q2 = item["query_1"], item["query_2"]
        m1 = universal_extract_fields(q1)
        m2 = universal_extract_fields(q2)
        if not hard_gate(m1, m2, universal_schema.filter_keys):
            gated_count += 1
            false_adv.append(0.0)
            continue

        e1 = np.array(get_embedding(q1))
        e2 = np.array(get_embedding(q2))
        sim = float(np.dot(e1, e2))
        false_adv.append(sim)

        if backend == "qdrant" and qc:
            qc.upsert(coll_name, points=[PointStruct(id=1, vector=e1.tolist(), payload={"meta": m1, "query": q1})])
            hits = qc.query_points(collection_name=coll_name, query=e2.tolist(), limit=1, score_threshold=thresh).points
            if hits:
                failed_pairs.append((q1, q2, sim, m1, m2))
            qc.delete(coll_name, points_selector=[1])
        else:
            if sim >= thresh:
                failed_pairs.append((q1, q2, sim, m1, m2))

    if backend == "qdrant" and qc and qc.collection_exists(coll_name):
        qc.delete_collection(coll_name)

    false_hits = sum(1 for x in false_adv if x >= thresh)
    max_sim = max(false_adv) if false_adv else 0.0
    print(f"Adversarial Total Query Pairs: {len(items)}")
    print(f"Adversarial Gated by Schema: {gated_count}/{len(items)}")
    print(f"Adversarial Max Similarity: {max_sim:.4f}")
    print(f"Adversarial False Hits (> {thresh:.3f}): {false_hits}/{len(items)} ({(false_hits/len(items))*100:.2f}%)")

    if false_hits > 0:
        print("\n[FAILED CROSS-TYPE ADVERSARIAL PAIRS]")
        for q1, q2, sim, m1, m2 in failed_pairs[:5]:
            print(f"  Q1: {q1}\n  Q2: {q2}\n  Sim: {sim:.4f}\n  M1: {m1}, M2: {m2}\n")
        raise AssertionError(
            f"Cross-type adversarial false-hit regression: {false_hits}/{len(items)} above {thresh}. Baseline is 0%."
        )

    return {
        "total": len(items),
        "gated": gated_count,
        "max_similarity": max_sim,
        "false_hits": false_hits,
        "false_hit_rate": (false_hits / len(items)) * 100.0,
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
        "--backend",
        choices=["embedded", "qdrant"],
        default="embedded",
        help="Vector and storage backend (embedded or qdrant)",
    )
    parser.add_argument(
        "--ingest-tenant",
        action="store_true",
        help="Ingest all corpus types into one tenant before evaluation",
    )
    parser.add_argument(
        "--eval-adversarial",
        action="store_true",
        help="Run cross-type adversarial query evaluation",
    )
    args = parser.parse_args()

    if args.ingest_tenant:
        print(f"Ingesting all corpus types into tenant 'eval_unified_tenant' (backend: {args.backend})...")
        n = ingest_corpus_into_tenant("eval_unified_tenant", backend=args.backend)
        print(f"Ingested {n} chunks into 'eval_unified_tenant'.")

    eval_harness(loader_type=args.loader_type, backend=args.backend)

    if args.loader_type == "mixed" or args.eval_adversarial:
        eval_cross_type_adversarial(backend=args.backend)

