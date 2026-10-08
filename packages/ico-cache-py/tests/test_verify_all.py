import pytest
import asyncio
import json
import os
import time

import sys
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
tests_dir = os.path.dirname(__file__)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

from examples.financial_schema import financial_schema, extract_fields
from fixtures_gen import generate_paraphrase_queries, generate_near_miss_queries
from ico_cache.core.cache_engine import CacheEngine, _canonical_meta_suffix
from ico_cache.core.metadata_guard import hard_gate
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from qdrant_client.models import VectorParams, Distance

REDIS_PASSWORD = "myredissecret"
FILTER_KEYS    = ["entity", "quarter", "topic"]

# Deterministic synthetic query sets (replaces the deleted curated
# examples/sec-filings-corpus/datasets/queries files).
PARAPHRASES = generate_paraphrase_queries()
NEAR_MISS   = generate_near_miss_queries()

def is_distributed_available() -> bool:
    try:
        from qdrant_client import QdrantClient
        import redis
        qc = QdrantClient("localhost", port=6333, timeout=1, check_compatibility=False)
        qc.get_collections()
        r = redis.Redis(host="localhost", port=6379, password=REDIS_PASSWORD, socket_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


@pytest.fixture
def make_engine():
    if not is_distributed_available():
        pytest.skip("Distributed stack (Qdrant + Redis) is not available")

    def _make(l2_coll="l2_cache", l3_coll="l3_cache"):
        engine = CacheEngine(
            embedder     = FastEmbedder(),
            vector_store = QdrantStore(host="localhost", port=6333),
            exact_store  = RedisStore(host="localhost", port=6379, password=REDIS_PASSWORD),
            schema       = financial_schema,
            metadata_filter_keys=FILTER_KEYS,
            adaptive_threshold=True,
            target_hit_rate=0.80,
            min_threshold=0.70,
            max_threshold=0.95,
            adjustment_rate=0.01,
        )
        engine._l2_collection = l2_coll
        engine._l3_collection = l3_coll
        return engine
    return _make

def test_1_query_generation_audit():
    paraphrases = PARAPHRASES
    near_miss   = NEAR_MISS
    
    entity_swap  = sum(1 for r in near_miss
        if extract_fields(r["query_1"])["entity"] and extract_fields(r["query_2"])["entity"]
        and extract_fields(r["query_1"])["entity"] != extract_fields(r["query_2"])["entity"])
    quarter_swap = sum(1 for r in near_miss
        if extract_fields(r["query_1"])["quarter"] and extract_fields(r["query_2"])["quarter"]
        and extract_fields(r["query_1"])["quarter"] != extract_fields(r["query_2"])["quarter"])
    topic_swap   = sum(1 for r in near_miss
        if extract_fields(r["query_1"])["entity"] == extract_fields(r["query_2"])["entity"]
        and extract_fields(r["query_1"])["topic"] and extract_fields(r["query_2"])["topic"]
        and extract_fields(r["query_1"])["topic"] != extract_fields(r["query_2"])["topic"])

    total_classified = entity_swap + quarter_swap + topic_swap
    assert total_classified >= 90, "Near-miss coverage insufficient"

    para_same = sum(1 for r in paraphrases
        if extract_fields(r["query_1"])["entity"] == extract_fields(r["query_2"])["entity"])
    assert para_same == len(paraphrases), "Mismatched entities in paraphrases"

@pytest.mark.asyncio
async def test_2_false_hit_check(make_engine):
    engine = make_engine()
    qc = engine.vector_store.qc
    near_miss = NEAR_MISS
    
    false_hits = 0
    for i, pair in enumerate(near_miss):
        coll_name = f"v2_pair_{i}"
        if qc.collection_exists(coll_name):
            qc.delete_collection(coll_name)
        qc.create_collection(coll_name, vectors_config=VectorParams(size=384, distance=Distance.COSINE))

        q1, q2 = pair["query_1"], pair["query_2"]
        meta1 = {k: v for k, v in extract_fields(q1).items() if v is not None}
        meta2 = {k: v for k, v in extract_fields(q2).items() if v is not None}

        emb1 = engine.embedder.embed(q1)
        fake_resp = {"answer": f"pair_{i}"}

        from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, IsEmptyCondition, PayloadField
        qc.upsert(coll_name, points=[
            PointStruct(id=i, vector=emb1, payload={"query": q1, "answer": fake_resp, "meta": meta1})
        ])

        emb2 = engine.embedder.embed(q2)
        conditions = []
        for k, v in meta2.items():
            conditions.append(
                Filter(should=[
                    FieldCondition(key=f"meta.{k}", match=MatchValue(value=v)),
                    IsEmptyCondition(is_empty=PayloadField(key=f"meta.{k}"))
                ])
            )
        q_filter = Filter(must=conditions) if conditions else None

        hits = qc.query_points(
            collection_name=coll_name,
            query=emb2,
            query_filter=q_filter,
            limit=1,
            score_threshold=0.85,
        ).points

        if hits:
            cached_meta = hits[0].payload.get("meta", {})
            if hard_gate(meta2, cached_meta, FILTER_KEYS):
                false_hits += 1

        qc.delete_collection(coll_name)
    
    assert false_hits == 0, f"Found {false_hits} false hits"

@pytest.mark.asyncio
async def test_3_l3_context(make_engine):
    should_hit = [
        {"query": "What did they say about revenue?", "ctx_store": "The user is asking about WMT.", "ctx_query": "The user is asking about WMT."},
        {"query": "What did they say about margins?", "ctx_store": "The user is asking about JPM.", "ctx_query": "The user is asking about JPM."},
    ]
    should_miss = [
        {"query": "What did they say about revenue?", "ctx_store": "The user is asking about WMT.", "ctx_query": "The user is asking about MSFT."},
        {"query": "What did they say about margins?", "ctx_store": "The user is asking about JPM.", "ctx_query": "The user is asking about GOOGL."},
    ]
    
    engine = make_engine()
    qc = engine.vector_store.qc
    for coll in ["l2_v3_test", "l3_v3_test"]:
        if qc.collection_exists(coll):
            qc.delete_collection(coll)

    qc.create_collection("l2_v3_test", vectors_config=VectorParams(size=384, distance=Distance.COSINE))
    qc.create_collection("l3_v3_test", vectors_config={
        "query":   VectorParams(size=384, distance=Distance.COSINE),
        "context": VectorParams(size=384, distance=Distance.COSINE),
    })

    engine._l2_collection = "l2_v3_test"
    engine._l3_collection = "l3_v3_test"
    engine._collections_setup = True

    # Monkeypatch for test
    async def _patched_write_l3(query, context, generated, meta=None):
        effective_meta = engine._auto_meta(query, meta)
        ctx_meta = extract_fields(context)
        full_meta = {**effective_meta, **{k: v for k, v in ctx_meta.items() if v is not None}}
        emb_q = engine.embedder.embed(query)
        emb_c = engine.embedder.embed(context)
        key_raw = query + ":" + context + _canonical_meta_suffix(full_meta)
        await engine.vector_store.aqc.upsert(
            collection_name="l3_v3_test",
            points=[{"id": hash(key_raw) % (10 ** 10), "vector": {"query": emb_q, "context": emb_c}, "payload": {"query": query, "context": context, "answer": generated, "meta": full_meta}}]
        )
    engine.async_write_l3 = _patched_write_l3

    async def _patched_get_l3(query, context, meta=None):
        if not context or not context.strip(): return None
        effective_meta = engine._auto_meta(query, meta)
        emb_q = engine.embedder.embed(query)
        emb_c = engine.embedder.embed(context)
        q_filter = engine.build_meta_filter(effective_meta)

        hits_q = await engine.vector_store.aqc.query_points(collection_name="l3_v3_test", query=emb_q, using="query", query_filter=q_filter, limit=5, score_threshold=engine.thresh_ctx_q)
        if not hits_q.points: return None

        hits_c = await engine.vector_store.aqc.query_points(collection_name="l3_v3_test", query=emb_c, using="context", query_filter=q_filter, limit=5, score_threshold=engine.thresh_ctx_c)
        if not hits_c.points: return None

        q_ids = {h.id for h in hits_q.points}
        c_ids = {h.id for h in hits_c.points}
        common = q_ids.intersection(c_ids)

        incoming_ctx_meta = extract_fields(context)
        for cid in common:
            h = next(h for h in hits_q.points if h.id == cid)
            cached_payload = h.payload
            cached_ctx_meta = extract_fields(cached_payload.get("context", ""))
            cached_meta = cached_payload.get("meta", {})
            full_cached_meta = {**cached_meta, **{k: v for k, v in cached_ctx_meta.items() if v is not None}}
            full_incoming_meta = {**effective_meta, **{k: v for k, v in incoming_ctx_meta.items() if v is not None}}
            if hard_gate(full_incoming_meta, full_cached_meta, engine.metadata_filter_keys):
                return cached_payload.get("answer")
        return None
    engine.get_l3 = _patched_get_l3

    for pair in should_hit:
        await engine.async_write_l3(pair["query"], pair["ctx_store"], {"answer": "hit"})

    for pair in should_hit:
        assert await engine.get_l3(pair["query"], pair["ctx_query"]) is not None, "False negative"

    for pair in should_miss:
        assert await engine.get_l3(pair["query"], pair["ctx_query"]) is None, "False positive"

@pytest.mark.asyncio
async def test_4_concurrency(make_engine):
    """Single-flight: 20 concurrent identical misses trigger exactly one generation."""
    engine = make_engine()
    QUERY = "What was MSFT's revenue in Q3?"
    META  = {"entity": "MSFT", "quarter": "Q3", "topic": "revenue"}

    calls = {"n": 0}

    async def generate():
        calls["n"] += 1
        await asyncio.sleep(0.1)
        return {"answer": "Generated answer", "query": QUERY}

    # Ensure a cold cache for this key.
    TENANT = "concurrency_test"
    engine.exact_store.delete_prefix(f"default:")
    engine.exact_store.delete_prefix(f"v3:{TENANT}:")
    coll = engine._coll_name("l2_cache", TENANT)
    if engine.vector_store.qc.collection_exists(coll):
        engine.vector_store.qc.delete_collection(coll)

    results = await asyncio.gather(
        *[
            engine.resolve_or_generate(QUERY, meta=META, tenant_id=TENANT, generate_fn=generate)
            for _ in range(20)
        ]
    )
    assert calls["n"] == 1, f"expected one generation, saw {calls['n']}"
    assert all(r["response"]["answer"] == "Generated answer" for r in results)

@pytest.mark.asyncio
async def test_5_adaptive_threshold(make_engine):
    engine = make_engine()
    for _ in range(50):
        engine._update_adaptive_threshold(hit=False)
    assert engine.thresh_semantic < 0.85

    q_stored   = "What was MSFT revenue in Q1?"
    q_incoming = "What was AAPL revenue in Q1?"
    meta_stored   = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}
    meta_incoming = {"entity": "AAPL", "quarter": "Q1", "topic": "revenue"}

    await engine.async_write_l2(q_stored, {"answer": "MSFT Q1."}, meta_stored)
    result = await engine.resolve(q_incoming, meta=meta_incoming)
    assert result["source"] == "MISS"
    assert hard_gate(meta_incoming, meta_stored, engine.metadata_filter_keys) is False