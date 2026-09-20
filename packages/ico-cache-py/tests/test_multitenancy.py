import os
import shutil
import pytest
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore

@pytest.fixture
def temp_embedded_engine(tmp_path):
    db_dir = tmp_path / "lancedb_test"
    db_path = str(tmp_path / "cache_test.db")
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        exact_store=SQLiteStore(db_path=db_path),
        tenant_isolation_mode="collection"
    )
    yield engine
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(str(db_dir)):
        shutil.rmtree(str(db_dir), ignore_errors=True)

@pytest.mark.asyncio
async def test_cross_tenant_leakage_l1(temp_embedded_engine):
    engine = temp_embedded_engine
    query = "What is the account balance for customer 101?"
    resp = {"balance": "$50,000"}

    # Write to Tenant A
    engine.set_l1(query, resp, tenant_id="tenant_a")

    # Read as Tenant A -> HIT
    hit_a = await engine.get_l1(query, tenant_id="tenant_a")
    assert hit_a is not None
    assert hit_a["balance"] == "$50,000"

    # Read as Tenant B -> ZERO HIT (must be None)
    hit_b = await engine.get_l1(query, tenant_id="tenant_b")
    assert hit_b is None

@pytest.mark.asyncio
async def test_cross_tenant_leakage_l2_semantic(temp_embedded_engine):
    engine = temp_embedded_engine
    query_stored = "Show me the quarterly revenue report"
    query_incoming = "Give me the quarterly revenue summary"
    resp = {"revenue": "$1.2B"}

    # Write to Tenant A
    await engine.async_write_l2(query_stored, resp, tenant_id="tenant_a")

    # Resolve under Tenant A -> HIT
    res_a = await engine.resolve(query_incoming, tenant_id="tenant_a")
    assert res_a["source"] in ["L1", "L2"]
    assert res_a["response"]["revenue"] == "$1.2B"

    # Resolve under Tenant B -> ZERO HIT (must be MISS)
    res_b = await engine.resolve(query_incoming, tenant_id="tenant_b")
    assert res_b["source"] == "MISS"
    assert res_b["response"] is None

@pytest.mark.asyncio
async def test_cross_tenant_leakage_l3_context(temp_embedded_engine):
    engine = temp_embedded_engine
    query = "What were their risk factors?"
    context = "Confidential acquisition target Acme Corp"
    resp = {"risk": "Regulatory review pending"}

    # Write to Tenant Alpha
    await engine.async_write_l3(query, context, resp, tenant_id="tenant_alpha")

    # Resolve under Tenant Alpha -> HIT
    res_alpha = await engine.resolve(query, context=context, tenant_id="tenant_alpha")
    assert res_alpha["source"] == "L3"

    # Resolve under Tenant Beta -> ZERO HIT (must be MISS)
    res_beta = await engine.resolve(query, context=context, tenant_id="tenant_beta")
    assert res_beta["source"] == "MISS"
    assert res_beta["response"] is None

@pytest.mark.asyncio
async def test_cross_tenant_payload_mode(tmp_path):
    db_dir = tmp_path / "lancedb_payload_test"
    db_path = str(tmp_path / "cache_payload_test.db")
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        exact_store=SQLiteStore(db_path=db_path),
        tenant_isolation_mode="payload"
    )
    query_stored = "Company financial forecast for next fiscal year"
    query_incoming = "Company financial forecast for upcoming fiscal year"
    resp = {"forecast": "+15% YoY growth"}

    # Write to Tenant 1
    await engine.async_write_l2(query_stored, resp, tenant_id="tenant_1")

    # Tenant 1 resolves -> HIT
    res1 = await engine.resolve(query_incoming, tenant_id="tenant_1")
    assert res1["source"] in ["L1", "L2"]
    assert res1["response"]["forecast"] == "+15% YoY growth"

    # Tenant 2 resolves -> MISS
    res2 = await engine.resolve(query_incoming, tenant_id="tenant_2")
    assert res2["source"] == "MISS"
    assert res2["response"] is None

