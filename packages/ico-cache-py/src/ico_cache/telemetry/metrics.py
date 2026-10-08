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
from prometheus_client.metrics import MetricWrapperBase

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
    "ico_cache_requests_total",
    "Total requests by decision action, agent type, and tenant.",
    ["decision", "agent_type", "tenant"],
)
BACKEND_UP = Gauge(
    "ico_cache_backend_up",
    "Backend reachability (1=up, 0=down or degraded).",
    ["backend"],
)

# Token + Cost Accounting (Phase 3A.5) - Section 21 metrics
TOKENS_TOTAL = Counter(
    "ico_tokens_total",
    "Total tokens by type and tenant.",
    ["type", "tenant"],
)
# Phase 4: ico_cache_* rollup family. Labelled by ``type`` only — Prometheus sorts
# exposition labels alphabetically, so a ``tenant`` label would render before
# ``type``. Per-tenant attribution lives on TOKENS_TOTAL / COST_USD_TOTAL.
ICO_CACHE_TOKENS_TOTAL = Counter(
    "ico_cache_tokens",
    "Total tokens by type (rollup across tenants).",
    ["type"],
)
LLM_CALLS_TOTAL = Counter(
    "ico_llm_calls_total",
    "Total LLM calls by layer and tenant.",
    ["layer", "tenant"],
)
LLM_CALLS_AVOIDED_TOTAL = Counter(
    "ico_llm_calls_avoided_total",
    "Total LLM calls avoided by cache layer and tenant.",
    ["layer", "tenant"],
)
EMBEDDING_CALLS_TOTAL = Counter(
    "ico_embedding_calls_total",
    "Total embedding calls by layer and tenant.",
    ["layer", "tenant"],
)
EMBEDDING_CALLS_AVOIDED_TOTAL = Counter(
    "ico_embedding_calls_avoided_total",
    "Total embedding calls avoided by cache layer and tenant.",
    ["layer", "tenant"],
)
RETRIEVAL_CALLS_TOTAL = Counter(
    "ico_retrieval_calls_total",
    "Total retrieval calls by layer and tenant.",
    ["layer", "tenant"],
)
RETRIEVAL_CALLS_AVOIDED_TOTAL = Counter(
    "ico_retrieval_calls_avoided_total",
    "Total retrieval calls avoided by cache layer and tenant.",
    ["layer", "tenant"],
)
COST_USD_TOTAL = Counter(
    "ico_cost_usd_total",
    "Total cost in USD by type and tenant.",
    ["type", "tenant"],
)
ICO_CACHE_COST_USD_TOTAL = Counter(
    "ico_cache_cost_usd",
    "Total cost in USD by type (rollup across tenants).",
    ["type"],
)
COST_SAVED_USD_TOTAL = Counter(
    "ico_cost_saved_usd_total",
    "Total cost saved in USD by type and tenant.",
    ["type", "tenant"],
)
LATENCY_SAVED_SECONDS = Histogram(
    "ico_latency_saved_seconds",
    "Latency saved in seconds by layer and tenant.",
    ["layer", "tenant"],
    buckets=_LATENCY_BUCKETS,
)
LATENCY_SECONDS = Histogram(
    "ico_cache_latency_seconds",
    "Latency in seconds by phase and layer.",
    ["phase", "layer"],
    buckets=_LATENCY_BUCKETS,
)
REUSE_CONFIDENCE = Histogram(
    "ico_cache_reuse_confidence",
    "Reuse confidence by action and layer.",
    ["action", "layer"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)
GATE_EVALUATIONS = Counter(
    "ico_cache_gate_evaluations_total",
    "Gate evaluations by gate, result, and layer.",
    ["gate", "result", "layer"],
)
PROJECT_MEMORY_STALENESS = Gauge(
    "ico_cache_project_memory_staleness",
    "Project memory staleness in hours by project.",
    ["project_id", "commit_age_hours"],
)
FALSE_HIT_SUSPECTED = Counter(
    "ico_cache_false_hit_suspected",
    "Suspected false hits by layer and reason.",
    ["layer", "reason"],
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


def record_request(decision: str, agent_type: str, tenant: str) -> None:
    """Record a request with decision, agent type, and tenant.

    Args:
        decision: The decision action (e.g., "CACHE_HIT", "FULL_LLM_CALL", "SEMANTIC_REUSE")
        agent_type: Type of agent (e.g., "chatbot", "coding_agent", "rag")
        tenant: Tenant identifier
    """
    try:
        REQUESTS_TOTAL.labels(decision=decision, agent_type=agent_type, tenant=tenant).inc()
    except Exception:  # pragma: no cover
        logger.debug("metrics.record_request failed", exc_info=True)


def record_http_request(method: str, endpoint: str, status: Optional[int]) -> None:
    """Record an HTTP request (legacy compatibility).

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Request endpoint path
        status: HTTP status code
    """
    try:
        REQUESTS_TOTAL.labels(decision=f"HTTP_{method}", agent_type=endpoint, tenant=str(status or 0)).inc()
    except Exception:  # pragma: no cover
        logger.debug("metrics.record_http_request failed", exc_info=True)


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


# Token + Cost Accounting helpers (Phase 3A.5)
_DEFAULT_TOKEN_TYPES = ("input", "output", "cached", "saved", "embedding", "avoided_input", "avoided_output", "avoided_total")
_DEFAULT_COST_TYPES = ("actual", "saved", "estimated", "avoided")


def _init_default_children() -> None:
    """Pre-create default metric children so a fresh /metrics scrape exposes them."""
    try:
        for token_type in _DEFAULT_TOKEN_TYPES:
            TOKENS_TOTAL.labels(type=token_type, tenant="default")
            ICO_CACHE_TOKENS_TOTAL.labels(type=token_type)
        for cost_type in _DEFAULT_COST_TYPES:
            COST_USD_TOTAL.labels(type=cost_type, tenant="default")
            ICO_CACHE_COST_USD_TOTAL.labels(type=cost_type)
    except Exception:  # pragma: no cover - metrics must never break requests
        logger.debug("metrics._init_default_children failed", exc_info=True)


def record_tokens(token_type: str, count: int, tenant: str = "default") -> None:
    """Record token usage.

    Args:
        token_type: One of "input", "output", "cached", "saved", "embedding", "avoided_input", "avoided_output", "avoided_total"
        count: Number of tokens
        tenant: Tenant identifier
    """
    try:
        TOKENS_TOTAL.labels(type=token_type, tenant=tenant).inc(count)
        ICO_CACHE_TOKENS_TOTAL.labels(type=token_type).inc(count)
    except Exception:
        logger.debug("metrics.record_tokens failed", exc_info=True)


def record_cost(cost_type: str, usd: float, tenant: str = "default") -> None:
    """Record cost in USD.

    Args:
        cost_type: One of "actual", "saved", "estimated", "avoided"
        usd: Cost in USD
        tenant: Tenant identifier
    """
    try:
        COST_USD_TOTAL.labels(type=cost_type, tenant=tenant).inc(usd)
        ICO_CACHE_COST_USD_TOTAL.labels(type=cost_type).inc(usd)
    except Exception:
        logger.debug("metrics.record_cost failed", exc_info=True)


def record_cost_saved(cost_type: str, usd: float, tenant: str = "default") -> None:
    """Record cost saved in USD.

    Args:
        cost_type: Type of cost saved (e.g., "llm", "embedding", "retrieval", "total")
        usd: Cost saved in USD
        tenant: Tenant identifier
    """
    try:
        COST_SAVED_USD_TOTAL.labels(type=cost_type, tenant=tenant).inc(usd)
    except Exception:
        logger.debug("metrics.record_cost_saved failed", exc_info=True)


def record_latency(phase: str, layer: str, seconds: float) -> None:
    """Record latency for a specific phase and layer.

    Args:
        phase: One of "decision", "cache_lookup", "generation", "write", "retrieval"
        layer: Cache layer (e.g., "L1", "L2", "L3", "L0a", "L0b")
        seconds: Latency in seconds
    """
    try:
        LATENCY_SECONDS.labels(phase=phase, layer=layer).observe(max(seconds, 0.0))
    except Exception:
        logger.debug("metrics.record_latency failed", exc_info=True)


def record_latency_saved(layer: str, tenant: str, seconds: float) -> None:
    """Record latency saved by cache layer.

    Args:
        layer: Cache layer that saved latency
        tenant: Tenant identifier
        seconds: Latency saved in seconds
    """
    try:
        LATENCY_SAVED_SECONDS.labels(layer=layer, tenant=tenant).observe(max(seconds, 0.0))
    except Exception:
        logger.debug("metrics.record_latency_saved failed", exc_info=True)


def record_reuse_confidence(action: str, layer: str, confidence: float) -> None:
    """Record reuse confidence.

    Args:
        action: Reuse action (e.g., "EXACT_REUSE", "SEMANTIC_REUSE", "FULL_LLM_CALL")
        layer: Cache layer that produced the decision
        confidence: Confidence value 0.0-1.0
    """
    try:
        REUSE_CONFIDENCE.labels(action=action, layer=layer).observe(confidence)
    except Exception:
        logger.debug("metrics.record_reuse_confidence failed", exc_info=True)


def record_gate_evaluation(gate: str, result: str, layer: str) -> None:
    """Record gate evaluation result.

    Args:
        gate: Gate name (e.g., "tenant_id", "model_fingerprint", "entity")
        result: "pass" or "fail"
        layer: Cache layer
    """
    try:
        GATE_EVALUATIONS.labels(gate=gate, result=result, layer=layer).inc()
    except Exception:
        logger.debug("metrics.record_gate_evaluation failed", exc_info=True)


def record_project_memory_staleness(project_id: str, commit_age_hours: float) -> None:
    """Record project memory staleness."""
    try:
        PROJECT_MEMORY_STALENESS.labels(project_id=project_id, commit_age_hours=str(int(commit_age_hours))).set(commit_age_hours)
    except Exception:
        logger.debug("metrics.record_project_memory_staleness failed", exc_info=True)


def record_false_hit_suspected(layer: str, reason: str) -> None:
    """Record suspected false hit."""
    try:
        FALSE_HIT_SUSPECTED.labels(layer=layer, reason=reason).inc()
    except Exception:
        logger.debug("metrics.record_false_hit_suspected failed", exc_info=True)


# Phase 3A.5 Accounting metric helpers
def record_llm_call(layer: str, tenant: str = "default") -> None:
    """Record an LLM call."""
    try:
        LLM_CALLS_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_llm_call failed", exc_info=True)


def record_llm_call_avoided(layer: str, tenant: str = "default") -> None:
    """Record an LLM call avoided by cache."""
    try:
        LLM_CALLS_AVOIDED_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_llm_call_avoided failed", exc_info=True)


def record_embedding_call(layer: str, tenant: str = "default") -> None:
    """Record an embedding call."""
    try:
        EMBEDDING_CALLS_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_embedding_call failed", exc_info=True)


def record_embedding_call_avoided(layer: str, tenant: str = "default") -> None:
    """Record an embedding call avoided by cache."""
    try:
        EMBEDDING_CALLS_AVOIDED_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_embedding_call_avoided failed", exc_info=True)


def record_retrieval_call(layer: str, tenant: str = "default") -> None:
    """Record a retrieval call."""
    try:
        RETRIEVAL_CALLS_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_retrieval_call failed", exc_info=True)


def record_retrieval_call_avoided(layer: str, tenant: str = "default") -> None:
    """Record a retrieval call avoided by cache."""
    try:
        RETRIEVAL_CALLS_AVOIDED_TOTAL.labels(layer=layer, tenant=tenant).inc()
    except Exception:
        logger.debug("metrics.record_retrieval_call_avoided failed", exc_info=True)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


def reset_metrics_for_testing() -> None:
    """Reset all metrics in place for testing.

    Collectors are cleared (label sets removed, unlabeled values zeroed) but the
    metric objects themselves are never unregistered or re-created, so any module
    that imported a metric at collection time keeps a live, working reference.
    Default children are re-created afterwards so scrape output stays stable.
    """
    seen: set[int] = set()
    for collector in list(REGISTRY._names_to_collectors.values()):
        if id(collector) in seen:
            continue
        seen.add(id(collector))
        try:
            if isinstance(collector, MetricWrapperBase):
                if getattr(collector, "_labelnames", None):
                    collector.clear()
                else:
                    # clear() is a no-op for unlabeled metrics; zero values in place.
                    value = getattr(collector, "_value", None)
                    if value is not None and hasattr(value, "set"):
                        value.set(0.0)
                    hist_sum = getattr(collector, "_sum", None)
                    if hist_sum is not None and hasattr(hist_sum, "set"):
                        hist_sum.set(0.0)
                    for bucket in getattr(collector, "_buckets", None) or []:
                        if hasattr(bucket, "set"):
                            bucket.set(0.0)
        except Exception:  # pragma: no cover - best effort
            logger.debug("metrics.reset_metrics_for_testing failed", exc_info=True)
    _init_default_children()


_init_default_children()


__all__ = [
    "CONTENT_TYPE_LATEST",
    "render_metrics",
    "record_lookup",
    "record_generation",
    "record_request",
    "set_backend_up",
    "inflight_inc",
    "inflight_dec",
    # Token + Cost (Phase 3A.5)
    "record_tokens",
    "record_cost",
    "record_cost_saved",
    "record_latency",
    "record_latency_saved",
    "record_reuse_confidence",
    "record_gate_evaluation",
    "record_project_memory_staleness",
    "record_false_hit_suspected",
    "record_llm_call",
    "record_llm_call_avoided",
    "record_embedding_call",
    "record_embedding_call_avoided",
    "record_retrieval_call",
    "record_retrieval_call_avoided",
]
