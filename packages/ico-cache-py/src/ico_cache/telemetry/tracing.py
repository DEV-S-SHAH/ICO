import time
from contextlib import contextmanager
from typing import Any, Generator, Optional
from opentelemetry import trace
from opentelemetry.trace import Tracer, Span

TRACER_NAME = "ico_cache"


def get_tracer() -> Tracer:
    """Returns the OpenTelemetry tracer instance for ico_cache."""
    return trace.get_tracer(TRACER_NAME)


class LayerSpanRecorder:
    def __init__(self, span: Span, t0: float):
        self.span = span
        self.t0 = t0
        self.recorded = False

    def record_result(self, hit: bool, **extra_attrs: Any):
        duration_ms = (time.perf_counter() - self.t0) * 1000
        self.span.set_attribute("cache.hit", bool(hit))
        self.span.set_attribute("latency_ms", round(duration_ms, 3))
        for k, v in extra_attrs.items():
            if v is not None:
                self.span.set_attribute(k, v)
        self.recorded = True


@contextmanager
def trace_cache_lookup(
    layer: str, tenant_id: str = "default", query: str = ""
) -> Generator[LayerSpanRecorder, None, None]:
    """
    Context manager that starts an OpenTelemetry span around a cache layer lookup.
    Emits attributes:
      - cache.layer (L1, L2, L3)
      - tenant_id
      - query
      - cache.hit (bool)
      - latency_ms (float)
    """
    tracer = get_tracer()
    start_time = time.perf_counter()
    span_name = f"cache_lookup.{layer.lower()}"
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("cache.layer", layer)
        span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("query", query)

        recorder = LayerSpanRecorder(span, start_time)
        try:
            yield recorder
        finally:
            if not recorder.recorded:
                duration_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("cache.hit", False)
                span.set_attribute("latency_ms", round(duration_ms, 3))


class FallbackSpanRecorder:
    def __init__(self, span: Span, t0: float):
        self.span = span
        self.t0 = t0

    def record_completion(self, citations_count: int = 0, score: float = 0.0):
        duration_ms = (time.perf_counter() - self.t0) * 1000
        self.span.set_attribute("latency_ms", round(duration_ms, 3))
        self.span.set_attribute("citations_count", citations_count)
        self.span.set_attribute("score", score)


@contextmanager
def trace_rag_fallback(
    tenant_id: str = "default", query: str = ""
) -> Generator[FallbackSpanRecorder, None, None]:
    """
    Context manager that starts an OpenTelemetry span around the RAG fallback path.
    Emits attributes:
      - cache.layer ('RAG_FALLBACK')
      - cache.hit (False)
      - tenant_id
      - query
      - latency_ms
    """
    tracer = get_tracer()
    start_time = time.perf_counter()
    with tracer.start_as_current_span("rag_fallback") as span:
        span.set_attribute("cache.layer", "RAG_FALLBACK")
        span.set_attribute("cache.hit", False)
        span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("query", query)

        recorder = FallbackSpanRecorder(span, start_time)
        try:
            yield recorder
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("latency_ms", round(duration_ms, 3))
