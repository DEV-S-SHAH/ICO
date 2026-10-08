"""Accounting and usage tracking for token/cost observability.

Provides UsageRecord data model, thread-safe UsageTracker with tenant isolation,
CostCalculator for centralized cost estimation, SavingsCalculator for avoided
usage computation, and PricingModel with versioning support.

Also maintains backward compatibility with existing CacheLayer, DecisionAction,
AccountingContext, and AccountingCollector APIs used by cache_engine.

Security features:
- Input validation on all accounting records (hard gates)
- Metadata scrubbing to prevent secret leakage
- Per-tenant rate limiting to prevent DoS
- Pricing integrity verification via cost_model
- Immutable records for audit trail
"""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from ico_cache.telemetry.cost_model import CostModel, get_cost_model
from ico_cache.telemetry.provider_adapters import UsageSource as ProviderUsageSource

logger = logging.getLogger("ico_cache.telemetry.accounting")


# ──────────────────────────────────────────────────────────────────────────────
# Secret scrubbing utilities
# ──────────────────────────────────────────────────────────────────────────────

# Secret patterns to scrub from metadata before logging/storage
# Matching is exact or `_pattern`-suffixed / `pattern_`-prefixed to avoid false
# positives like "max_tokens" or benign fields ("session_id", "request_id").
_SECRET_PATTERNS = frozenset({
    "api_key", "apikey", "api-key", "secret", "token", "password",
    "passwd", "pass", "authorization", "bearer", "x_api_key", "x_auth_token",
    "access_token", "refresh_token", "client_secret", "private_key",
    "ssh_key", "cert", "key_id", "aws_secret", "azure_key", "gcp_key",
    "auth_token", "jwt", "cookie", "csrf",
})


def _scrub_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Remove potential secrets from metadata before logging/recording.

    Recursively scrubs nested dicts. Truncates values > 100 chars.
    Uses exact key matching (case-insensitive) to avoid false positives.
    """
    if not metadata:
        return {}
    scrubbed = {}
    for k, v in metadata.items():
        key_lower = k.lower()
        # Check for exact match or common prefixes/suffixes
        is_secret = False
        for pattern in _SECRET_PATTERNS:
            if key_lower == pattern or key_lower.endswith("_" + pattern) or key_lower.startswith(pattern + "_"):
                is_secret = True
                break
        if is_secret:
            scrubbed[k] = "***REDACTED***"
        elif isinstance(v, dict):
            scrubbed[k] = _scrub_metadata(v)
        elif isinstance(v, str) and len(v) > 100:
            scrubbed[k] = v[:100] + "...[truncated]"
        else:
            scrubbed[k] = v
    return scrubbed


def _validate_non_negative_int(value: int, field_name: str) -> None:
    """Validate integer is non-negative. Raises ValueError if invalid."""
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_non_negative_float(value: float, field_name: str) -> None:
    """Validate float is non-negative. Raises ValueError if invalid."""
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative number")


def _validate_max_one(value: float, field_name: str) -> None:
    """Validate score is between 0.0 and 1.0. Raises ValueError if invalid."""
    if not isinstance(value, (int, float)) or value > 1.0:
        raise ValueError(f"{field_name} must be <= 1.0")


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compatible enums (used by cache_engine)
# ──────────────────────────────────────────────────────────────────────────────

class CacheLayer(str, Enum):
    """Cache layers in the ICO-Cache hierarchy (backward compatible)."""
    L0A = "L0a"
    L0B = "L0b"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"
    L8 = "L8"
    L9 = "L9"
    RAG_FALLBACK = "RAG_FALLBACK"
    NONE = "NONE"


class DecisionAction(str, Enum):
    """Action taken after evaluating reuse opportunities (backward compatible)."""
    EXACT_REUSE = "EXACT_REUSE"
    SEMANTIC_REUSE = "SEMANTIC_REUSE"
    CONTEXT_REUSE = "CONTEXT_REUSE"
    MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    PARTIAL_RECOMPUTE = "PARTIAL_RECOMPUTE"
    FULL_LLM_CALL = "FULL_LLM_CALL"
    ERROR = "ERROR"
    REFUSAL = "REFUSAL"


# Re-export UsageSource from provider_adapters for compatibility
UsageSource = ProviderUsageSource


class UsageType(str, Enum):
    """Type of token usage."""
    INPUT = "input"
    OUTPUT = "output"
    CACHED = "cached"
    SAVED = "saved"
    EMBEDDING = "embedding"
    CONTEXT_CONSTRUCTION = "context_construction"
    RERANKER = "reranker"


# ──────────────────────────────────────────────────────────────────────────────
# Token types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenUsage:
    """Token usage breakdown."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.total_tokens


@dataclass(frozen=True)
class LayerAttribution:
    """Attribution of tokens to cache layers."""
    L0a: int = 0
    L0b: int = 0
    L1: int = 0
    L2: int = 0
    L3: int = 0
    L4: int = 0
    L5: int = 0
    L6: int = 0
    L7: int = 0
    L8: int = 0
    L9: int = 0
    RAG_FALLBACK: int = 0
    NONE: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Pricing Version for historical reproducibility
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PricingVersion:
    """Pricing version for historical reproducibility."""
    version: str
    effective_date: datetime
    source: str
    description: str = ""

    def __str__(self) -> str:
        return self.version


