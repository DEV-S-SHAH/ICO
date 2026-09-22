import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
DEMO_DIR = os.path.join(REPO_ROOT, "apps/financial-rag-demo")
if DEMO_DIR not in sys.path:
    sys.path.insert(0, DEMO_DIR)

spec = importlib.util.spec_from_file_location("api_main_security", os.path.join(DEMO_DIR, "api/main.py"))
api_main = importlib.util.module_from_spec(spec)
sys.modules["api_main_security"] = api_main
spec.loader.exec_module(api_main)
app = api_main.app

HEADERS = {"X-API-Key": "key-tenant-a"}


@pytest.fixture
def client():
    return TestClient(app)


class _FakeJob:
    def dict(self):
        return {"job_id": "j1", "status": "processing"}


def _patch_job_manager():
    manager = MagicMock()
    manager.submit_ingest.return_value = _FakeJob()
    return patch("ico_cache.async_ingest.job_manager", manager)


def test_auth_is_timing_safe_across_keys(client):
    """A valid key for the second tenant still resolves (compare-all loop)."""
    with patch.object(api_main.engine, "resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = {"source": "L1", "response": {"answer": "x"}}
        resp = client.post(
            "/v1/query",
            headers={"X-API-Key": "key-tenant-b"},
            json={"query": "q"},
        )
    assert resp.status_code == 200
    mock_resolve.assert_awaited_once()
    assert mock_resolve.await_args.kwargs.get("tenant_id") == "tenant_b"


def test_ingest_rejects_path_traversal(client):
    resp = client.post("/v1/ingest", headers=HEADERS, json={"file_path": "../../etc/passwd"})
    assert resp.status_code == 400


def test_ingest_rejects_absolute_path(client):
    resp = client.post("/v1/ingest", headers=HEADERS, json={"file_path": "/etc/passwd"})
    assert resp.status_code == 400


def test_ingest_allows_relative_path_within_root(client):
    rel = "sample_doc.json"
    os.makedirs(api_main.INGEST_ROOT, exist_ok=True)
    abs_path = os.path.join(api_main.INGEST_ROOT, rel)
    with open(abs_path, "w") as f:
        f.write("{}")
    try:
        with _patch_job_manager() as manager:
            resp = client.post("/v1/ingest", headers=HEADERS, json={"file_path": rel})
        assert resp.status_code == 200
        manager.submit_ingest.assert_called_once()
        assert manager.submit_ingest.call_args.kwargs["file_path"] == os.path.realpath(abs_path)
    finally:
        os.remove(abs_path)


def test_upload_sanitizes_traversal_filename(client):
    with _patch_job_manager():
        resp = client.post(
            "/v1/ingest/upload",
            headers=HEADERS,
            files={"file": ("../../evil.txt", b"hello")},
        )
    assert resp.status_code == 200
    written = os.path.join(api_main.UPLOAD_DIR, "evil.txt")
    assert os.path.exists(written)
    os.remove(written)


def test_upload_enforces_size_cap(client):
    original = api_main.settings.max_upload_bytes
    api_main.settings.max_upload_bytes = 10
    try:
        resp = client.post(
            "/v1/ingest/upload",
            headers=HEADERS,
            files={"file": ("big.bin", b"x" * 100)},
        )
        assert resp.status_code == 413
        assert not os.path.exists(os.path.join(api_main.UPLOAD_DIR, "big.bin"))
    finally:
        api_main.settings.max_upload_bytes = original


def test_clear_cache_is_tenant_scoped(client):
    with patch.object(api_main.engine, "invalidate", new_callable=AsyncMock) as mock_inv:
        mock_inv.return_value = {"status": "success", "tenant_id": "tenant_a"}
        resp = client.post("/v1/clear_cache", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "tenant_a"
    mock_inv.assert_awaited_once_with(tenant_id="tenant_a")
