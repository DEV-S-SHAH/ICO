import importlib.util
import logging
import os
import sys

from fastapi.testclient import TestClient
from starlette.requests import Request

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
DEMO_DIR = os.path.join(REPO_ROOT, "apps/financial-rag-demo")
for path in (REPO_ROOT, DEMO_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

spec = importlib.util.spec_from_file_location("api_main_observability", os.path.join(DEMO_DIR, "api/main.py"))
api_main = importlib.util.module_from_spec(spec)
sys.modules["api_main_observability"] = api_main
spec.loader.exec_module(api_main)

app = api_main.app
client = TestClient(app)


def test_metrics_endpoint_exposes_prometheus_metrics():
    client.get("/v1/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "ico_cache_requests_total" in response.text
    assert "ico_cache_lookups_total" in response.text


def test_ready_returns_503_when_any_backend_down(monkeypatch):
    monkeypatch.setattr(
        api_main, "_check_backends", lambda: {"redis": "disconnected", "qdrant": "connected"}
    )
    response = client.get("/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "redis" in body["unavailable"]


def test_ready_returns_200_when_all_backends_up(monkeypatch):
    monkeypatch.setattr(
        api_main, "_check_backends", lambda: {"redis": "connected", "qdrant": "connected"}
    )
    response = client.get("/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_health_stays_200_when_degraded(monkeypatch):
    monkeypatch.setattr(
        api_main, "_check_backends", lambda: {"redis": "disconnected", "qdrant": "disconnected"}
    )
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def _request_with_headers(headers):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "client": ("1.2.3.4", 1234),
    }
    return Request(scope)


def test_rate_limit_key_hashes_api_key():
    key = api_main._rate_limit_key(
        _request_with_headers([(b"x-api-key", b"super-secret-key-123")])
    )
    assert key.startswith("key:")
    assert "super-secret-key-123" not in key


def test_rate_limit_key_falls_back_to_client_ip():
    key = api_main._rate_limit_key(_request_with_headers([]))
    assert key == "1.2.3.4"


def test_configured_limiter_uses_redis_in_production():
    from api.config import Settings

    prod = Settings(
        API_KEYS='{"k":"t"}',
        ENVIRONMENT="production",
        REDIS_HOST="redis",
        REDIS_PORT=6379,
        REDIS_AUTH="pw",
    )
    assert prod.resolved_rate_limit_storage_uri == "redis://:pw@redis:6379/0"

    dev = Settings(API_KEYS="", ENVIRONMENT="development")
    assert dev.resolved_rate_limit_storage_uri == "memory://"


def test_record_lookup_increments_counter():
    from ico_cache.telemetry import metrics

    counter = metrics.CACHE_LOOKUPS.labels(layer="TESTLAYER", result="hit")
    before = counter._value.get()
    metrics.record_lookup("TESTLAYER", True, 0.01)
    assert counter._value.get() == before + 1


def test_setup_tracing_noop_without_endpoint():
    from ico_cache.telemetry.tracing import setup_tracing

    assert setup_tracing(otlp_endpoint=None) is None


def test_configure_logging_emits_json(capsys):
    from ico_cache.telemetry.logging import configure_logging

    configure_logging(json_logs=True, level="INFO")
    logging.getLogger("ico_cache.observability_test").info("hello_json_event")
    out = capsys.readouterr().out
    assert "hello_json_event" in out
    assert out.strip().startswith("{")
