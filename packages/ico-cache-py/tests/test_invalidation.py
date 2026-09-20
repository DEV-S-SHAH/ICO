import os
import shutil
import pytest
import importlib.util
import sys
from unittest.mock import AsyncMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
DEMO_DIR = os.path.join(REPO_ROOT, "apps/financial-rag-demo")
if DEMO_DIR not in sys.path:
    sys.path.insert(0, DEMO_DIR)

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.invalidation import publish_invalidation, InvalidationWorker
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location("api_main_module_inv", os.path.join(DEMO_DIR, "api/main.py"))
api_main = importlib.util.module_from_spec(spec)
sys.modules["api_main_module_inv"] = api_main
spec.loader.exec_module(api_main)
app = api_main.app


@pytest.fixture
def temp_engine(tmp_path):
    db_dir = tmp_path / "lancedb_inv_test"
    db_path = str(tmp_path / "cache_inv_test.db")
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        exact_store=SQLiteStore(db_path=db_path),
        tenant_isolation_mode="collection",
    )
    yield engine
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(str(db_dir)):
        shutil.rmtree(str(db_dir), ignore_errors=True)


@pytest.mark.asyncio
async def test_end_to_end_invalidation_lifecycle(temp_engine):
    """
    Test: ingest -> query (HIT) -> invalidate -> query (MISS).
    """
    engine = temp_engine
    tenant_target = "tenant_alpha"
    tenant_other = "tenant_beta"

    query = "What is the Q3 operating margin?"
    context = "Q3 Operating Margin rose to 28.5% YoY"
    answer = {"margin": "28.5%"}

    # 1. Ingest into tenant_alpha and tenant_beta
    engine.set_l1(query, answer, tenant_id=tenant_target)
    await engine.async_write_l2(query, answer, tenant_id=tenant_target)
    await engine.async_write_l3(query, context, answer, tenant_id=tenant_target)

    engine.set_l1(query, answer, tenant_id=tenant_other)
    await engine.async_write_l2(query, answer, tenant_id=tenant_other)

    # 2. Query before invalidation -> HIT
    hit_l1 = await engine.get_l1(query, tenant_id=tenant_target)
    assert hit_l1 == answer

    res_l2 = await engine.resolve(query, tenant_id=tenant_target)
    assert res_l2["source"] in ["L1", "L2"]
    assert res_l2["response"] == answer

    res_l3 = await engine.resolve(query, context=context, tenant_id=tenant_target)
    assert res_l3["source"] in ["L1", "L2", "L3"]
    assert res_l3["response"] == answer

    # 3. Invalidate tenant_alpha
    inv_res = await engine.invalidate(tenant_id=tenant_target)
    assert inv_res["status"] == "success"
    assert inv_res["tenant_id"] == tenant_target

    # 4. Query after invalidation -> MISS
    hit_l1_after = await engine.get_l1(query, tenant_id=tenant_target)
    assert hit_l1_after is None

    res_after = await engine.resolve(query, tenant_id=tenant_target)
    assert res_after["source"] == "MISS"
    assert res_after["response"] is None

    res_after_l3 = await engine.resolve(query, context=context, tenant_id=tenant_target)
    assert res_after_l3["source"] == "MISS"
    assert res_after_l3["response"] is None

    # 5. Confirm tenant_beta remains intact (HIT)
    res_other = await engine.resolve(query, tenant_id=tenant_other)
    assert res_other["source"] in ["L1", "L2"]
    assert res_other["response"] == answer