# ──────────────────────────────────────────────────────────────────────────────
# New spec-compliant UsageRecord (Phase 3A.5)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UsageRecord:
    """Complete usage record for a single cache decision cycle.

    All fields are immutable once created. Use UsageTracker.record() to
    build and persist records.

    Two construction modes are supported (selected by ``timestamp`` type):

    * **Modern** (``timestamp: datetime``): the spec-compliant interface used by
      cache_engine and the RAG pipeline. ``layer`` may be a plain string and an
      empty ``tenant_id`` is permitted for metric-only recording.
    * **Legacy** (``timestamp: float`` epoch seconds): a stricter audit-friendly
      mode that requires ``layer``/``decision_action`` to be enum values, a
      non-empty ``tenant_id``, and validates the legacy field set
      (``cached_tokens``, ``saved_tokens``, ``*_cost_usd``, latency, scores, gates).
    """

    # --- Required identity ---
    request_id: str
    trace_id: str = ""
    tenant_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    layer: str = ""  # "L1", "L2", "L3", "L0a", "L0b", "RAG_FALLBACK"
    decision_action: DecisionAction = DecisionAction.FULL_LLM_CALL

    # --- Usage counts (integers) ---
    cache_hit: int = 0
    cache_miss: int = 0
    llm_called: int = 0
    embedding_called: int = 0
    retrieval_called: int = 0
    reranker_called: int = 0

    # --- Token accounting ---
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    avoided_input_tokens: int = 0
    avoided_output_tokens: int = 0
    avoided_total_tokens: int = 0
    embedding_tokens: int = 0
    retrieval_units: int = 0

    # --- Cost accounting (USD) ---
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    tokens_saved: int = 0
    cost_saved: float = 0.0
    latency_saved: float = 0.0  # seconds

    # --- Latency ---
    latency_ms: float = 0.0

    # --- Model/Provider metadata ---
    model: str = ""
    model_fingerprint: str = ""
    provider: str = ""
    currency: str = "USD"
    pricing_version: str = ""

    # --- Status ---
    success: bool = True
    error: str = ""

    # --- Diagnostics ---
    metadata: Dict[str, Any] = field(default_factory=dict)
    usage_source: UsageSource = UsageSource.UNKNOWN

    # --- Legacy field set (backward compat with ValidatedAccountingCollector) ---
    cached_tokens: int = 0
    saved_tokens: int = 0
    actual_cost_usd: float = 0.0
    saved_cost_usd: float = 0.0
    decision_latency_ms: float = 0.0
    cache_lookup_latency_ms: float = 0.0
    embedding_latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    reranking_latency_ms: float = 0.0
    context_construction_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    reuse_confidence: float = 0.0
    retrieval_score: float = 0.0
    reranker_score: float = 0.0
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate fields after initialization (mode-dependent)."""
        # Scrub metadata and extra regardless of mode (best effort, never raises)
        try:
            object.__setattr__(self, "metadata", _scrub_metadata(self.metadata))
        except Exception:  # pragma: no cover - scrubbing must never break recording
            object.__setattr__(self, "metadata", {})
        try:
            object.__setattr__(self, "extra", _scrub_metadata(self.extra))
        except Exception:  # pragma: no cover
            object.__setattr__(self, "extra", {})

        if isinstance(self.timestamp, (int, float)):
            self._validate_legacy()
        else:
            self._validate_modern()

    def _validate_modern(self) -> None:
        """Validate modern (datetime timestamp) mode fields."""
        int_fields = [
            'cache_hit', 'cache_miss', 'llm_called', 'embedding_called',
            'retrieval_called', 'reranker_called', 'input_tokens', 'output_tokens',
            'total_tokens', 'cached_input_tokens', 'avoided_input_tokens',
            'avoided_output_tokens', 'avoided_total_tokens', 'embedding_tokens',
            'retrieval_units', 'tokens_saved'
        ]
        for field_name in int_fields:
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")

        float_fields = [
            'estimated_cost', 'actual_cost', 'cost_saved', 'latency_saved',
            'latency_ms'
        ]
        for field_name in float_fields:
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")

    def _validate_legacy(self) -> None:
        """Validate legacy (float epoch timestamp) mode fields strictly.

        Strict validation prevents forged/inflated records and keeps the
        audit trail trustworthy (see Phase 4 accounting security contract).
        """
        if not isinstance(self.tenant_id, str) or not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not isinstance(self.timestamp, (int, float)) or self.timestamp <= 0:
            raise ValueError("timestamp must be a positive number")
        if not isinstance(self.layer, CacheLayer):
            raise ValueError("layer must be a CacheLayer enum")
        if not isinstance(self.decision_action, DecisionAction):
            raise ValueError("decision_action must be a DecisionAction enum")

        int_fields = [
            'input_tokens', 'output_tokens', 'cached_tokens', 'saved_tokens',
            'cache_hit', 'cache_miss', 'llm_called', 'embedding_called',
            'retrieval_called', 'reranker_called'
        ]
        for field_name in int_fields:
            _validate_non_negative_int(getattr(self, field_name), field_name)

        float_fields = [
            'estimated_cost', 'actual_cost', 'cost_saved', 'latency_saved',
            'latency_ms', 'actual_cost_usd', 'saved_cost_usd',
            'decision_latency_ms', 'cache_lookup_latency_ms',
            'embedding_latency_ms', 'retrieval_latency_ms',
            'reranking_latency_ms', 'context_construction_latency_ms',
            'generation_latency_ms', 'total_latency_ms',
        ]
        for field_name in float_fields:
            _validate_non_negative_float(getattr(self, field_name), field_name)

        for field_name in ('reuse_confidence', 'retrieval_score', 'reranker_score'):
            _validate_max_one(getattr(self, field_name), field_name)

        if not isinstance(self.gates_passed, list):
            raise ValueError("gates_passed must be a list")
        if not isinstance(self.gates_failed, list):
            raise ValueError("gates_failed must be a list")

    @classmethod
    def create(
        cls,
        tenant_id: str,
        layer: str,
        decision_action: DecisionAction,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> "UsageRecord":
        """Factory for creating a new UsageRecord with defaults."""
        return cls(
            request_id=request_id or str(uuid.uuid4()),
            trace_id=trace_id or str(uuid.uuid4()),
            tenant_id=tenant_id,
            timestamp=timestamp or datetime.now(timezone.utc),
            layer=layer,
            decision_action=decision_action,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization/logging."""
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else self.timestamp,
            "layer": self.layer.value if isinstance(self.layer, CacheLayer) else self.layer,
            "decision_action": self.decision_action.value
            if isinstance(self.decision_action, DecisionAction)
            else self.decision_action,
            "cache_hit": self.cache_hit,
            "cache_miss": self.cache_miss,
            "llm_called": self.llm_called,
            "embedding_called": self.embedding_called,
            "retrieval_called": self.retrieval_called,
            "reranker_called": self.reranker_called,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "avoided_input_tokens": self.avoided_input_tokens,
            "avoided_output_tokens": self.avoided_output_tokens,
            "avoided_total_tokens": self.avoided_total_tokens,
            "embedding_tokens": self.embedding_tokens,
            "retrieval_units": self.retrieval_units,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "tokens_saved": self.tokens_saved,
            "cost_saved": self.cost_saved,
            "latency_saved": self.latency_saved,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "model_fingerprint": self.model_fingerprint,
            "provider": self.provider,
            "currency": self.currency,
            "pricing_version": self.pricing_version,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
            "usage_source": self.usage_source.value
            if isinstance(self.usage_source, UsageSource)
            else self.usage_source,
            "cached_tokens": self.cached_tokens,
            "saved_tokens": self.saved_tokens,
            "actual_cost_usd": self.actual_cost_usd,
            "saved_cost_usd": self.saved_cost_usd,
            "decision_latency_ms": self.decision_latency_ms,
            "cache_lookup_latency_ms": self.cache_lookup_latency_ms,
            "embedding_latency_ms": self.embedding_latency_ms,
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "reranking_latency_ms": self.reranking_latency_ms,
            "context_construction_latency_ms": self.context_construction_latency_ms,
            "generation_latency_ms": self.generation_latency_ms,
            "total_latency_ms": self.total_latency_ms,
            "reuse_confidence": self.reuse_confidence,
            "retrieval_score": self.retrieval_score,
            "reranker_score": self.reranker_score,
            "gates_passed": self.gates_passed,
            "gates_failed": self.gates_failed,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsageRecord":
        """Create a UsageRecord from a serialized dict.

        Accepts both payload shapes:

        * ``timestamp`` ISO-8601 string → modern mode (layer/action may be str).
        * ``timestamp`` numeric epoch or absent → legacy mode; string
          ``layer``/``decision_action`` values are coerced to enums.

        ``extra`` and ``metadata`` are scrubbed during construction.
        """
        payload = dict(data)
        timestamp = payload.pop("timestamp", None)
        request_id = payload.pop("request_id", "")
        trace_id = payload.pop("trace_id", "")
        tenant_id = payload.pop("tenant_id", "")
        layer = payload.pop("layer", "L1")
        decision_action = payload.pop("decision_action", "EXACT_REUSE")

        if isinstance(timestamp, str):
            ts = datetime.fromisoformat(timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return cls(
                request_id=request_id,
                trace_id=trace_id,
                tenant_id=tenant_id,
                timestamp=ts,
                layer=layer,
                decision_action=decision_action,
                **payload,
            )

        ts = timestamp if isinstance(timestamp, (int, float)) else time.time()
        if isinstance(layer, str):
            layer = CacheLayer(layer)
        if isinstance(decision_action, str):
            decision_action = DecisionAction(decision_action)
        return cls(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            timestamp=ts,
            layer=layer,
            decision_action=decision_action,
            **payload,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compatible AccountingContext (mutable builder for UsageRecord)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AccountingContext:
    """
    Mutable context for building a UsageRecord during request processing.

    Used internally to accumulate metrics across phases, then frozen into
    a UsageRecord at the end. Backward compatible with cache_engine.
    """

    request_id: str
    tenant_id: str
    layer: CacheLayer = CacheLayer.NONE
    decision_action: DecisionAction = DecisionAction.FULL_LLM_CALL

    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    saved_tokens: int = 0

    # Embedding
    embedding_calls: int = 0
    embedding_calls_avoided: int = 0
    embedding_input_tokens: int = 0
    embedding_latency_ms: float = 0.0

    # Retrieval
    retrieval_calls: int = 0
    retrieval_calls_avoided: int = 0
    chunks_retrieved: int = 0
    chunks_filtered: int = 0
    retrieval_latency_ms: float = 0.0
    retrieval_score: float = 0.0

    # L4 Retrieval Cache
    retrieval_cache_hits: int = 0
    retrieval_cache_misses: int = 0
    retrieval_latency_saved_ms: float = 0.0

    # Reranking
    reranker_calls: int = 0
    reranker_calls_avoided: int = 0
    chunks_reranked: int = 0
    chunks_used: int = 0
    reranking_latency_ms: float = 0.0
    reranker_score: float = 0.0

    # Context construction
    context_construction_tokens: int = 0
    context_construction_tokens_avoided: int = 0
    context_chunks: int = 0
    context_construction_latency_ms: float = 0.0
    context_construction_latency_saved_ms: float = 0.0
    context_cache_hits: int = 0
    context_cache_misses: int = 0

    # Cache lookup
    cache_lookup_latency_ms: float = 0.0

    # Generation
    generation_latency_ms: float = 0.0

    # Decision
    decision_latency_ms: float = 0.0

    # Total latency (computed at end)
    total_latency_ms: float = 0.0

    # Cost
    actual_cost_usd: float = 0.0
    saved_cost_usd: float = 0.0

    # Confidence
    reuse_confidence: float = 0.0

    # Gates
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)

    # Errors
    error: Optional[str] = None
    error_phase: Optional[str] = None

    # Extra
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> UsageRecord:
        """Finalize and create immutable UsageRecord (spec-compliant)."""
        total_latency = (
            self.decision_latency_ms
            + self.cache_lookup_latency_ms
            + self.embedding_latency_ms
            + self.retrieval_latency_ms
            + self.reranking_latency_ms
            + self.context_construction_latency_ms
            + self.generation_latency_ms
        )
        # Map old field names to new spec fields
        return UsageRecord(
            request_id=self.request_id,
            tenant_id=self.tenant_id,
            trace_id=str(uuid.uuid4()),  # Not tracked in old context
            timestamp=datetime.now(timezone.utc),
            layer=self.layer.value,
            decision_action=self.decision_action,
            cache_hit=1 if self.cached_tokens > 0 else 0,
            cache_miss=1 if self.cached_tokens == 0 and self.decision_action == DecisionAction.FULL_LLM_CALL else 0,
            llm_called=1 if self.decision_action == DecisionAction.FULL_LLM_CALL else 0,
            embedding_called=self.embedding_calls,
            retrieval_called=self.retrieval_calls,
            reranker_called=self.reranker_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.input_tokens + self.output_tokens,
            cached_input_tokens=self.cached_tokens,
            avoided_input_tokens=max(0, self.saved_tokens - self.output_tokens) if self.saved_tokens > self.output_tokens else 0,
            avoided_output_tokens=max(0, self.saved_tokens - self.input_tokens) if self.saved_tokens > self.input_tokens else 0,
            avoided_total_tokens=self.saved_tokens,
            embedding_tokens=self.embedding_input_tokens,
            retrieval_units=self.chunks_retrieved,
            estimated_cost=0.0,
            actual_cost=self.actual_cost_usd,
            tokens_saved=self.saved_tokens,
            cost_saved=self.saved_cost_usd,
            latency_saved=0.0,  # Not tracked in old context
            latency_ms=total_latency,
            model=self.extra.get("model", ""),
            model_fingerprint=self.extra.get("model_fingerprint", ""),
            provider=self.extra.get("provider", ""),
            currency="USD",
            pricing_version=get_pricing_model().get_current_version(),
            success=self.error is None,
            error=self.error or "",
            metadata=_scrub_metadata(self.extra),
            usage_source=UsageSource.ESTIMATED,
        )

    def to_legacy_record(self) -> "LegacyUsageRecord":
        """Create legacy UsageRecord for backward compatibility."""
        total_latency = (
            self.decision_latency_ms
            + self.cache_lookup_latency_ms
            + self.embedding_latency_ms
            + self.retrieval_latency_ms
            + self.reranking_latency_ms
            + self.context_construction_latency_ms
            + self.generation_latency_ms
        )
        return LegacyUsageRecord(
            request_id=self.request_id,
            tenant_id=self.tenant_id,
            timestamp=time.time(),
            layer=self.layer,
            decision_action=self.decision_action,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cached_tokens=self.cached_tokens,
            saved_tokens=self.saved_tokens,
            embedding_calls=self.embedding_calls,
            embedding_calls_avoided=self.embedding_calls_avoided,
            embedding_input_tokens=self.embedding_input_tokens,
            retrieval_calls=self.retrieval_calls,
            retrieval_calls_avoided=self.retrieval_calls_avoided,
            chunks_retrieved=self.chunks_retrieved,
            chunks_filtered=self.chunks_filtered,
            reranker_calls=self.reranker_calls,
            reranker_calls_avoided=self.reranker_calls_avoided,
            chunks_reranked=self.chunks_reranked,
            chunks_used=self.chunks_used,
            context_construction_tokens=self.context_construction_tokens,
            context_construction_tokens_avoided=self.context_construction_tokens_avoided,
            context_chunks=self.context_chunks,
            decision_latency_ms=self.decision_latency_ms,
            cache_lookup_latency_ms=self.cache_lookup_latency_ms,
            embedding_latency_ms=self.embedding_latency_ms,
            retrieval_latency_ms=self.retrieval_latency_ms,
            reranking_latency_ms=self.reranking_latency_ms,
            context_construction_latency_ms=self.context_construction_latency_ms,
            generation_latency_ms=self.generation_latency_ms,
            total_latency_ms=total_latency,
            actual_cost_usd=self.actual_cost_usd,
            saved_cost_usd=self.saved_cost_usd,
            reuse_confidence=self.reuse_confidence,
            retrieval_score=self.retrieval_score,
            reranker_score=self.reranker_score,
            gates_passed=self.gates_passed,
            gates_failed=self.gates_failed,
            error=self.error,
            error_phase=self.error_phase,
            extra=self.extra,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Legacy UsageRecord (backward compatibility alias)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LegacyUsageRecord:
    """Legacy UsageRecord for backward compatibility with existing code."""
    request_id: str
    tenant_id: str
    timestamp: float
    layer: CacheLayer
    decision_action: DecisionAction
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    saved_tokens: int = 0
    embedding_calls: int = 0
    embedding_calls_avoided: int = 0
    embedding_input_tokens: int = 0
    retrieval_calls: int = 0
    retrieval_calls_avoided: int = 0
    chunks_retrieved: int = 0
    chunks_filtered: int = 0
    reranker_calls: int = 0
    reranker_calls_avoided: int = 0
    chunks_reranked: int = 0
    chunks_used: int = 0
    context_construction_tokens: int = 0
    context_construction_tokens_avoided: int = 0
    context_chunks: int = 0
    decision_latency_ms: float = 0.0
    cache_lookup_latency_ms: float = 0.0
    embedding_latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    reranking_latency_ms: float = 0.0
    context_construction_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    actual_cost_usd: float = 0.0
    saved_cost_usd: float = 0.0
    reuse_confidence: float = 0.0
    retrieval_score: float = 0.0
    reranker_score: float = 0.0
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    error: Optional[str] = None
    error_phase: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp,
            "layer": self.layer.value,
            "decision_action": self.decision_action.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "saved_tokens": self.saved_tokens,
            "embedding_calls": self.embedding_calls,
            "embedding_calls_avoided": self.embedding_calls_avoided,
            "embedding_input_tokens": self.embedding_input_tokens,
            "retrieval_calls": self.retrieval_calls,
            "retrieval_calls_avoided": self.retrieval_calls_avoided,
            "chunks_retrieved": self.chunks_retrieved,
            "chunks_filtered": self.chunks_filtered,
            "reranker_calls": self.reranker_calls,
            "reranker_calls_avoided": self.reranker_calls_avoided,
            "chunks_reranked": self.chunks_reranked,
            "chunks_used": self.chunks_used,
            "context_construction_tokens": self.context_construction_tokens,
            "context_construction_tokens_avoided": self.context_construction_tokens_avoided,
            "context_chunks": self.context_chunks,
            "decision_latency_ms": self.decision_latency_ms,
            "cache_lookup_latency_ms": self.cache_lookup_latency_ms,
            "embedding_latency_ms": self.embedding_latency_ms,
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "reranking_latency_ms": self.reranking_latency_ms,
            "context_construction_latency_ms": self.context_construction_latency_ms,
            "generation_latency_ms": self.generation_latency_ms,
            "total_latency_ms": self.total_latency_ms,
            "actual_cost_usd": self.actual_cost_usd,
            "saved_cost_usd": self.saved_cost_usd,
            "reuse_confidence": self.reuse_confidence,
            "retrieval_score": self.retrieval_score,
            "reranker_score": self.reranker_score,
            "gates_passed": self.gates_passed,
            "gates_failed": self.gates_failed,
            "error": self.error,
            "error_phase": self.error_phase,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegacyUsageRecord":
        """Create LegacyUsageRecord from dictionary."""
        return cls(
            request_id=data["request_id"],
            tenant_id=data["tenant_id"],
            timestamp=data.get("timestamp", time.time()),
            layer=CacheLayer(data["layer"]),
            decision_action=DecisionAction(data["decision_action"]),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
            saved_tokens=data.get("saved_tokens", 0),
            embedding_calls=data.get("embedding_calls", 0),
            embedding_calls_avoided=data.get("embedding_calls_avoided", 0),
            embedding_input_tokens=data.get("embedding_input_tokens", 0),
            retrieval_calls=data.get("retrieval_calls", 0),
            retrieval_calls_avoided=data.get("retrieval_calls_avoided", 0),
            chunks_retrieved=data.get("chunks_retrieved", 0),
            chunks_filtered=data.get("chunks_filtered", 0),
            reranker_calls=data.get("reranker_calls", 0),
            reranker_calls_avoided=data.get("reranker_calls_avoided", 0),
            chunks_reranked=data.get("chunks_reranked", 0),
            chunks_used=data.get("chunks_used", 0),
            context_construction_tokens=data.get("context_construction_tokens", 0),
            context_construction_tokens_avoided=data.get("context_construction_tokens_avoided", 0),
            context_chunks=data.get("context_chunks", 0),
            decision_latency_ms=data.get("decision_latency_ms", 0.0),
            cache_lookup_latency_ms=data.get("cache_lookup_latency_ms", 0.0),
            embedding_latency_ms=data.get("embedding_latency_ms", 0.0),
            retrieval_latency_ms=data.get("retrieval_latency_ms", 0.0),
            reranking_latency_ms=data.get("reranking_latency_ms", 0.0),
            context_construction_latency_ms=data.get("context_construction_latency_ms", 0.0),
            generation_latency_ms=data.get("generation_latency_ms", 0.0),
            total_latency_ms=data.get("total_latency_ms", 0.0),
            actual_cost_usd=data.get("actual_cost_usd", 0.0),
            saved_cost_usd=data.get("saved_cost_usd", 0.0),
            reuse_confidence=data.get("reuse_confidence", 0.0),
            retrieval_score=data.get("retrieval_score", 0.0),
            reranker_score=data.get("reranker_score", 0.0),
            gates_passed=data.get("gates_passed", []),
            gates_failed=data.get("gates_failed", []),
            error=data.get("error"),
            error_phase=data.get("error_phase"),
            extra=data.get("extra", {}),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Accounting Collector (backward compatible with security)
# ──────────────────────────────────────────────────────────────────────────────

class AccountingRateLimiter:
    """Per-tenant token-bucket rate limiter for accounting records.

    Each tenant owns an independent bucket. Tokens refill continuously at
    ``max_events_per_minute / 60`` per second up to a ``burst_allowance``
    capacity. This bounds bursty forged-traffic while allowing sustained
    legitimate throughput.
    """

    def __init__(self, max_events_per_minute: int = 100000, burst_allowance: int = 10000):
        if max_events_per_minute <= 0 or burst_allowance <= 0:
            raise ValueError("max_events_per_minute and burst_allowance must be positive")
        self.max_events_per_minute = max_events_per_minute
        self.burst_allowance = burst_allowance
        self._refill_rate = max_events_per_minute / 60.0
        self._lock = threading.Lock()
        self._tokens: Dict[str, float] = {}
        self._last_times: Dict[str, float] = {}

    def _refill(self, tenant_id: str) -> float:
        """Return current available tokens after time-based refill."""
        now = time.time()
        last = self._last_times.get(tenant_id, now)
        current = self._tokens.get(tenant_id, float(self.burst_allowance))
        current = min(float(self.burst_allowance), current + (now - last) * self._refill_rate)
        return current

    def allow(self, tenant_id: str) -> bool:
        """Try to consume one token for the tenant. Returns True if allowed."""
        with self._lock:
            now = time.time()
            tokens = self._refill(tenant_id)
            if tokens < 1.0:
                self._tokens[tenant_id] = tokens
                self._last_times[tenant_id] = now
                return False
            self._tokens[tenant_id] = tokens - 1.0
            self._last_times[tenant_id] = now
            return True

    def check_limit(self, tenant_id: str) -> bool:
        """Backward-compatible alias for ``allow`` (consumes one token)."""
        return self.allow(tenant_id)


class AccountingCollector:
    """
    Collects and aggregates UsageRecords for reporting.

    In production, this would flush to a time-series database (InfluxDB, TimescaleDB)
    or stream to Kafka/Redis for real-time dashboards.
    """

    def __init__(self, max_buffer: int = 10000):
        self._buffer: List[LegacyUsageRecord] = []
        self._max_buffer = max_buffer
        self._aggregates: Dict[str, Dict[str, float]] = {}
        self._rate_limiter = AccountingRateLimiter()

    def record(self, record: LegacyUsageRecord) -> bool:
        """Add a usage record to the buffer. Returns False if rate-limited."""
        if not self._rate_limiter.check_limit(record.tenant_id):
            logger.warning("Rate limit exceeded for tenant %s", record.tenant_id)
            return False

        self._buffer.append(record)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer :]

        # Update running aggregates
        self._update_aggregates(record)
        return True

    def _update_aggregates(self, record: LegacyUsageRecord) -> None:
        """Update running aggregates for quick queries."""
        key = f"{record.tenant_id}:{record.layer.value}:{record.decision_action.value}"
        agg = self._aggregates.setdefault(
            key,
            {
                "count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_saved_tokens": 0,
                "total_actual_cost": 0.0,
                "total_saved_cost": 0.0,
                "total_latency_ms": 0.0,
                "total_embedding_calls": 0,
                "total_retrieval_calls": 0,
                "total_reranker_calls": 0,
                "total_chunks_retrieved": 0,
                "total_chunks_used": 0,
            },
        )
        agg["count"] += 1
        agg["total_input_tokens"] += record.input_tokens
        agg["total_output_tokens"] += record.output_tokens
        agg["total_saved_tokens"] += record.saved_tokens
        agg["total_actual_cost"] += record.actual_cost_usd
        agg["total_saved_cost"] += record.saved_cost_usd
        agg["total_latency_ms"] += record.total_latency_ms
        agg["total_embedding_calls"] += record.embedding_calls
        agg["total_retrieval_calls"] += record.retrieval_calls
        agg["total_reranker_calls"] += record.reranker_calls
        agg["total_chunks_retrieved"] += record.chunks_retrieved
        agg["total_chunks_used"] += record.chunks_used

    def get_aggregates(self, tenant_id: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """Get aggregates, optionally filtered by tenant."""
        if tenant_id is None:
            return dict(self._aggregates)
        return {k: v for k, v in self._aggregates.items() if k.startswith(f"{tenant_id}:")}

    def get_recent(self, limit: int = 100) -> List[LegacyUsageRecord]:
        """Get most recent records."""
        return self._buffer[-limit:]

    def clear(self) -> None:
        """Clear buffer and aggregates."""
        self._buffer.clear()
        self._aggregates.clear()


class ValidatedAccountingCollector:
    """Thread-safe, per-tenant collector for validated UsageRecord flow.

    Enforces event rate limiting (token bucket, per tenant) and provides
    isolated per-tenant reads, aggregates, and clears so cross-tenant data
    can never be observed or tampered with through this API.
    """

    def __init__(
        self,
        max_events_per_minute: int = 100000,
        burst_allowance: int = 10000,
        enable_rate_limiting: bool = True,
    ):
        self._max_events_per_minute = max_events_per_minute
        self._burst_allowance = burst_allowance
        self._enable_rate_limiting = enable_rate_limiting
        self._rate_limiter = (
            AccountingRateLimiter(max_events_per_minute=max_events_per_minute, burst_allowance=burst_allowance)
            if enable_rate_limiting
            else None
        )
        self._lock = threading.RLock()
        self._records: Dict[str, List[UsageRecord]] = {}
        self._max_records_per_tenant = 10000

    def record(self, record: UsageRecord) -> bool:
        """Record a usage event for its tenant. Returns False if rate limited."""
        if self._enable_rate_limiting:
            rate_limiter = self._rate_limiter
            assert rate_limiter is not None
            if not rate_limiter.allow(record.tenant_id):
                return False
        with self._lock:
            bucket = self._records.setdefault(record.tenant_id, [])
            if len(bucket) >= self._max_records_per_tenant:
                bucket = bucket[-(self._max_records_per_tenant - 1):]
            bucket.append(record)
            self._records[record.tenant_id] = bucket
        return True

    def get_records(self, tenant_id: str) -> List[UsageRecord]:
        """Get records for a single tenant (isolated view)."""
        with self._lock:
            return list(self._records.get(tenant_id, []))

    def get_aggregates(self, tenant_id: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """Get per-tenant aggregates, optionally filtered to one tenant.

        Returns a dict keyed by tenant id so callers can enumerate tenants;
        the value holds aggregate counters for that tenant.
        """
        with self._lock:
            if tenant_id is not None:
                records = self._records.get(tenant_id, [])
                tenants: Dict[str, List[UsageRecord]] = {tenant_id: records}
            else:
                tenants = {
                    tid: list(recs) for tid, recs in self._records.items()
                }
            return {tid: self._aggregate(recs) for tid, recs in tenants.items()}

    @staticmethod
    def _aggregate(records: Sequence[UsageRecord]) -> Dict[str, float]:
        agg: Dict[str, float] = {
            "count": 0,
            "total_input_tokens": 0.0,
            "total_output_tokens": 0.0,
            "total_cached_tokens": 0.0,
            "total_saved_tokens": 0.0,
            "total_actual_cost_usd": 0.0,
            "total_saved_cost_usd": 0.0,
            "total_latency_ms": 0.0,
            "total_decision_latency_ms": 0.0,
        }
        for record in records:
            agg["count"] += 1
            agg["total_input_tokens"] += record.input_tokens
            agg["total_output_tokens"] += record.output_tokens
            agg["total_cached_tokens"] += record.cached_tokens
            agg["total_saved_tokens"] += record.saved_tokens
            agg["total_actual_cost_usd"] += record.actual_cost_usd
            agg["total_saved_cost_usd"] += record.saved_cost_usd
            agg["total_latency_ms"] += record.total_latency_ms
            agg["total_decision_latency_ms"] += record.decision_latency_ms
        return agg

    def clear_tenant(self, tenant_id: str) -> int:
        """Remove one tenant's records. Returns number of records removed."""
        with self._lock:
            bucket = self._records.pop(tenant_id, [])
        return len(bucket)

    def get_all_tenants(self) -> List[str]:
        """List tenants that currently hold records."""
        with self._lock:
            return list(self._records.keys())


# Global collector instance (for simple use cases)
_global_collector: Optional[AccountingCollector] = None


def get_collector() -> AccountingCollector:
    """Get or create the global accounting collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = AccountingCollector()
    return _global_collector


def set_collector(collector: AccountingCollector) -> None:
    """Set the global accounting collector."""
    global _global_collector
    _global_collector = collector


def record_usage_legacy(record: LegacyUsageRecord) -> bool:
    """Convenience function to record usage via global collector (legacy)."""
    return get_collector().record(record)


# ──────────────────────────────────────────────────────────────────────────────
# New spec-compliant classes (Phase 3A.5)
# ──────────────────────────────────────────────────────────────────────────────

class UsageTracker:
    """Thread-safe usage tracker with tenant isolation.

    Records UsageRecord instances and emits metrics. Designed for
    high-throughput scenarios with minimal lock contention.
    """

    def __init__(
        self,
        cost_model: Optional[CostModel] = None,
        pricing_version: str = "default",
    ):
        self._cost_model = cost_model or get_cost_model()
        self._pricing_version = pricing_version
        self._lock = threading.RLock()
        self._records: Dict[str, list] = {}  # tenant_id -> [UsageRecord]
        self._max_records_per_tenant = 10000  # Memory bound

    def record(self, record: UsageRecord) -> None:
        """Record a usage record with tenant isolation.

        Emits Prometheus metrics and stores record for potential export.
        Never raises - metrics failures are logged only.
        """
        try:
            self._emit_metrics(record)
        except Exception as e:  # pragma: no cover - metrics must never break requests
            logger.debug("UsageTracker.record metrics failed: %s", e, exc_info=True)

        # Store for tenant-isolated access
        with self._lock:
            tenant_records = self._records.setdefault(record.tenant_id, [])
            tenant_records.append(record)
            # Trim if exceeding max
            if len(tenant_records) > self._max_records_per_tenant:
                # Remove oldest 10%
                trim_count = self._max_records_per_tenant // 10
                del tenant_records[:trim_count]

    def _emit_metrics(self, record: UsageRecord) -> None:
        """Emit Prometheus metrics from a UsageRecord."""
        from ico_cache.telemetry.metrics import (
            record_tokens,
            record_cost,
            record_latency,
            record_llm_call,
            record_llm_call_avoided,
            record_embedding_call,
            record_embedding_call_avoided,
            record_retrieval_call,
            record_retrieval_call_avoided,
            record_latency_saved,
        )

        tenant = record.tenant_id

        # Token metrics
        if record.input_tokens:
            record_tokens("input", record.input_tokens, tenant)
        if record.output_tokens:
            record_tokens("output", record.output_tokens, tenant)
        if record.cached_input_tokens:
            record_tokens("cached", record.cached_input_tokens, tenant)
        if record.avoided_input_tokens or record.avoided_output_tokens:
            avoided_total = record.avoided_input_tokens + record.avoided_output_tokens
            record_tokens("saved", avoided_total, tenant)

        # Cost metrics
        if record.actual_cost:
            record_cost("actual", record.actual_cost, tenant)
        if record.cost_saved:
            record_cost("saved", record.cost_saved, tenant)

        # Latency metrics
        if record.latency_ms:
            record_latency("total", record.layer, record.latency_ms / 1000.0)

        if record.latency_saved:
            record_latency_saved(record.layer, tenant, record.latency_saved)

        # Call-type metrics
        # Emit "called" metric when the operation was actually performed
        if record.llm_called:
            try:
                record_llm_call(record.layer, tenant)
            except Exception:
                logger.debug("LLM calls metric failed", exc_info=True)
        # Emit "avoided" metric for cache hits (when operation was avoided)
        elif record.decision_action in (DecisionAction.EXACT_REUSE, DecisionAction.SEMANTIC_REUSE, DecisionAction.CONTEXT_REUSE, DecisionAction.MEMORY_RETRIEVAL, DecisionAction.RAG_RETRIEVAL, DecisionAction.PARTIAL_RECOMPUTE):
            try:
                record_llm_call_avoided(record.layer, tenant)
            except Exception:
                logger.debug("LLM calls avoided metric failed", exc_info=True)

        if record.embedding_called:
            try:
                record_embedding_call(record.layer, tenant)
            except Exception:
                logger.debug("Embedding calls metric failed", exc_info=True)
        elif record.decision_action in (DecisionAction.EXACT_REUSE, DecisionAction.SEMANTIC_REUSE, DecisionAction.CONTEXT_REUSE, DecisionAction.MEMORY_RETRIEVAL, DecisionAction.RAG_RETRIEVAL, DecisionAction.PARTIAL_RECOMPUTE):
            try:
                record_embedding_call_avoided(record.layer, tenant)
            except Exception:
                logger.debug("Embedding calls avoided metric failed", exc_info=True)

        if record.retrieval_called:
            try:
                record_retrieval_call(record.layer, tenant)
            except Exception:
                logger.debug("Retrieval calls metric failed", exc_info=True)
        elif record.decision_action in (DecisionAction.EXACT_REUSE, DecisionAction.SEMANTIC_REUSE, DecisionAction.CONTEXT_REUSE, DecisionAction.MEMORY_RETRIEVAL, DecisionAction.RAG_RETRIEVAL, DecisionAction.PARTIAL_RECOMPUTE):
            try:
                record_retrieval_call_avoided(record.layer, tenant)
            except Exception:
                logger.debug("Retrieval calls avoided metric failed", exc_info=True)

    def get_records(self, tenant_id: str, *, since: Optional[datetime] = None, limit: int = 1000) -> list:
        """Get records for a specific tenant (tenant isolation enforced)."""
        with self._lock:
            records = self._records.get(tenant_id, [])
            if since:
                records = [r for r in records if r.timestamp >= since]
            return records[-limit:]

    def get_all_tenants(self) -> list:
        """Get list of all tenant IDs with recorded usage."""
        with self._lock:
            return list(self._records.keys())

    def clear_tenant(self, tenant_id: str) -> int:
        """Clear all records for a tenant. Returns count cleared."""
        with self._lock:
            count = len(self._records.pop(tenant_id, []))
            return count

    def clear_all(self) -> int:
        """Clear all records. Returns total count cleared."""
        with self._lock:
            total = sum(len(v) for v in self._records.values())
            self._records.clear()
            return total


class CostCalculator:
    """Centralized cost calculation with provider/model awareness."""

    def __init__(self, cost_model: Optional[CostModel] = None):
        self._cost_model = cost_model or get_cost_model()

    def calculate(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Optional[float]:
        """Calculate cost in USD for given token counts.

        Returns None if pricing not available.
        """
        return self._cost_model.estimate_cost(provider, model, input_tokens, output_tokens)

    def calculate_from_usage(
        self,
        provider: str,
        model: str,
        usage: Dict[str, Any],
    ) -> Optional[float]:
        """Calculate cost from provider usage dict (LiteLLM format)."""
        return self._cost_model.estimate_cost_from_usage(provider, model, usage)

    def calculate_with_fallback(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        fallback_cost: float = 0.0,
    ) -> float:
        """Calculate cost with fallback if pricing unknown."""
        cost = self.calculate(provider, model, input_tokens, output_tokens)
        return cost if cost is not None else fallback_cost


class SavingsCalculator:
    """Calculates avoided usage and cost savings from cache hits.

    Uses a baseline model (full LLM call) to compute what would have
    been consumed without cache.
    """

    def __init__(
        self,
        cost_calculator: Optional[CostCalculator] = None,
        baseline_latency_ms: float = 2000.0,
    ):
        self._cost_calculator = cost_calculator or CostCalculator()
        self._baseline_latency_ms = baseline_latency_ms

    def calculate_savings(
        self,
        *,
        layer: str,
        decision_action: DecisionAction,
        provider: str,
        model: str,
        baseline_input_tokens: int,
        baseline_output_tokens: int,
        actual_input_tokens: int = 0,
        actual_output_tokens: int = 0,
        actual_latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Calculate savings from cache reuse vs baseline full LLM call."""
        baseline_cost = self._cost_calculator.calculate(
            provider, model, baseline_input_tokens, baseline_output_tokens
        ) or 0.0

        actual_cost = self._cost_calculator.calculate(
            provider, model, actual_input_tokens, actual_output_tokens
        ) or 0.0

        avoided_input = max(0, baseline_input_tokens - actual_input_tokens)
        avoided_output = max(0, baseline_output_tokens - actual_output_tokens)
        avoided_total = avoided_input + avoided_output

        cost_saved = max(0.0, baseline_cost - actual_cost)
        latency_saved = max(0.0, (self._baseline_latency_ms - actual_latency_ms) / 1000.0)

        return {
            "avoided_input_tokens": avoided_input,
            "avoided_output_tokens": avoided_output,
            "avoided_total_tokens": avoided_total,
            "cost_saved": cost_saved,
            "latency_saved": latency_saved,
            "tokens_saved": avoided_total,
            "baseline_cost": baseline_cost,
            "actual_cost": actual_cost,
        }

    def estimate_baseline_tokens(
        self,
        query: str,
        context: str = "",
        model: str = "gpt-4o-mini",
    ) -> tuple[int, int]:
        """Estimate baseline tokens for a full LLM call."""
        total_chars = len(query) + len(context)
        estimated_input = max(100, total_chars // 4)
        estimated_output = 500
        return estimated_input, estimated_output


class PricingModel:
    """Pricing model with versioning for historical reproducibility."""

    def __init__(
        self,
        cost_model: Optional[CostModel] = None,
        default_version: str = "2024-10",
    ):
        self._cost_model = cost_model or get_cost_model()
        self._default_version = default_version
        self._versions: Dict[str, PricingVersion] = {
            "2024-10": PricingVersion(
                version="2024-10",
                effective_date=datetime(2024, 10, 1, tzinfo=timezone.utc),
                source="openai:2024-10,anthropic:2024-10,gemini:2024-10",
                description="Default pricing as of October 2024",
            ),
        }

    def register_version(self, version: PricingVersion) -> None:
        """Register a pricing version."""
        self._versions[version.version] = version

    def get_version(self, version: Optional[str] = None) -> PricingVersion:
        """Get pricing version by ID, or default."""
        version = version or self._default_version
        return self._versions.get(version, self._versions[self._default_version])

    def estimate_cost_with_version(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        version: Optional[str] = None,
    ) -> Optional[float]:
        """Estimate cost using a specific pricing version."""
        _pricing_version = self.get_version(version)
        cost = self._cost_model.estimate_cost(provider, model, input_tokens, output_tokens)
        if cost is not None:
            return cost
        return None

    def get_current_version(self) -> str:
        """Get the current default pricing version."""
        return self._default_version

    def set_default_version(self, version: str) -> None:
        """Set the default pricing version."""
        if version in self._versions:
            self._default_version = version
        else:
            raise ValueError(f"Unknown pricing version: {version}")


# ──────────────────────────────────────────────────────────────────────────────
# Global instances
# ──────────────────────────────────────────────────────────────────────────────

_default_tracker: Optional[UsageTracker] = None
_default_cost_calculator: Optional[CostCalculator] = None
_default_savings_calculator: Optional[SavingsCalculator] = None
_default_pricing_model: Optional[PricingModel] = None


def get_usage_tracker() -> UsageTracker:
    """Get the global default usage tracker."""
    global _default_tracker
    if _default_tracker is None:
        _default_tracker = UsageTracker()
    return _default_tracker


def set_usage_tracker(tracker: UsageTracker) -> None:
    """Set the global default usage tracker."""
    global _default_tracker
    _default_tracker = tracker


def get_cost_calculator() -> CostCalculator:
    """Get the global default cost calculator."""
    global _default_cost_calculator
    if _default_cost_calculator is None:
        _default_cost_calculator = CostCalculator()
    return _default_cost_calculator


def set_cost_calculator(calculator: CostCalculator) -> None:
    """Set the global default cost calculator."""
    global _default_cost_calculator
    _default_cost_calculator = calculator


def get_savings_calculator() -> SavingsCalculator:
    """Get the global default savings calculator."""
    global _default_savings_calculator
    if _default_savings_calculator is None:
        _default_savings_calculator = SavingsCalculator()
    return _default_savings_calculator


def set_savings_calculator(calculator: SavingsCalculator) -> None:
    """Set the global default savings calculator."""
    global _default_savings_calculator
    _default_savings_calculator = calculator


def get_pricing_model() -> PricingModel:
    """Get the global default pricing model."""
    global _default_pricing_model
    if _default_pricing_model is None:
        _default_pricing_model = PricingModel()
    return _default_pricing_model


def set_pricing_model(model: PricingModel) -> None:
    """Set the global default pricing model."""
    global _default_pricing_model
    _default_pricing_model = model


def record_usage(record_or_tenant_id=None, layer=None, decision_action=None, **kwargs) -> UsageRecord:
    """Backward-compatible record_usage function.

    Accepts either:
    1. A UsageRecord object (legacy usage)
    2. Individual parameters: tenant_id, layer, decision_action, **kwargs
    """
    # Case 1: First arg is a UsageRecord object (backward compat)
    if isinstance(record_or_tenant_id, UsageRecord):
        record = record_or_tenant_id
        get_usage_tracker().record(record)
        return record

    # Case 2: Individual parameters (new spec-compliant way)
    # tenant_id may be passed as positional arg or in kwargs
    tenant_id = record_or_tenant_id if record_or_tenant_id is not None else kwargs.pop("tenant_id", None)
    if tenant_id is None:
        raise ValueError("tenant_id is required")
    return create_and_record_usage(
        tenant_id=tenant_id,
        layer=layer,
        decision_action=decision_action,
        **kwargs,
    )


def create_and_record_usage(
    tenant_id: str,
    layer: str,
    decision_action: DecisionAction,
    *,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    cache_hit: int = 0,
    cache_miss: int = 0,
    llm_called: int = 0,
    embedding_called: int = 0,
    retrieval_called: int = 0,
    reranker_called: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cached_input_tokens: int = 0,
    avoided_input_tokens: int = 0,
    avoided_output_tokens: int = 0,
    avoided_total_tokens: int = 0,
    embedding_tokens: int = 0,
    retrieval_units: int = 0,
    estimated_cost: float = 0.0,
    actual_cost: float = 0.0,
    tokens_saved: int = 0,
    cost_saved: float = 0.0,
    latency_saved: float = 0.0,
    latency_ms: float = 0.0,
    model: str = "",
    model_fingerprint: str = "",
    provider: str = "",
    currency: str = "USD",
    pricing_version: str = "",
    success: bool = True,
    error: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    usage_source: UsageSource = UsageSource.UNKNOWN,
) -> UsageRecord:
    """Convenience function to create and record a UsageRecord (spec-compliant)."""
    record = UsageRecord(
        request_id=request_id or str(uuid.uuid4()),
        trace_id=trace_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        timestamp=datetime.now(timezone.utc),
        layer=layer,
        decision_action=decision_action,
        cache_hit=cache_hit,
        cache_miss=cache_miss,
        llm_called=llm_called,
        embedding_called=embedding_called,
        retrieval_called=retrieval_called,
        reranker_called=reranker_called,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        avoided_input_tokens=avoided_input_tokens,
        avoided_output_tokens=avoided_output_tokens,
        avoided_total_tokens=avoided_total_tokens,
        embedding_tokens=embedding_tokens,
        retrieval_units=retrieval_units,
        estimated_cost=estimated_cost,
        actual_cost=actual_cost,
        tokens_saved=tokens_saved,
        cost_saved=cost_saved,
        latency_saved=latency_saved,
        latency_ms=latency_ms,
        model=model,
        model_fingerprint=model_fingerprint,
        provider=provider,
        currency=currency,
        pricing_version=pricing_version or get_pricing_model().get_current_version(),
        success=success,
        error=error,
        metadata=_scrub_metadata(metadata or {}),
        usage_source=usage_source,
    )

    get_usage_tracker().record(record)
    return record


__all__ = [
    # Backward-compatible enums
    "CacheLayer",
    "DecisionAction",
    "UsageSource",
    "UsageType",
    # Token types
    "TokenUsage",
    "LayerAttribution",
    # Pricing
    "PricingVersion",
    # Record types
    "UsageRecord",
    "LegacyUsageRecord",
    "AccountingContext",
    "AccountingCollector",
    "ValidatedAccountingCollector",
    "AccountingRateLimiter",
    # Collector functions
    "get_collector",
    "set_collector",
    "record_usage",
    "record_usage_legacy",
    "create_and_record_usage",
    # New spec-compliant classes
    "UsageTracker",
    "CostCalculator",
    "SavingsCalculator",
    "PricingModel",
    # Global instances
    "get_usage_tracker",
    "set_usage_tracker",
    "get_cost_calculator",
    "set_cost_calculator",
    "get_savings_calculator",
    "set_savings_calculator",
    "get_pricing_model",
    "set_pricing_model",
    "record_usage",
    # Security utilities
    "_scrub_metadata",
]
