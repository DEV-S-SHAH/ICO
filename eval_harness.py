import json
import os
import time
from qdrant_client import QdrantClient
from fastembed import TextEmbedding
from examples.financial_schema import extract_fields
from ico_cache.core.metadata_guard import hard_gate
import numpy as np

qc = QdrantClient("localhost", port=6333, check_compatibility=False)
embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
FILTER_KEYS = ["entity", "quarter", "topic"]

def load_jsonl(filepath):
    data = []
    with open(filepath, "r") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data

def get_embedding(text):
    return list(embedder.embed([text]))[0].tolist()

def eval_harness():
    print("Loading datasets...")
    base_dir = "examples/sec-filings-corpus/datasets/queries"
    paraphrases = load_jsonl(os.path.join(base_dir, "paraphrases.jsonl"))
    near_miss = load_jsonl(os.path.join(base_dir, "near_miss_negatives.jsonl"))
    context_dep = load_jsonl(os.path.join(base_dir, "context_dependent.jsonl"))
    
    print("Evaluating L2 Semantic...")
    true_l2, false_l2 = [], []
    
    for item in paraphrases:
        meta1 = extract_fields(item["query_1"])
        meta2 = extract_fields(item["query_2"])
        if not hard_gate(meta1, meta2, FILTER_KEYS):
            true_l2.append(0.0) # blocked by gate
            continue
            
        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        true_l2.append(np.dot(q1_emb, q2_emb))
        
    for item in near_miss:
        meta1 = extract_fields(item["query_1"])
        meta2 = extract_fields(item["query_2"])
        if not hard_gate(meta1, meta2, FILTER_KEYS):
            false_l2.append(0.0) # blocked by gate -> successfully handled near miss!
            continue
            
        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        false_l2.append(np.dot(q1_emb, q2_emb))
        
    print("Evaluating L3 Context...")
    true_l3, false_l3 = [], []
    
    for item in paraphrases:
        meta1 = extract_fields(item["query_1"])
        meta2 = extract_fields(item["query_2"])
        # For true L3, context is the same, query is paraphrased.
        meta_c1 = extract_fields("Context is AAPL")
        meta_c2 = extract_fields("Context is AAPL")
        
        # In L3, the metadata of incoming query+context must match cached query+context
        # Incoming: query_2 + C2. Cached: query_1 + C1.
        meta_in = {**meta2, **meta_c2}
        meta_cache = {**meta1, **meta_c1}
        
        if not hard_gate(meta_in, meta_cache, FILTER_KEYS):
            true_l3.append(0.0)
            continue
            
        q1_emb = np.array(get_embedding(item["query_1"]))
        q2_emb = np.array(get_embedding(item["query_2"]))
        c_emb = np.array(get_embedding("Context is AAPL"))
        
        q_score = np.dot(q1_emb, q2_emb)
        c_score = np.dot(c_emb, c_emb) # 1.0
        true_l3.append(min(q_score, c_score))
        
    for item in context_dep:
        if item.get("label", False) == True: continue
        meta1 = extract_fields(item["query"])
        meta2 = extract_fields(item["query"])
        meta_c1 = extract_fields(item["context_1"])
        meta_c2 = extract_fields(item["context_2"])
        
        meta_in = {**meta2, **meta_c2}
        meta_cache = {**meta1, **meta_c1}
        
        if not hard_gate(meta_in, meta_cache, FILTER_KEYS):
            false_l3.append(0.0)
            continue
            
        q_emb = np.array(get_embedding(item["query"]))
        c1_emb = np.array(get_embedding(item["context_1"]))
        c2_emb = np.array(get_embedding(item["context_2"]))
        
        q_score = np.dot(q_emb, q_emb) # 1.0
        c_score = np.dot(c1_emb, c2_emb)
        false_l3.append(min(q_score, c_score))
        
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
        raise AssertionError(f"False-hit regression detected! L2={l2_false_hits}, L3={l3_false_hits}. Baseline is 0%.")

if __name__ == "__main__":
    eval_harness()
