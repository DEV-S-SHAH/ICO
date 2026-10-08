"""
decision_trace.py — Phase 5 Decision Trace for ICO-Cache.

Structured decision tracing that explains exactly why each request was a
HIT, MISS, reuse, or an LLM call.

Every request produces a :class:`DecisionTrace` covering the full cascade:

    L0a → L0b → L1 → L2 → L3 → L4 → L5 → LLM

For every layer the trace records:

* ``attempted`` — whether the layer was consulted for this request
* ``hit`` / status — HIT, MISS, BLOCKED (gate), SKIPPED or NOT_ATTEMPTED
* ``reason`` — human readable explanation
* ``latency_ms`` — time spent in the layer
* ``reuse_source`` — which reuse mechanism produced the value

The trace also carries the final decision (:class:`DecisionOutcome`), the
request id and the tenant.  Raw queries and responses are never stored —
only a truncated SHA-256 query hash — so traces are safe to expose.

Traces are propagated with a :mod:`contextvars` "active trace" so layers
across module boundaries (CacheEngine, RAGPipeline, DecisionEngine) all
contribute to the same trace without threading arguments through every
call site.
"""

import hashlib
import re
import threading
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class LayerStatus(str, Enum):
    """Status of a single cache layer evaluation."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"  # layer never reached in this request
    ATTEMPTED = "ATTEMPTED"          # consulted, neither hit nor miss (e.g. LLM)
    HIT = "HIT"
    MISS = "MISS"
    BLOCKED = "BLOCKED"              # candidate found but a hard gate rejected it
    SKIPPED = "SKIPPED"              # reached, but preconditions not met


class DecisionOutcome(str, Enum):
    """Final decision for the request."""

    CACHE_RESPONSE = "CACHE_RESPONSE"      # L1/L2/L3 hit — cached answer returned
    REUSE_RETRIEVAL = "REUSE_RETRIEVAL"    # L4 hit — retrieval results reused
    REUSE_CONTEXT = "REUSE_CONTEXT"        # L5 hit — assembled context reused
    GENERATE_LLM = "GENERATE_LLM"          # complete miss — generated with LLM
    PARTIAL_RECOMPUTE = "PARTIAL_RECOMPUTE"


# Canonical cascade order used to present traces to the Dashboard.
CANONICAL_CASCADE: Tuple[str, ...] = ("L0a", "L0b", "L1", "L2", "L3", "L4", "L5", "LLM")

# Layers whose reuse yields a cached response (no LLM call needed).
_RESPONSE_LAYERS = ("L0a", "L0b", "L1", "L2", "L3")

# Layers that only exist inside the RAG generation path.
_RAG_LAYERS = ("L4", "L5")

_MAX_ID_LEN = 128
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_id(value: Optional[str], max_len: int = _MAX_ID_LEN) -> Optional[str]:
    """
    Sanitize an identifier (request id / tenant id) for safe storage.

    Strips control characters (log/JSON injection), trims whitespace and
    bounds the length.  Returns ``None`` for empty or unusable input.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = _CONTROL_CHARS.sub("", value).strip()
    if not value:
        return None
    if len(value) > max_len:
        value = value[:max_len]
    return value


