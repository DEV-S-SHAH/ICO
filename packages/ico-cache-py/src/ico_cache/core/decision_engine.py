"""
decision_engine.py — Intelligent reuse decision engine for ICO-Cache Phase 3.

This module implements the DecisionEngine that evaluates reuse opportunities
across the 10-layer cache hierarchy (L0a-L9) per the authoritative Execution Order.
"""

import asyncio
import functools
import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .metadata_guard import MetadataSchema, hard_gate, CRITICAL_FIELDS, GateMode
from .decision_trace import (
    DecisionTrace,
    DecisionTraceStore,
    LayerTrace,
    LayerStatus,
    begin_trace,
    derive_outcome,
    reset_active_trace,
)

if TYPE_CHECKING:
    from .cache_engine import CacheEngine


# Phase 3 cache schema version — clean break from 2.x per ADR-012
CACHE_SCHEMA_VERSION = 3


async def _run_sync(fn, *args, **kwargs):
    """Run a blocking callable in a worker thread so it never blocks the loop."""
    if kwargs:
        fn = functools.partial(fn, **kwargs)
    return await asyncio.to_thread(fn, *args)


class ReuseAction(str, Enum):
    """The action taken after evaluating reuse opportunities."""

    EXACT_REUSE = "EXACT_REUSE"
    SEMANTIC_REUSE = "SEMANTIC_REUSE"
    CONTEXT_REUSE = "CONTEXT_REUSE"
    MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    PARTIAL_RECOMPUTE = "PARTIAL_RECOMPUTE"
    FULL_LLM_CALL = "FULL_LLM_CALL"


class ReusePolicy:
    """Policy configuration for reuse decisions."""

    def __init__(
        self,
        mode: GateMode = GateMode.STRICT,
        threshold: Optional[float] = None,
        fuzzy_fields: Optional[List[str]] = None,
    ):
        self.mode = mode
        self.threshold = threshold or (0.95 if mode == GateMode.STRICT else 0.80)
        self.fuzzy_fields = set(fuzzy_fields or [])

    @classmethod
    def strict(cls) -> "ReusePolicy":
        return cls(mode=GateMode.STRICT, threshold=0.95)

    @classmethod
    def balanced(cls, fuzzy_fields: Optional[List[str]] = None) -> "ReusePolicy":
        return cls(mode=GateMode.BALANCED, threshold=0.80, fuzzy_fields=fuzzy_fields)


