"""Prometheus metrics for ICO-Cache.

All metrics live on the default registry so a single ``/metrics`` scrape exposes
them. Helpers are intentionally cheap and never raise, so instrumentation cannot
break a request path.
"""
import logging
from typing import Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)

logger = logging.getLogger("ico_cache.telemetry.metrics")

_LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

CACHE_LOOKUPS = Counter(
    "ico_cache_lookups_total",
    "Cache layer lookups by layer and result (hit/miss).",
    ["layer", "result"],
)
LOOKUP_SECONDS = Histogram(
    "ico_cache_lookup_seconds",
    "Cache layer lookup latency in seconds.",
    ["layer"],
    buckets=_LATENCY_BUCKETS,
)
GENERATION_SECONDS = Histogram(
    "ico_cache_generation_seconds",
    "LLM generation latency on cache miss in seconds.",
    buckets=_LATENCY_BUCKETS,
)
INFLIGHT_GENERATIONS = Gauge(
    "ico_cache_inflight_generations",
    "Number of single-flight generations currently in progress.",
)
REQUESTS_TOTAL = Counter(
    "ico_cache_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "endpoint", "status"],
)
BACKEND_UP = Gauge(
    "ico_cache_backend_up",
    "Backend reachability (1=up, 0=down or degraded).",
    ["backend"],
)


def record_lookup(layer: str, hit: bool, seconds: Optional[float] = None) -> None:
    try:
        CACHE_LOOKUPS.labels(layer=layer, result="hit" if hit else "miss").inc()
        if seconds is not None:
            LOOKUP_SECONDS.labels(layer=layer).observe(max(seconds, 0.0))
    except Exception:  # pragma: no cover - metrics must never break requests
        logger.debug("metrics.record_lookup failed", exc_info=True)


def record_generation(seconds: float) -> None:
    try:
        GENERATION_SECONDS.observe(max(seconds, 0.0))
    except Exception:  # pragma: no cover
        logger.debug("metrics.record_generation failed", exc_info=True)


def record_request(method: str, endpoint: str, status: Optional[int]) -> None:
    try:
        REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=str(status or 0)).inc()
    except Exception:  # pragma: no cover
        logger.debug("metrics.record_request failed", exc_info=True)


def set_backend_up(backend: str, up: bool) -> None:
    try:
        BACKEND_UP.labels(backend=backend).set(1 if up else 0)
    except Exception:  # pragma: no cover
        logger.debug("metrics.set_backend_up failed", exc_info=True)


def inflight_inc() -> None:
    try:
        INFLIGHT_GENERATIONS.inc()
    except Exception:  # pragma: no cover
        pass


def inflight_dec() -> None:
    try:
        INFLIGHT_GENERATIONS.dec()
    except Exception:  # pragma: no cover
        pass


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


__all__ = [
    "CONTENT_TYPE_LATEST",
    "render_metrics",
    "record_lookup",
    "record_generation",
    "record_request",
    "set_backend_up",
    "inflight_inc",
    "inflight_dec",
]
