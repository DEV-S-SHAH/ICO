import importlib.util
import os
import sys
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
DEMO_DIR = os.path.join(REPO_ROOT, "apps/financial-rag-demo")
if DEMO_DIR not in sys.path:
    sys.path.insert(0, DEMO_DIR)

spec = importlib.util.spec_from_file_location("api_main_module", os.path.join(DEMO_DIR, "api/main.py"))
api_main = importlib.util.module_from_spec(spec)
sys.modules["api_main_module"] = api_main
spec.loader.exec_module(api_main)
app = api_main.app

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore


@pytest.fixture
def client():
    return TestClient(app)


def test_auth_missing_api_key(client):
    """Calling protected endpoint without X-API-Key returns 401."""
    response = client.post("/v1/query", json={"query": "test query"})
    assert response.status_code == 401
    assert "Missing API key" in response.json().get("detail", "")


def test_auth_invalid_api_key(client):
    """Calling protected endpoint with invalid X-API-Key returns 401."""
    response = client.post(
        "/v1/query",
        headers={"X-API-Key": "completely-invalid-key-999"},
        json={"query": "test query"},
    )
    assert response.status_code == 401
    assert "Invalid API key" in response.json().get("detail", "")


def test_auth_valid_key_matching_tenant(client):
    """Calling with valid key matching payload tenant returns 200."""
    with patch("api_main_module.engine.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {
            "source": "L2",
            "response": {"answer": "Mocked tenant_a answer", "citations": []},
            "score": 0.95,
        }
        response = client.post(
            "/v1/query",
            headers={"X-API-Key": "key-tenant-a"},
            json={"query": "What is tenant A revenue?", "tenant_id": "tenant_a"},
        )
        assert response.status_code == 200
        assert response.json()["source"] == "L2"
        mock_resolve.assert_awaited_once()
        call = mock_resolve.await_args
        assert call.args[0] == "What is tenant A revenue?"
        assert call.kwargs.get("tenant_id") == "tenant_a"


def test_auth_valid_key_default_tenant(client):
    """Calling with valid key without specifying tenant_id infers key's tenant and returns 200."""
    with patch("api_main_module.engine.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {
            "source": "L1",
            "response": {"answer": "Mocked default answer", "citations": []},
            "score": 1.0,
        }
        response = client.post(
            "/v1/query",
            headers={"X-API-Key": "key-tenant-a"},
            json={"query": "What is revenue?"},
        )
        assert response.status_code == 200
        assert response.json()["source"] == "L1"
        mock_resolve.assert_awaited_once()
        call = mock_resolve.await_args
        assert call.args[0] == "What is revenue?"
        assert call.kwargs.get("tenant_id") == "tenant_a"


def test_auth_key_tenant_mismatch(client):
    """Calling with valid key for tenant_a but targeting tenant_b returns 403 Forbidden."""
    response = client.post(
        "/v1/query",
        headers={"X-API-Key": "key-tenant-a"},
        json={"query": "Give me tenant B secret files", "tenant_id": "tenant_b"},
    )
    assert response.status_code == 403
    assert "Forbidden" in response.json().get("detail", "")
    assert "cannot access tenant 'tenant_b'" in response.json().get("detail", "")


def test_embedded_mode_requires_no_auth(tmp_path):
    """Embedded mode (direct CacheEngine usage) functions without any API keys."""
    db_dir = tmp_path / "lancedb_embedded"
    db_path = str(tmp_path / "sqlite_embedded.db")
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        exact_store=SQLiteStore(db_path=db_path),
    )
    # Direct operations succeed without any auth headers/tokens
    engine.set_l1("direct query", {"data": 123}, tenant_id="my_embedded_tenant")
    import asyncio
    hit = asyncio.run(engine.get_l1("direct query", tenant_id="my_embedded_tenant"))
    assert hit == {"data": 123}