def test_api_invalidate_endpoint():
    """Test POST /v1/invalidate endpoint via FastAPI TestClient."""
    client = TestClient(app)
    headers = {"X-API-Key": "key-tenant-a"}

    # Mismatch rejection: key-tenant-a trying to invalidate tenant_b -> 403
    mismatch_resp = client.post(
        "/v1/invalidate",
        headers=headers,
        json={"tenant_id": "tenant_b"},
    )
    assert mismatch_resp.status_code == 403

    # Authorized invalidation -> 200
    with patch("api_main_module_inv.engine.invalidate", new_callable=AsyncMock) as mock_inv:
        mock_inv.return_value = {
            "status": "success",
            "tenant_id": "tenant_a",
            "l1_purged": 5,
            "l2_purged": 2,
            "l3_purged": 1,
        }
        resp = client.post(
            "/v1/invalidate",
            headers=headers,
            json={"tenant_id": "tenant_a", "filter": {"doc_id": "10-K-2024"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["tenant_id"] == "tenant_a"
        mock_inv.assert_awaited_once_with(tenant_id="tenant_a", filter_dict={"doc_id": "10-K-2024"})


@pytest.mark.asyncio
async def test_invalidation_worker_processing(temp_engine):
    """Test InvalidationWorker event processing."""
    engine = temp_engine
    worker = InvalidationWorker(engine=engine)

    query = "Capital expenditure guidance"
    ans = {"capex": "$15B"}
    engine.set_l1(query, ans, tenant_id="tenant_worker_test")

    # Verify present
    assert await engine.get_l1(query, tenant_id="tenant_worker_test") == ans

    # Process invalidation via worker
    await worker.process_event(tenant_id="tenant_worker_test")

    # Verify purged
    assert await engine.get_l1(query, tenant_id="tenant_worker_test") is None


def is_distributed_available() -> bool:
    try:
        from qdrant_client import QdrantClient
        import redis
        qc = QdrantClient("localhost", port=6333, timeout=1, check_compatibility=False)
        qc.get_collections()
        r = redis.Redis(host="localhost", port=6379, password="myredissecret", socket_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["embedded", "distributed"])
async def test_payload_mode_invalidation_isolation(backend, tmp_path):
    """
    Test: In payload-filter mode (shared collections), invalidating tenant_a
    must execute a FILTERED point delete, leaving tenant_b's cached entries intact.
    """
    if backend == "embedded":
        db_dir = tmp_path / "lancedb_payload_inv"
        db_path = str(tmp_path / "cache_payload_inv.db")
        vector_store = LanceDBStore(uri=str(db_dir))
        exact_store = SQLiteStore(db_path=db_path)
    else:
        if not is_distributed_available():
            pytest.skip("Distributed stack (Qdrant + Redis) is not available")
        from ico_cache.backends.vector.qdrant_store import QdrantStore
        from ico_cache.backends.exact.redis_store import RedisStore
        vector_store = QdrantStore(host="localhost", port=6333)
        exact_store = RedisStore(host="localhost", port=6379, password="myredissecret")

    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=vector_store,
        exact_store=exact_store,
        tenant_isolation_mode="payload",
    )

    q_a = "What is the Q3 revenue for Tenant A?"
    resp_a = {"revenue": "$100M", "tenant": "A"}
    q_b = "What is the Q3 revenue for Tenant B?"
    resp_b = {"revenue": "$200M", "tenant": "B"}

    # Seed both tenants into shared payload-isolated collection
    engine.set_l1(q_a, resp_a, tenant_id="tenant_a")
    await engine.async_write_l2(q_a, resp_a, tenant_id="tenant_a")

    engine.set_l1(q_b, resp_b, tenant_id="tenant_b")
    await engine.async_write_l2(q_b, resp_b, tenant_id="tenant_b")

    # Confirm both hit initially
    hit_a = await engine.resolve(q_a, tenant_id="tenant_a")
    hit_b = await engine.resolve(q_b, tenant_id="tenant_b")
    assert hit_a["source"] in ["L1", "L2"]
    assert hit_b["source"] in ["L1", "L2"]

    # Invalidate tenant_a ONLY
    inv_res = await engine.invalidate(tenant_id="tenant_a")
    assert inv_res["status"] == "success"
    assert inv_res["tenant_id"] == "tenant_a"

    # Confirm tenant_a is cold MISS
    res_a_after = await engine.resolve(q_a, tenant_id="tenant_a")
    assert res_a_after["source"] == "MISS"
    assert res_a_after["response"] is None

    # CRITICAL: Confirm tenant_b is STILL A HIT (shared collection NOT dropped)
    res_b_after = await engine.resolve(q_b, tenant_id="tenant_b")
    assert res_b_after["source"] in ["L1", "L2"]
    assert res_b_after["response"]["revenue"] == "$200M"

    # Cleanup
    if backend == "distributed":
        exact_store.delete_prefix("tenant_a:")
        exact_store.delete_prefix("tenant_b:")
        for coll in ["l2_cache", "l3_cache"]:
            if vector_store.collection_exists(coll):
                vector_store.delete_collection(coll)