def hash_query(query: Optional[str]) -> Optional[str]:
    """Truncated SHA-256 of the query. Raw text is never stored in a trace."""
    if not query or not isinstance(query, str):
        return None
    return hashlib.sha256(query.encode("utf-8", "replace")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────────
# Layer trace
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerTrace:
    """
    Trace record for one cache layer (L0a … L5) or the LLM stage.

    Records whether the layer was attempted, the hit/miss result, the
    reason, the latency and — for hits — the reuse source.
    """

    layer: str
    status: LayerStatus
    reason: str
    latency_ms: float = 0.0
    hit: bool = False
    confidence: float = 0.0
    score: float = 0.0
    cache_key: Optional[str] = None
    reuse_source: Optional[str] = None
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def attempted(self) -> bool:
        """True when the layer was actually consulted for this request."""
        return self.status not in (LayerStatus.NOT_ATTEMPTED, LayerStatus.SKIPPED)

    @property
    def is_hit(self) -> bool:
        """Alias kept for callers that prefer ``is_hit`` over ``hit``."""
        return self.hit

    @property
    def miss(self) -> bool:
        """True when the layer was consulted and did not produce a value."""
        return self.attempted and not self.hit

    def to_dict(self) -> Dict[str, Any]:
        """Serializable view of the layer trace."""
        return {
            "layer": self.layer,
            "attempted": self.attempted,
            "status": self.status.value,
            "hit": self.hit,
            "miss": self.miss,
            "reason": self.reason,
            "latency_ms": round(self.latency_ms, 3),
            "confidence": round(self.confidence, 3) if self.confidence else 0.0,
            "score": round(self.score, 3) if self.score else 0.0,
            "cache_key": self.cache_key,
            "reuse_source": self.reuse_source,
            "gates_passed": list(self.gates_passed),
            "gates_failed": list(self.gates_failed),
            "metadata": dict(self.metadata),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Decision trace
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DecisionTrace:
    """
    Complete decision trace for one cache request.

    Identity is limited to a request id, a tenant id and a truncated query
    hash: no raw query, context, or response content is retained.
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    request_id: Optional[str] = None
    tenant_id: str = "default"
    timestamp: float = field(default_factory=time.time)

    layers: List[LayerTrace] = field(default_factory=list)

    outcome: DecisionOutcome = DecisionOutcome.GENERATE_LLM
    final_layer: Optional[str] = None
    final_confidence: float = 0.0
    final_reason: str = ""

    total_latency_ms: float = 0.0

    query_hash: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None

    finalized: bool = False

    # ------------------------------------------------------------------
    def add_layer_trace(self, trace: LayerTrace) -> LayerTrace:
        """Append a layer trace (replacing an existing entry for the layer)."""
        self.layers = [le for le in self.layers if le.layer != trace.layer]
        self.layers.append(trace)
        return trace

    def get_layer(self, layer: str) -> Optional[LayerTrace]:
        """Return the trace for a layer, if it was recorded."""
        for entry in self.layers:
            if entry.layer == layer:
                return entry
        return None

    @property
    def cache_hit(self) -> bool:
        """True when any cache layer produced a hit."""
        return any(le.hit for le in self.layers)

    @property
    def layers_attempted(self) -> List[str]:
        """Names of layers that were consulted, in cascade order."""
        return [le.layer for le in self._ordered() if le.attempted]

    @property
    def reused_retrieval(self) -> bool:
        return self.outcome == DecisionOutcome.REUSE_RETRIEVAL

    @property
    def reused_context(self) -> bool:
        return self.outcome == DecisionOutcome.REUSE_CONTEXT

    @property
    def reused_response(self) -> bool:
        return self.outcome == DecisionOutcome.CACHE_RESPONSE

    # ------------------------------------------------------------------
    def _ordered(self) -> List[LayerTrace]:
        """Layers in canonical cascade order, unknown layers kept at the end."""
        by_name: Dict[str, LayerTrace] = {}
        extras: List[LayerTrace] = []
        for entry in self.layers:
            if entry.layer in CANONICAL_CASCADE:
                by_name[entry.layer] = entry
            else:
                extras.append(entry)
        ordered = [by_name.pop(name) for name in CANONICAL_CASCADE if name in by_name]
        ordered.extend(extras)
        return ordered

    def _not_attempted(self, layer: str) -> LayerTrace:
        if layer == "LLM":
            if self.outcome == DecisionOutcome.GENERATE_LLM:
                return LayerTrace(
                    layer="LLM",
                    status=LayerStatus.ATTEMPTED,
                    reason=self.final_reason or "LLM generation required: no cached reuse path found",
                )
            return LayerTrace(
                layer="LLM",
                status=LayerStatus.NOT_ATTEMPTED,
                reason="LLM not called: response served from cache",
            )
        if self.final_layer and self.final_layer in CANONICAL_CASCADE:
            try:
                stop_idx = CANONICAL_CASCADE.index(self.final_layer)
                layer_idx = CANONICAL_CASCADE.index(layer)
                if layer_idx > stop_idx:
                    return LayerTrace(
                        layer=layer,
                        status=LayerStatus.NOT_ATTEMPTED,
                        reason=f"Not attempted: request satisfied at {self.final_layer}",
                    )
            except ValueError:
                pass
        return LayerTrace(
            layer=layer,
            status=LayerStatus.NOT_ATTEMPTED,
            reason="Not evaluated in this decision path",
        )

    def ensure_cascade(self) -> None:
        """Fill in every canonical layer so the full L0→LLM cascade is present."""
        present = {le.layer for le in self.layers}
        for layer in CANONICAL_CASCADE:
            if layer not in present:
                self.add_layer_trace(self._not_attempted(layer))
        self.layers = self._ordered()

    def finalize(
        self,
        outcome: DecisionOutcome,
        final_layer: Optional[str] = None,
        final_confidence: float = 0.0,
        final_reason: str = "",
    ) -> "DecisionTrace":
        """Seal the trace: record the decision, complete the cascade, sum latency."""
        self.outcome = outcome
        self.final_layer = final_layer
        self.final_confidence = final_confidence
        self.final_reason = final_reason
        self.ensure_cascade()
        self.total_latency_ms = sum(le.latency_ms for le in self.layers)
        self.finalized = True
        return self

    # ------------------------------------------------------------------
    def summary(self) -> str:
        """One-line human readable explanation of the decision."""
        lat = f", latency={self.total_latency_ms:.1f}ms"
        if self.outcome == DecisionOutcome.CACHE_RESPONSE:
            return (
                f"{self.final_layer} HIT: {self.final_reason} "
                f"(confidence={self.final_confidence:.2f}{lat})"
            )
        if self.outcome == DecisionOutcome.REUSE_RETRIEVAL:
            return f"L4 HIT: reused retrieval results ({self.final_reason}{lat})"
        if self.outcome == DecisionOutcome.REUSE_CONTEXT:
            return f"L5 HIT: reused assembled context ({self.final_reason}{lat})"
        if self.outcome == DecisionOutcome.PARTIAL_RECOMPUTE:
            return f"PARTIAL_RECOMPUTE: {self.final_reason}{lat}"
        return f"MISS: {self.final_reason}{lat}"

    def to_dict(self) -> Dict[str, Any]:
        """Serializable view consumed by the Dashboard / HTTP API."""
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp,
            "layers": [le.to_dict() for le in self._ordered()],
            "outcome": self.outcome.value,
            "final_layer": self.final_layer,
            "final_confidence": round(self.final_confidence, 3),
            "final_reason": self.final_reason,
            "cache_hit": self.cache_hit,
            "reused_response": self.reused_response,
            "reused_retrieval": self.reused_retrieval,
            "reused_context": self.reused_context,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "query_hash": self.query_hash,
            "model": self.model,
            "provider": self.provider,
            "summary": self.summary(),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Trace store
# ──────────────────────────────────────────────────────────────────────────────

class DecisionTraceStore:
    """
    Bounded, thread-safe store of recent decision traces.

    Indexes traces by trace id, request id and tenant so the Dashboard can
    fetch a single trace or browse recent ones per tenant.
    """

    def __init__(self, max_traces: int = 1000):
        self.max_traces = max(1, int(max_traces))
        self._lock = threading.Lock()
        self._traces: Dict[str, DecisionTrace] = {}
        self._by_request: Dict[str, str] = {}
        self._by_tenant: Dict[str, List[str]] = {}
        self._order: List[str] = []

    def store(self, trace: DecisionTrace) -> DecisionTrace:
        """Store a finalized trace, evicting the oldest when over capacity."""
        with self._lock:
            trace_id = trace.trace_id
            # Drop any previous registration of the same trace id.
            self._evict(trace_id)
            self._traces[trace_id] = trace
            self._order.append(trace_id)
            if trace.request_id:
                self._by_request[trace.request_id] = trace_id
            tenant = trace.tenant_id or "default"
            self._by_tenant.setdefault(tenant, []).append(trace_id)
            while len(self._traces) > self.max_traces:
                oldest = self._order.pop(0)
                if oldest == trace_id:
                    continue
                self._evict(oldest)
        return trace

    def _evict(self, trace_id: str) -> None:
        """Remove a trace and its index entries (caller holds the lock)."""
        existing = self._traces.pop(trace_id, None)
        if existing is None:
            return
        if trace_id in self._order:
            try:
                self._order.remove(trace_id)
            except ValueError:
                pass
        if existing.request_id and self._by_request.get(existing.request_id) == trace_id:
            self._by_request.pop(existing.request_id, None)
        tenant = existing.tenant_id or "default"
        bucket = self._by_tenant.get(tenant)
        if bucket and trace_id in bucket:
            bucket.remove(trace_id)
            if not bucket:
                self._by_tenant.pop(tenant, None)

    def get_by_trace_id(self, trace_id: str) -> Optional[DecisionTrace]:
        with self._lock:
            return self._traces.get(trace_id)

    def get_by_request_id(self, request_id: str) -> Optional[DecisionTrace]:
        rid = safe_id(request_id)
        if not rid:
            return None
        with self._lock:
            trace_id = self._by_request.get(rid)
            return self._traces.get(trace_id) if trace_id else None

    def get_recent(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[DecisionTrace]:
        """Most recent traces, optionally restricted to one tenant."""
        limit = max(0, int(limit))
        with self._lock:
            if tenant_id is not None:
                ids = self._by_tenant.get(tenant_id, [])
                chosen = list(reversed(ids))[:limit]
            else:
                chosen = list(reversed(self._order))[:limit]
            return [self._traces[t] for t in chosen if t in self._traces]

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._by_request.clear()
            self._by_tenant.clear()
            self._order.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_outcome: Dict[str, int] = {}
            by_tenant: Dict[str, int] = {}
            for trace in self._traces.values():
                by_outcome[trace.outcome.value] = by_outcome.get(trace.outcome.value, 0) + 1
                tenant = trace.tenant_id or "default"
                by_tenant[tenant] = by_tenant.get(tenant, 0) + 1
            return {
                "total_traces": len(self._traces),
                "by_outcome": by_outcome,
                "by_tenant": by_tenant,
                "max_traces": self.max_traces,
            }


# ──────────────────────────────────────────────────────────────────────────────
# Active-trace propagation (contextvars)
# ──────────────────────────────────────────────────────────────────────────────

_active_trace: ContextVar[Optional[DecisionTrace]] = ContextVar(
    "ico_cache_active_decision_trace", default=None
)


def get_active_trace() -> Optional[DecisionTrace]:
    """Return the decision trace active in the current task context, if any."""
    return _active_trace.get()


def set_active_trace(trace: Optional[DecisionTrace]) -> Token:
    """Make ``trace`` active; pass the token to :func:`reset_active_trace`."""
    return _active_trace.set(trace)


def reset_active_trace(token: Token) -> None:
    """Restore the previously active trace."""
    _active_trace.reset(token)


def record_layer(
    layer: str,
    status: LayerStatus,
    reason: str,
    *,
    latency_ms: float = 0.0,
    hit: bool = False,
    confidence: float = 0.0,
    score: float = 0.0,
    cache_key: Optional[str] = None,
    reuse_source: Optional[str] = None,
    gates_passed: Optional[List[str]] = None,
    gates_failed: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[LayerTrace]:
    """
    Record a layer evaluation on the active trace.

    No-op (returns ``None``) when no trace is active, so instrumenting a
    layer never changes behavior when tracing is disabled.
    """
    trace = _active_trace.get()
    if trace is None:
        return None
    entry = LayerTrace(
        layer=layer,
        status=status,
        reason=reason,
        latency_ms=latency_ms,
        hit=hit,
        confidence=confidence,
        score=score,
        cache_key=cache_key,
        reuse_source=reuse_source,
        gates_passed=list(gates_passed or []),
        gates_failed=list(gates_failed or []),
        metadata=dict(metadata or {}),
    )
    return trace.add_layer_trace(entry)


def begin_trace(
    request_id: Optional[str] = None,
    tenant_id: str = "default",
    *,
    query: Optional[str] = None,
    query_hash: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    reuse_active: bool = True,
) -> Tuple[Optional[DecisionTrace], Optional[Token], bool]:
    """
    Start (or join) a trace for the current request context.

    Returns ``(trace, token, created)``:

    * ``trace``   — the active trace, or ``None`` when tracing is disabled
    * ``token``   — token to pass to :func:`reset_active_trace` (if created)
    * ``created`` — True when this call created the trace (the creator owns
      finalization and storage)

    When ``reuse_active`` is True and a trace is already active in this
    context, that trace is reused and ``created`` is False.
    """
    if reuse_active:
        existing = _active_trace.get()
        if existing is not None:
            return existing, None, False

    trace = DecisionTrace(
        request_id=safe_id(request_id),
        tenant_id=safe_id(tenant_id) or "default",
        query_hash=query_hash if query_hash is not None else hash_query(query),
        model=safe_id(model) if model else None,
        provider=safe_id(provider) if provider else None,
    )
    token = _active_trace.set(trace)
    return trace, token, True


def derive_outcome(trace: DecisionTrace) -> DecisionOutcome:
    """
    Derive the final decision from the recorded cascade.

    Precedence: cached response (L1/L2/L3) > reused context (L5) >
    reused retrieval (L4) > full LLM generation.
    """
    if trace.final_layer in _RESPONSE_LAYERS:
        layer = trace.get_layer(trace.final_layer)
        if layer is not None and layer.hit:
            return DecisionOutcome.CACHE_RESPONSE

    l5 = trace.get_layer("L5")
    if l5 is not None and l5.hit:
        return DecisionOutcome.REUSE_CONTEXT

    l4 = trace.get_layer("L4")
    if l4 is not None and l4.hit:
        return DecisionOutcome.REUSE_RETRIEVAL

    return DecisionOutcome.GENERATE_LLM


__all__ = [
    "CANONICAL_CASCADE",
    "DecisionOutcome",
    "DecisionTrace",
    "DecisionTraceStore",
    "LayerStatus",
    "LayerTrace",
    "begin_trace",
    "derive_outcome",
    "get_active_trace",
    "hash_query",
    "record_layer",
    "reset_active_trace",
    "safe_id",
    "set_active_trace",
]