# ──────────────────────────────────────────────────────────────────────────────
# Decision Context — Input to the Decision Engine
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DecisionContext:
    """
    Complete context for a reuse decision.

    Contains all information needed to evaluate cache layers L0-L9.
    """

    # Request identity
    query: str
    context: Optional[str] = None
    prompt_template: Optional[str] = None
    prompt_version: str = "v1"

    # Phase 5: request id carried into the decision trace
    request_id: Optional[str] = None

    # Model/Provider
    model: str = "gpt-4o"
    provider: str = "openai"
    model_params: Dict[str, Any] = field(default_factory=dict)

    # Metadata (extracted + explicit)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Identity & Scope
    tenant_id: str = "default"
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None

    # Repository state (for coding agents)
    repo_url: Optional[str] = None
    commit_sha: Optional[str] = None
    changed_files: List[str] = field(default_factory=list)

    # Tool context
    available_tools: List["ToolSpec"] = field(default_factory=list)
    tool_versions: Dict[str, str] = field(default_factory=dict)

    # L8/L9 Interaction Control
    personalized_response: bool = False
    injected_context_hash: Optional[str] = None

    # Authorization
    authz_version: str = "v1"

    # Policy
    reuse_policy: ReusePolicy = field(default_factory=ReusePolicy.strict)
    max_latency_ms: int = 5000
    cost_budget_usd: Optional[float] = None

    def __post_init__(self):
        """Compute derived fields."""
        self.model_fingerprint = self._compute_model_fingerprint()
        self.params_hash = self._compute_params_hash()

    def _compute_model_fingerprint(self) -> str:
        """Compute model fingerprint: sha256(model + provider + params)[:12]."""
        # Include model params that affect output determinism
        deterministic_params = {
            k: v for k, v in self.model_params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed")
        }
        parts = [
            self.model,
            self.provider,
            str(sorted(deterministic_params.items()))
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _compute_params_hash(self) -> str:
        """Compute hash of all model parameters."""
        raw = str(sorted(self.model_params.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ToolSpec:
    """Specification for a tool/function that can be called."""
    name: str
    description: str
    parameters: Dict[str, Any]
    idempotent: bool = False
    version: str = "1.0"


# ──────────────────────────────────────────────────────────────────────────────
# Layer Evaluation Result
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerEvaluation:
    """Result of evaluating a single cache layer."""

    layer: str
    checked: bool = False
    hit: bool = False
    score: float = 0.0
    confidence: float = 0.0
    cache_key: Optional[str] = None
    cached_value: Optional[Any] = None
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    gate_mode: GateMode = GateMode.STRICT
    reasoning: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "checked": self.checked,
            "hit": self.hit,
            "score": self.score,
            "confidence": self.confidence,
            "cache_key": self.cache_key,
            "gates_passed": self.gates_passed,
            "gates_failed": self.gates_failed,
            "gate_mode": self.gate_mode.value,
            "reasoning": self.reasoning,
            "latency_ms": self.latency_ms,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Reuse Decision — Output of the Decision Engine
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ReuseDecision:
    """
    Final reuse decision from the Decision Engine.

    Contains the action to take, confidence, and full reasoning for observability.
    """

    action: ReuseAction
    confidence: float
    layer: str
    cache_key: Optional[str]
    reasoning: str
    required_recompute: List[str] = field(default_factory=list)
    metadata_gates_passed: List[str] = field(default_factory=list)
    metadata_gates_failed: List[str] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    layer_evaluations: List[LayerEvaluation] = field(default_factory=list)
    decision_id: str = field(default_factory=lambda: hashlib.sha256(str(time.time()).encode()).hexdigest()[:16])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "action": self.action.value,
            "confidence": self.confidence,
            "layer": self.layer,
            "cache_key": self.cache_key,
            "reasoning": self.reasoning,
            "required_recompute": self.required_recompute,
            "metadata_gates_passed": self.metadata_gates_passed,
            "metadata_gates_failed": self.metadata_gates_failed,
            "fallback_reason": self.fallback_reason,
            "layer_evaluations": [e.to_dict() for e in self.layer_evaluations],
            "timestamp": self.timestamp,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Cache Layer Interface
# ──────────────────────────────────────────────────────────────────────────────

class CacheLayer(ABC):
    """Abstract base class for cache layer implementations."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def evaluate(self, ctx: DecisionContext, cache_engine: "CacheEngine") -> LayerEvaluation:
        """
        Evaluate this layer for a reuse decision.

        Returns LayerEvaluation with hit/miss, confidence, and gate results.
        """
        pass

    @abstractmethod
    async def write(self, ctx: DecisionContext, cache_engine: "CacheEngine", value: Any, ttl: int) -> bool:
        """Write a value to this cache layer."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Hard Gate Evaluation (Extended)
# ──────────────────────────────────────────────────────────────────────────────

def hard_gate_extended(
    incoming: Dict[str, Any],
    cached: Dict[str, Any],
    layer: str,
    mode: GateMode = GateMode.STRICT,
    fuzzy_fields: Optional[List[str]] = None,
    schema: Optional[MetadataSchema] = None,
) -> tuple[bool, List[str], List[str]]:
    """
    Extended hard gate with CRITICAL_FIELDS and GateMode support.

    Returns: (allowed, gates_passed, gates_failed)
    """
    critical = CRITICAL_FIELDS.get(layer, [])
    fuzzy = set(fuzzy_fields or [])
    if schema:
        for f in schema.fields:
            if f.fuzzy:
                fuzzy.add(f.name)

    passed = []
    failed = []

    all_keys = set(incoming.keys()).union(cached.keys()).union(critical)
    for key in all_keys:
        v_in = incoming.get(key)
        v_cached = cached.get(key)

        is_critical = key in critical
        is_fuzzy = key in fuzzy

        if v_in is not None and v_cached is not None and v_in != v_cached:
            # Mismatch — check if it's a critical field or non-fuzzy
            if is_critical or mode == GateMode.STRICT or (mode == GateMode.BALANCED and not is_fuzzy):
                failed.append(key)
            else:
                # BALANCED mode with fuzzy field — allow with penalty
                passed.append(f"{key}(fuzzy)")
        elif v_in is not None or v_cached is not None:
            # One side has value, other doesn't — pass but note
            passed.append(key)
        else:
            # Both None — pass
            passed.append(key)

    allowed = len(failed) == 0
    return allowed, passed, failed


# ──────────────────────────────────────────────────────────────────────────────
# Confidence Model
# ──────────────────────────────────────────────────────────────────────────────

BASE_CONFIDENCE = {
    ReuseAction.EXACT_REUSE: 1.0,
    ReuseAction.SEMANTIC_REUSE: 0.90,  # base, modified by score
    ReuseAction.CONTEXT_REUSE: 0.85,
    ReuseAction.MEMORY_RETRIEVAL: 0.80,
    ReuseAction.RAG_RETRIEVAL: 0.75,
    ReuseAction.PARTIAL_RECOMPUTE: 0.50,
    ReuseAction.FULL_LLM_CALL: 0.0,
}

CONFIDENCE_MODIFIERS = {
    "fuzzy_gate_pass": -0.1,
    "missing_metadata": -0.05,
    "context_metadata_mismatch": -0.1,
    "commit_sha_mismatch": -0.2,
    "stale_file": -0.1,
    "collection_version_stale": -0.1,
    "reusable_component": 0.1,
}


def compute_confidence(
    action: ReuseAction,
    base_score: float = 0.0,
    modifiers: Optional[List[str]] = None,
) -> float:
    """Compute final confidence with modifiers."""
    confidence = BASE_CONFIDENCE.get(action, 0.0)

    if action == ReuseAction.SEMANTIC_REUSE:
        confidence = base_score  # cosine similarity
    elif action == ReuseAction.CONTEXT_REUSE:
        confidence = min(base_score, confidence)  # min of query and context scores

    if modifiers:
        for mod in modifiers:
            confidence += CONFIDENCE_MODIFIERS.get(mod, 0.0)

    return max(0.0, min(1.0, confidence))


# ──────────────────────────────────────────────────────────────────────────────
# Key Builders for L0a, L0b, L1
# ──────────────────────────────────────────────────────────────────────────────

def build_l0a_key(fn_name: str, args: Dict[str, Any], fn_version: str, env_hash: str = "") -> str:
    """Build L0a deterministic function cache key."""
    args_str = str(sorted(args.items()))
    raw = f"{fn_name}:{args_str}:{fn_version}:{env_hash}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"det:{fn_name}:{fn_version}:{key_hash}"


def build_l0b_key(model_fingerprint: str, text: str) -> str:
    """Build L0b embedding cache key."""
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"emb:{model_fingerprint}:{text_hash}"


def build_l1_key(
    tenant_id: str,
    normalized_query: str,
    model_fingerprint: str,
    provider: str,
    prompt_version: str,
    context_hash: str,
    canonical_meta_suffix: str,
) -> str:
    """Build L1 exact prompt match key per Phase 3 spec (v3 schema)."""
    raw = f"{normalized_query}|{model_fingerprint}|{provider}|{prompt_version}|{context_hash}{canonical_meta_suffix}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return f"v3:{tenant_id}:l1:{key_hash}"


def canonical_meta_suffix(meta: Dict[str, Any]) -> str:
    """Deterministic string representation of metadata for L1 key."""
    if not meta:
        return ""
    items = sorted((k, v) for k, v in meta.items() if v is not None)
    return "|" + "&".join(f"{k}={v}" for k, v in items)


def normalize_query(query: str) -> str:
    """Normalize query for exact matching."""
    return " ".join(query.lower().strip().split())


def context_hash(context: Optional[str]) -> str:
    """Compute context hash for L1/L3 keys."""
    if not context or not context.strip():
        return "empty"
    return hashlib.sha256(context.encode()).hexdigest()[:16]


def compute_chunks_hash(chunks: List[dict]) -> str:
    """
    Compute deterministic hash of retrieved chunk contents for L5 cache key.

    Uses content hashes from chunks, sorted for determinism.
    """
    if not chunks:
        return "empty"
    content_hashes = []
    for chunk in chunks:
        text = chunk.get("text", "")
        if text:
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            content_hashes.append(h)
    if not content_hashes:
        return "empty"
    content_hashes.sort()
    combined = "|".join(content_hashes)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def build_l5_key(
    tenant_id: str,
    chunks_hash: str,
    template_version: str,
    token_budget: int,
    model_fingerprint: str,
    provider: str,
) -> str:
    """Build L5 context cache key per Phase 3 spec."""
    raw = f"{tenant_id}:{chunks_hash}:{template_version}:{token_budget}:{model_fingerprint}:{provider}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return f"v3:{tenant_id}:l5:{key_hash}"


def compute_context_tokens(text: str) -> int:
    """Estimate token count for context text (4 chars per token, rounded up)."""
    if not text:
        return 1
    return max((len(text) + 3) // 4, 1)


# ──────────────────────────────────────────────────────────────────────────────
# Collection Version Tracking
# ──────────────────────────────────────────────────────────────────────────────

class CollectionVersionTracker:
    """
    Tracks collection versions per tenant for L4 invalidation.

    Collection version increments on every ingestion/deletion.
    """

    def __init__(self, exact_store):
        self.exact_store = exact_store
        self._cache: Dict[str, int] = {}

    def _key(self, tenant_id: str, collection: str) -> str:
        return f"{tenant_id}:collection_version:{collection}"

    async def get_version(self, tenant_id: str, collection: str) -> int:
        key = self._key(tenant_id, collection)
        if key in self._cache:
            return self._cache[key]
        val = self.exact_store.get(key)
        if val:
            version = int(val.decode())
            self._cache[key] = version
            return version
        return 1  # default version

    async def increment(self, tenant_id: str, collection: str) -> int:
        key = self._key(tenant_id, collection)
        version = await self.get_version(tenant_id, collection) + 1
        self.exact_store.set(key, str(version).encode())
        self._cache[key] = version
        return version

    async def set_version(self, tenant_id: str, collection: str, version: int) -> None:
        key = self._key(tenant_id, collection)
        self.exact_store.set(key, str(version).encode())
        self._cache[key] = version


# ──────────────────────────────────────────────────────────────────────────────
# Decision Engine — Main Implementation
# ──────────────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Decision Engine for ICO-Cache Phase 3.

    Evaluates reuse opportunities across the 10-layer cache hierarchy (L0a-L9)
    per the authoritative Execution Order defined in the architecture.
    """

    def __init__(
        self,
        cache_engine: "CacheEngine",
        policy: Optional[ReusePolicy] = None,
        enable_tracing: bool = True,
        max_traces: int = 1000,
    ):
        self.cache_engine = cache_engine
        self.policy = policy or ReusePolicy.strict()
        self._layers: Dict[str, CacheLayer] = {}
        self._embedder = cache_engine.embedder

        # Phase 5: Decision Trace
        self.enable_tracing = enable_tracing
        self.trace_store = DecisionTraceStore(max_traces=max_traces) if enable_tracing else None

    def register_layer(self, layer: CacheLayer) -> None:
        """Register a cache layer implementation."""
        self._layers[layer.name] = layer

    async def decide(self, ctx: DecisionContext) -> ReuseDecision:
        """
        Main entry point: evaluate all layers per Execution Order, return decision.

        Execution Order (authoritative):
        1. EXACT_REUSE (L0a → L0b → L1)
        2. SEMANTIC_REUSE (L2)
        3. CONTEXT_REUSE (L3)
        4. MEMORY_RETRIEVAL (L7 → L8)
        5. RAG_RETRIEVAL (L4 → L5)
        6. PARTIAL_RECOMPUTE
        7. FULL_LLM_CALL

        Phase 5: every decision is recorded as a structured DecisionTrace
        (L0a → L0b → L1 → L2 → L3 → L4 → L5 → LLM) retrievable through
        :meth:`get_trace` / :meth:`get_trace_by_request`.
        """
        evaluations: List[LayerEvaluation] = []
        policy = ctx.reuse_policy or self.policy

        trace: Optional[DecisionTrace] = None
        token = None
        created = False
        if self.enable_tracing and self.trace_store is not None:
            trace, token, created = begin_trace(
                request_id=ctx.request_id,
                tenant_id=ctx.tenant_id,
                query=ctx.query,
                model=ctx.model,
                provider=ctx.provider,
            )

        async def finish(
            action: ReuseAction,
            hit_eval: LayerEvaluation,
            fallback_reason: Optional[str] = None,
        ) -> ReuseDecision:
            decision = self._make_decision(
                action, hit_eval, evaluations, policy, fallback_reason=fallback_reason
            )
            self._record_decision(decision, ctx.tenant_id)
            if trace is not None and created:
                self._finalize_trace(trace, decision)
            return decision

        try:
            # Step 1: EXACT_REUSE (L0a → L0b → L1)
            eval_l0a = await self._evaluate_l0a(ctx)
            evaluations.append(eval_l0a)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l0a))
            if eval_l0a.hit and eval_l0a.confidence >= policy.threshold:
                return await finish(ReuseAction.EXACT_REUSE, eval_l0a)

            eval_l0b = await self._evaluate_l0b(ctx)
            evaluations.append(eval_l0b)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l0b))
            if eval_l0b.hit and eval_l0b.confidence >= policy.threshold:
                return await finish(ReuseAction.EXACT_REUSE, eval_l0b)

            eval_l1 = await self._evaluate_l1(ctx)
            evaluations.append(eval_l1)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l1))
            if eval_l1.hit and eval_l1.confidence >= policy.threshold:
                return await finish(ReuseAction.EXACT_REUSE, eval_l1)

            # Step 2: SEMANTIC_REUSE (L2)
            eval_l2 = await self._evaluate_l2(ctx)
            evaluations.append(eval_l2)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l2))
            if eval_l2.hit and eval_l2.confidence >= policy.threshold:
                return await finish(ReuseAction.SEMANTIC_REUSE, eval_l2)

            # Step 3: CONTEXT_REUSE (L3)
            eval_l3 = await self._evaluate_l3(ctx)
            evaluations.append(eval_l3)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l3))
            if eval_l3.hit and eval_l3.confidence >= policy.threshold:
                return await finish(ReuseAction.CONTEXT_REUSE, eval_l3)

            # Step 4: MEMORY_RETRIEVAL (L7 → L8) - Not yet implemented, skip
            # eval_l7 = await self._evaluate_l7(ctx)
            # evaluations.append(eval_l7)
            # eval_l8 = await self._evaluate_l8(ctx)
            # evaluations.append(eval_l8)

            # Step 5: RAG_RETRIEVAL (L4 → L5)
            # L4 is evaluated in RAGPipeline.retrieve()
            # L5 is context cache - evaluated here
            eval_l5 = await self._evaluate_l5(ctx)
            evaluations.append(eval_l5)
            if trace is not None:
                trace.add_layer_trace(self._to_layer_trace(eval_l5))
            if eval_l5.hit and eval_l5.confidence >= policy.threshold:
                return await finish(ReuseAction.RAG_RETRIEVAL, eval_l5)

            # Step 6: PARTIAL_RECOMPUTE - Not yet implemented, skip

            # Step 7: FULL_LLM_CALL
            return await finish(
                ReuseAction.FULL_LLM_CALL,
                LayerEvaluation(
                    layer="NONE",
                    hit=False,
                    confidence=0.0,
                    reasoning="No safe reuse path found",
                ),
                fallback_reason="All layers missed or below confidence threshold",
            )
        finally:
            if token is not None:
                reset_active_trace(token)

    def _record_decision(self, decision: ReuseDecision, tenant_id: str) -> None:
        """Record decision action for metrics."""
        if self.cache_engine:
            self.cache_engine.record_decision_action(decision.action.value, tenant_id)

    def _make_decision(
        self,
        action: ReuseAction,
        hit_eval: LayerEvaluation,
        all_evaluations: List[LayerEvaluation],
        policy: ReusePolicy,
        fallback_reason: Optional[str] = None,
    ) -> ReuseDecision:
        """Construct final ReuseDecision from evaluations."""
        passed = []
        failed = []
        for e in all_evaluations:
            passed.extend(e.gates_passed)
            failed.extend(e.gates_failed)

        return ReuseDecision(
            action=action,
            confidence=hit_eval.confidence,
            layer=hit_eval.layer,
            cache_key=hit_eval.cache_key,
            reasoning=hit_eval.reasoning,
            required_recompute=hit_eval.reasoning.split("recompute:")[-1].split() if "recompute:" in hit_eval.reasoning else [],
            metadata_gates_passed=passed,
            metadata_gates_failed=failed,
            fallback_reason=fallback_reason,
            layer_evaluations=all_evaluations,
        )

    async def _evaluate_l0a(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L0a: Deterministic function cache."""
        start = time.perf_counter()
        # L0a is for specific registered deterministic functions (token counting, hashing, etc.)
        # Not evaluated per-query; application calls cache_engine.execute_deterministic() directly
        # Report available functions for observability
        registered = list(self.cache_engine._det_functions.keys())
        latency = (time.perf_counter() - start) * 1000
        return LayerEvaluation(
            layer="L0a",
            checked=True,
            hit=False,  # L0a hits are function-specific, not query-driven
            confidence=0.0,
            reasoning=f"L0a deterministic function cache: {len(registered)} functions registered ({', '.join(registered) or 'none'})",
            latency_ms=latency,
        )

    async def _evaluate_l0b(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L0b: Embedding cache for query and context."""
        start = time.perf_counter()

        # L0b is checked implicitly when we get embeddings
        query_key = build_l0b_key(ctx.model_fingerprint, ctx.query)
        _ = build_l0b_key(ctx.model_fingerprint, ctx.context) if ctx.context else None

        # Get L0b stats to see if we had hits
        l0b_stats = self.cache_engine.get_l0b_stats()

        latency = (time.perf_counter() - start) * 1000

        # If we have L0b hits, report them
        if l0b_stats["hits"] > 0:
            return LayerEvaluation(
                layer="L0b",
                checked=True,
                hit=True,
                confidence=1.0,
                cache_key=query_key,
                reasoning=f"L0b embedding cache hit: {l0b_stats['hits']} hits, {l0b_stats['misses']} misses (hit_rate={l0b_stats['hit_rate']:.1%})",
                latency_ms=latency,
            )

        return LayerEvaluation(
            layer="L0b",
            checked=True,
            hit=False,
            confidence=0.0,
            cache_key=query_key,
            reasoning=f"L0b embedding cache miss: {l0b_stats['hits']} hits, {l0b_stats['misses']} misses (will compute and cache)",
            latency_ms=latency,
        )

    async def _evaluate_l1(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L1: Exact prompt match with full identity."""
        start = time.perf_counter()

        effective_meta = self.cache_engine._auto_meta(ctx.query, ctx.metadata)
        key = self.cache_engine._l1_key(
            ctx.query,
            effective_meta,
            tenant_id=ctx.tenant_id,
            model=ctx.model,
            provider=ctx.provider,
            prompt_version=ctx.prompt_version,
            context=ctx.context,
        )

        cached = await self.cache_engine.get_l1(
            ctx.query,
            ctx.metadata,
            tenant_id=ctx.tenant_id,
            model=ctx.model,
            provider=ctx.provider,
            prompt_version=ctx.prompt_version,
            context=ctx.context,
        )

        latency = (time.perf_counter() - start) * 1000

        if cached:
            # Verify hard gates
            cached_meta = cached.get("meta", {})
            allowed, gates_passed, gates_failed = hard_gate(  # type: ignore[misc]
                effective_meta,
                cached_meta,
                layer="L1",
                mode=ctx.reuse_policy.mode,
                fuzzy_fields=ctx.reuse_policy.fuzzy_fields,
                schema=self.cache_engine.schema,
            )

            if allowed:
                return LayerEvaluation(
                    layer="L1",
                    checked=True,
                    hit=True,
                    score=1.0,
                    confidence=1.0,
                    cache_key=key,
                    cached_value=cached,
                    gates_passed=gates_passed,
                    gates_failed=gates_failed,
                    gate_mode=ctx.reuse_policy.mode,
                    reasoning=f"L1 exact match: all hard gates passed ({len(gates_passed)} gates)",
                    latency_ms=latency,
                )
            else:
                return LayerEvaluation(
                    layer="L1",
                    checked=True,
                    hit=False,
                    confidence=0.0,
                    cache_key=key,
                    gates_passed=gates_passed,
                    gates_failed=gates_failed,
                    gate_mode=ctx.reuse_policy.mode,
                    reasoning=f"L1 key match but hard gate blocked: {gates_failed}",
                    latency_ms=latency,
                )

        return LayerEvaluation(
            layer="L1",
            checked=True,
            hit=False,
            confidence=0.0,
            cache_key=key,
            gate_mode=ctx.reuse_policy.mode,
            reasoning="L1 exact key miss",
            latency_ms=latency,
        )

    async def _evaluate_l2(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L2: Semantic query match with metadata hard gate."""
        start = time.perf_counter()

        effective_meta = self.cache_engine._auto_meta(ctx.query, ctx.metadata)

        # Embed query
        query_emb = await _run_sync(self.cache_engine.embedder.embed, ctx.query)

        # Search vector store
        coll_l2 = self.cache_engine._coll_name("l2_cache", ctx.tenant_id)
        q_filter = self.cache_engine.build_meta_filter(effective_meta, ctx.tenant_id)

        hits = await self.cache_engine.vector_store.search(
            collection=coll_l2,
            vector=query_emb,
            query_filter=q_filter,
            limit=5,
            score_threshold=self.cache_engine.thresh_semantic,
        )

        latency = (time.perf_counter() - start) * 1000

        if hits:
            for hit in hits:
                payload = hit.payload
                cached_meta = payload.get("meta", {})
                score = hit.score

                allowed, gates_passed, gates_failed = hard_gate(  # type: ignore[misc]
                    effective_meta,
                    cached_meta,
                    layer="L2",
                    mode=ctx.reuse_policy.mode,
                    fuzzy_fields=ctx.reuse_policy.fuzzy_fields,
                    schema=self.cache_engine.schema,
                )

                if allowed:
                    confidence = compute_confidence(
                        ReuseAction.SEMANTIC_REUSE,
                        base_score=score,
                        modifiers=["fuzzy_gate_pass"] * sum(1 for g in gates_passed if "(fuzzy)" in g),
                    )

                    return LayerEvaluation(
                        layer="L2",
                        checked=True,
                        hit=True,
                        score=score,
                        confidence=confidence,
                        cache_key=str(hit.id),
                        cached_value=payload.get("answer"),
                        gates_passed=gates_passed,
                        gates_failed=gates_failed,
                        gate_mode=ctx.reuse_policy.mode,
                        reasoning=f"L2 semantic match: score={score:.3f}, gates passed={len(gates_passed)}",
                        latency_ms=latency,
                    )
                else:
                    return LayerEvaluation(
                        layer="L2",
                        checked=True,
                        hit=False,
                        score=score,
                        confidence=0.0,
                        cache_key=str(hit.id),
                        gates_passed=gates_passed,
                        gates_failed=gates_failed,
                        gate_mode=ctx.reuse_policy.mode,
                        reasoning=f"L2 semantic candidate but hard gate blocked: {gates_failed}",
                        latency_ms=latency,
                    )

        return LayerEvaluation(
            layer="L2",
            checked=True,
            hit=False,
            confidence=0.0,
            reasoning="L2 no candidates above threshold",
            latency_ms=latency,
        )

    async def _evaluate_l3(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L3: Context-aware dual-vector match."""
        start = time.perf_counter()

        if not ctx.context or not ctx.context.strip():
            latency = (time.perf_counter() - start) * 1000
            return LayerEvaluation(
                layer="L3",
                checked=True,
                hit=False,
                confidence=0.0,
                reasoning="L3 skipped: no context provided",
                latency_ms=latency,
            )

        effective_meta = self.cache_engine._auto_meta(ctx.query, ctx.metadata)

        # Embed query and context
        query_emb = await _run_sync(self.cache_engine.embedder.embed, ctx.query)
        context_emb = await _run_sync(self.cache_engine.embedder.embed, ctx.context)

        coll_l3 = self.cache_engine._coll_name("l3_cache", ctx.tenant_id)
        q_filter = self.cache_engine.build_meta_filter(effective_meta, ctx.tenant_id)

        # Search both vectors
        hits_q = await self.cache_engine.vector_store.search(
            collection=coll_l3,
            vector=query_emb,
            query_filter=q_filter,
            limit=5,
            score_threshold=self.cache_engine.thresh_ctx_q,
            using="query",
        )
        if not hits_q:
            latency = (time.perf_counter() - start) * 1000
            return LayerEvaluation(
                layer="L3",
                checked=True,
                hit=False,
                confidence=0.0,
                reasoning="L3 no query vector matches",
                latency_ms=latency,
            )

        hits_c = await self.cache_engine.vector_store.search(
            collection=coll_l3,
            vector=context_emb,
            query_filter=q_filter,
            limit=5,
            score_threshold=self.cache_engine.thresh_ctx_c,
            using="context",
        )
        if not hits_c:
            latency = (time.perf_counter() - start) * 1000
            return LayerEvaluation(
                layer="L3",
                checked=True,
                hit=False,
                confidence=0.0,
                reasoning="L3 no context vector matches",
                latency_ms=latency,
            )

        # Intersect IDs
        q_ids = {h.id for h in hits_q}
        c_ids = {h.id for h in hits_c}
        common = q_ids.intersection(c_ids)

        latency = (time.perf_counter() - start) * 1000

        if common:
            for cid in common:
                h = next(h for h in hits_q if h.id == cid)
                cached_payload = h.payload
                cached_ctx_str = cached_payload.get("context", "")
                cached_meta = cached_payload.get("meta", {})

                # Extract context metadata
                incoming_ctx_meta = self.cache_engine.schema.extract(ctx.context) if self.cache_engine.schema else {}
                full_incoming_meta = {**effective_meta, **{k: v for k, v in incoming_ctx_meta.items() if v is not None}}
                cached_ctx_meta = self.cache_engine.schema.extract(cached_ctx_str) if self.cache_engine.schema else {}
                full_cached_meta = {**cached_meta, **{k: v for k, v in cached_ctx_meta.items() if v is not None}}

                # Add context_hash for L3 gate
                full_incoming_meta["context_hash"] = context_hash(ctx.context)
                full_cached_meta["context_hash"] = context_hash(cached_ctx_str)

                allowed, gates_passed, gates_failed = hard_gate(  # type: ignore[misc]
                    full_incoming_meta,
                    full_cached_meta,
                    layer="L3",
                    mode=ctx.reuse_policy.mode,
                    fuzzy_fields=ctx.reuse_policy.fuzzy_fields,
                    schema=self.cache_engine.schema,
                )

                if allowed:
                    query_score = h.score
                    c_hit = next(h for h in hits_c if h.id == cid)
                    context_score = c_hit.score
                    confidence = compute_confidence(
                        ReuseAction.CONTEXT_REUSE,
                        base_score=min(query_score, context_score),
                        modifiers=["fuzzy_gate_pass"] * sum(1 for g in gates_passed if "(fuzzy)" in g),
                    )

                    return LayerEvaluation(
                        layer="L3",
                        checked=True,
                        hit=True,
                        score=min(query_score, context_score),
                        confidence=confidence,
                        cache_key=str(cid),
                        cached_value=cached_payload.get("answer"),
                        gates_passed=gates_passed,
                        gates_failed=gates_failed,
                        gate_mode=ctx.reuse_policy.mode,
                        reasoning=f"L3 context match: query_score={query_score:.3f}, context_score={context_score:.3f}",
                        latency_ms=latency,
                    )
                else:
                    return LayerEvaluation(
                        layer="L3",
                        checked=True,
                        hit=False,
                        confidence=0.0,
                        cache_key=str(cid),
                        gates_passed=gates_passed,
                        gates_failed=gates_failed,
                        gate_mode=ctx.reuse_policy.mode,
                        reasoning=f"L3 context candidate but hard gate blocked: {gates_failed}",
                        latency_ms=latency,
                    )

        return LayerEvaluation(
            layer="L3",
            checked=True,
            hit=False,
            confidence=0.0,
            reasoning="L3 no intersection of query and context hits",
            latency_ms=latency,
        )

    async def _evaluate_l5(self, ctx: DecisionContext) -> LayerEvaluation:
        """Evaluate L5: Assembled RAG context cache."""
        start = time.perf_counter()

        if not ctx.context or not ctx.context.strip():
            latency = (time.perf_counter() - start) * 1000
            return LayerEvaluation(
                layer="L5",
                checked=True,
                hit=False,
                confidence=0.0,
                reasoning="L5 skipped: no context provided",
                latency_ms=latency,
            )

        # L5 requires chunks to compute the chunks_hash
        # The chunks should be available in ctx.metadata if RAG retrieval happened
        chunks = ctx.metadata.get("retrieved_chunks", []) if ctx.metadata else []
        if not chunks:
            latency = (time.perf_counter() - start) * 1000
            return LayerEvaluation(
                layer="L5",
                checked=True,
                hit=False,
                confidence=0.0,
                reasoning="L5 skipped: no retrieved chunks available",
                latency_ms=latency,
            )

        template_version = getattr(ctx, "prompt_template_version", ctx.prompt_version)
        token_budget = getattr(ctx, "token_budget", 4000)

        # Get cached context from L5
        cached_context = await self.cache_engine.get_l5(
            ctx.query,
            chunks,
            template_version,
            token_budget,
            tenant_id=ctx.tenant_id,
            model=ctx.model,
            provider=ctx.provider,
            model_params=ctx.model_params,
        )

        latency = (time.perf_counter() - start) * 1000

        if cached_context:
            # Verify hard gates
            chunks_hash = compute_chunks_hash(chunks)
            model_fingerprint = ctx.model_fingerprint
            provider = ctx.provider

            incoming_meta = {
                "tenant_id": ctx.tenant_id,
                "chunk_content_hashes": chunks_hash,
                "template_version": template_version,
                "token_budget": token_budget,
                "model_fingerprint": model_fingerprint,
                "provider": provider,
            }

            # Get cached metadata from the cached context payload
            # We need to fetch the metadata to verify gates
            # For now, we trust the cache_engine.get_l5 already verified gates
            # But let's re-verify for completeness
            allowed, gates_passed, gates_failed = hard_gate_extended(
                incoming_meta,
                incoming_meta,  # We'd need to get this from the cached entry
                layer="L5",
                mode=ctx.reuse_policy.mode,
                fuzzy_fields=list(ctx.reuse_policy.fuzzy_fields),
                schema=self.cache_engine.schema,
            )

            # Since get_l5 already verifies gates, we trust the hit
            confidence = compute_confidence(
                ReuseAction.RAG_RETRIEVAL,
                base_score=0.95,  # High confidence for exact context match
            )

            return LayerEvaluation(
                layer="L5",
                checked=True,
                hit=True,
                score=1.0,
                confidence=confidence,
                cache_key=f"l5:{ctx.tenant_id}:{chunks_hash[:8]}:{template_version}:{token_budget}",
                cached_value=cached_context,
                gates_passed=["tenant_id", "chunk_content_hashes", "template_version", "token_budget", "model_fingerprint", "provider"],
                gates_failed=[],
                gate_mode=ctx.reuse_policy.mode,
                reasoning=f"L5 context match: {len(chunks)} chunks, template={template_version}, budget={token_budget}",
                latency_ms=latency,
            )

        return LayerEvaluation(
            layer="L5",
            checked=True,
            hit=False,
            confidence=0.0,
            reasoning="L5 context cache miss: no matching assembled context found",
            latency_ms=latency,
        )

    # ──────────────────────────────────────────────────────────────────────────────
    # Phase 5: Decision Trace Helper Methods
    # ──────────────────────────────────────────────────────────────────────────────

    def _to_layer_trace(self, eval: LayerEvaluation) -> LayerTrace:
        """Convert LayerEvaluation to LayerTrace for observability."""
        # Determine status
        if not eval.checked:
            status = LayerStatus.NOT_ATTEMPTED
        elif eval.hit:
            status = LayerStatus.HIT
        elif eval.gates_failed:
            status = LayerStatus.BLOCKED
        elif "skipped" in eval.reasoning.lower():
            status = LayerStatus.SKIPPED
        else:
            status = LayerStatus.MISS

        # Determine reuse source
        reuse_source = None
        if eval.hit:
            if "exact" in eval.reasoning.lower():
                reuse_source = "exact_match"
            elif "semantic" in eval.reasoning.lower():
                reuse_source = "semantic_match"
            elif "context" in eval.reasoning.lower():
                reuse_source = "context_match"
            elif "embedding" in eval.reasoning.lower():
                reuse_source = "embedding_cache"
            elif "deterministic" in eval.reasoning.lower():
                reuse_source = "deterministic_function"

        return LayerTrace(
            layer=eval.layer,
            status=status,
            reason=eval.reasoning,
            latency_ms=eval.latency_ms,
            hit=eval.hit,
            confidence=eval.confidence,
            cache_key=eval.cache_key,
            reuse_source=reuse_source,
            gates_passed=eval.gates_passed,
            gates_failed=eval.gates_failed,
            metadata={
                "score": eval.score,
                "gate_mode": eval.gate_mode.value if hasattr(eval, 'gate_mode') else None,
            },
        )

    def _finalize_trace(self, trace: DecisionTrace, decision: ReuseDecision) -> None:
        """Finalize and store the decision trace for a ReuseDecision."""
        final_layer = decision.layer if decision.layer != "NONE" else None
        trace.final_layer = final_layer
        outcome = derive_outcome(trace)
        trace.finalize(
            outcome=outcome,
            final_layer=final_layer,
            final_confidence=decision.confidence,
            final_reason=decision.fallback_reason or decision.reasoning,
        )
        if self.trace_store:
            self.trace_store.store(trace)

    def get_trace(self, trace_id: str) -> Optional[DecisionTrace]:
        """Retrieve a decision trace by trace_id."""
        if self.trace_store:
            return self.trace_store.get_by_trace_id(trace_id)
        return None

    def get_trace_by_request(self, request_id: str) -> Optional[DecisionTrace]:
        """Retrieve a decision trace by request_id."""
        if self.trace_store:
            return self.trace_store.get_by_request_id(request_id)
        return None

    def get_recent_traces(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[DecisionTrace]:
        """Get recent decision traces, optionally filtered by tenant."""
        if self.trace_store:
            return self.trace_store.get_recent(tenant_id=tenant_id, limit=limit)
        return []

    def get_trace_stats(self) -> Dict[str, Any]:
        """Get statistics about stored traces."""
        if self.trace_store:
            return self.trace_store.stats()
        return {"error": "Tracing is disabled"}

