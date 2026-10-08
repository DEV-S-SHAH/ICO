"""
cache_engine.py — Generalized, dataset-agnostic, multi-tenant ICO-Cache CacheEngine.
"""

import asyncio
import functools
import hashlib
import json
import platform
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog

from ..backends.base import BaseEmbedder, BaseExactStore, BaseVectorStore
from ..telemetry.metrics import (
    inflight_dec,
    inflight_inc,
    record_generation,
    record_lookup,
    record_latency,
    record_request,
)
from ..telemetry.tracing import trace_cache_lookup
from ..telemetry.cost_model import CostModel, get_cost_model
from ..telemetry.accounting import (
    CostCalculator,
    DecisionAction,
    SavingsCalculator,
    UsageRecord,
    UsageSource,
    record_usage,
)
from .decision_trace import DecisionTraceStore
from .decision_engine import (
    build_l1_key,
    build_l5_key,
    canonical_meta_suffix,
    compute_chunks_hash,
    context_hash,
)
from .decision_trace import (
    DecisionOutcome,
    LayerStatus,
    LayerTrace,
    begin_trace,
    derive_outcome,
    record_layer,
    reset_active_trace,
)
from .metadata_guard import MetadataSchema, hard_gate, GateMode

logger = structlog.get_logger("ico_cache.core.cache_engine")


@dataclass
class DeterministicFunction:
    """Registration for a deterministic function that can be cached."""
    name: str
    version: str
    func: Callable
    description: str = ""
    arg_schema: Optional[Dict[str, Any]] = None

# Message returned by the RAG pipeline when it refuses to answer. Never cached.
INSUFFICIENT_CONTEXT = "Insufficient context."


async def _run_sync(fn, *args, **kwargs):
    """Run a blocking callable in a worker thread so it never blocks the loop."""
    if kwargs:
        fn = functools.partial(fn, **kwargs)
    return await asyncio.to_thread(fn, *args)


def _stable_id(*parts: str) -> int:
    """Deterministic, process-independent 64-bit id derived from sha256."""
    raw = ":".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _canonical_meta_suffix(meta: dict) -> str:
    """
    Deterministic string representation of the metadata dict used to
    differentiate L1 keys. Only fields that are non-None participate.
    """
    if not meta:
        return ""
    items = sorted((k, v) for k, v in meta.items() if v is not None)
    return "|" + "&".join(f"{k}={v}" for k, v in items)


def _cosine(a: List[float], b: List[float]) -> float:
    """Plain cosine similarity (does not assume normalized vectors)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    denom = (
        sum(x * x for x in a) ** 0.5
    ) * (
        sum(y * y for y in b) ** 0.5
    )
    if denom == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / denom


def _stale(payload: dict, ttl: int) -> bool:
    """True if a vector-cache entry is older than its TTL (no TTL -> never)."""
    if not ttl:
        return False
    ts = payload.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    return time.time() - ts > ttl


_EVIDENCE_RE = re.compile(
    r"\d[\d.,]*(?:%|ms|s|gb|mb|kb)?|\b[A-Z][A-Za-z0-9_]{1,}\b|\b[a-zA-Z]{3,}[a-z]*[A-Z][A-Za-z0-9_]*\b"
)
_EVIDENCE_STOP = {
    "the", "and", "for", "with", "that", "this", "you", "are", "was", "not",
    "but", "have", "there", "from", "which", "will", "than", "what", "how",
    "your", "their", "about", "would", "these", "over", "per", "out", "with",
}


def extract_evidence(context: Optional[str]) -> list:
    """Discriminative tokens (numbers, identifiers, significant words) of a
    context snippet, used to check whether a cached answer is still grounded
    in the *current* retrieved context."""
    if not context:
        return []
    out: list = []
    for tok in _EVIDENCE_RE.findall(context):
        low = tok.lower()
        if len(tok) < 2 or low in _EVIDENCE_STOP:
            continue
        if tok not in out:
            out.append(tok)
    return out[:32]


class CacheEngine:
    def __init__(
        self,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        exact_store: BaseExactStore,
        schema: Optional[MetadataSchema] = None,
        metadata_filter_keys: Optional[List[str]] = None,
        thresh_semantic: float = 0.85,
        thresh_ctx_q: float = 0.75,
        thresh_ctx_c: float = 0.85,
        adaptive_threshold: bool = False,
        target_hit_rate: float = 0.80,
        min_threshold: float = 0.70,
        max_threshold: float = 0.95,
        adjustment_rate: float = 0.01,
        l1_ttl: int = 3600,
        tenant_isolation_mode: str = "collection",  # "collection" or "payload"
        lookup_timeout: float = 2.0,
        serve_threshold: float = 0.90,
        bind_context_to_l1: bool = False,
        l2_l3_ttl: int = 3600,
        paraphrase_threshold: Optional[float] = None,
        evidence_overlap_threshold: float = 0.50,
        # Phase 3: New parameters for DecisionEngine integration
        default_model: str = "gpt-4o",
        default_provider: str = "openai",
        default_prompt_version: str = "v1",
        default_model_params: Optional[Dict[str, Any]] = None,
        # Phase 3: L0b Embedding Cache
        l0b_ttl: int = 2592000,  # 30 days
        # Phase 3: Token + Cost Accounting
        cost_model: Optional[CostModel] = None,
        agent_type: str = "chatbot",
        # Phase 5: Decision Trace
        enable_decision_tracing: bool = True,
        max_decision_traces: int = 1000,
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.exact_store = exact_store
        self.schema = schema or MetadataSchema()
        self.tenant_isolation_mode = tenant_isolation_mode
        self.cost_model = cost_model or get_cost_model()
        self.agent_type = agent_type

        # Phase 5: Decision Trace
        self.enable_decision_tracing = enable_decision_tracing
        self.decision_traces = (
            DecisionTraceStore(max_traces=max_decision_traces)
            if enable_decision_tracing
            else None
        )

        if metadata_filter_keys is not None:
            self.metadata_filter_keys = metadata_filter_keys
        elif self.schema and self.schema.fields:
            self.metadata_filter_keys = self.schema.filter_keys
        else:
            self.metadata_filter_keys = []

        self.thresh_semantic = thresh_semantic
        self.thresh_ctx_q = thresh_ctx_q
        self.thresh_ctx_c = thresh_ctx_c

        # Adaptive threshold
        self.adaptive_threshold = adaptive_threshold
        self.target_hit_rate = target_hit_rate
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self.adjustment_rate = adjustment_rate

        self.l1_ttl = l1_ttl
        self.lookup_timeout = lookup_timeout

        self.serve_threshold = serve_threshold
        self.bind_context_to_l1 = bind_context_to_l1
        self.l2_l3_ttl = l2_l3_ttl
        self.paraphrase_threshold = paraphrase_threshold
        self.evidence_overlap_threshold = evidence_overlap_threshold
        self._emb_cache: dict = {}

        # Phase 3: Default identity for L1 key
        self.default_model = default_model
        self.default_provider = default_provider
        self.default_prompt_version = default_prompt_version
        self.default_model_params = default_model_params or {}

        self._stats_hits = 0
        self._stats_misses = 0
        self._layer_stats = {"L1": 0, "L2": 0, "L3": 0, "MISS": 0}
        self._collections_setup: dict = {}
        # Single-flight: in-progress generations keyed by L1 key.
        self._inflight: dict = {}
        self._inflight_lock = asyncio.Lock()

        # Phase 3: L0a Deterministic Function Cache
        self._det_functions: Dict[str, DeterministicFunction] = {}
        self._env_hash: str = self._compute_env_hash()

        # Phase 3: L0b Embedding Cache
        self.l0b_ttl = l0b_ttl
        self._l0b_stats = {"hits": 0, "misses": 0}
        self._l0b_inflight: dict = {}  # Single-flight for L0b embeddings

        # Phase 3A.5: Token + Cost Accounting
        self._cost_calculator = CostCalculator(self.cost_model)
        self._savings_calculator = SavingsCalculator(self._cost_calculator)

        # Phase 3: L5 Context Cache
        self._l5_stats = {"hits": 0, "misses": 0}
        self._l5_inflight: dict = {}  # Single-flight for L5 context

    def get_metrics(self) -> dict:
        total = self._stats_hits + self._stats_misses
        return {
            "hits": self._stats_hits,
            "misses": self._stats_misses,
            "hit_rate": (self._stats_hits / total) if total > 0 else 0.0,
            "layer_stats": dict(self._layer_stats),
            "threshold_semantic": self.thresh_semantic,
        }

    @classmethod
    def embedded(
        cls,
        db_path: str = "cache.db",
        vector_dir: str = "./lancedb",
        metadata_filter_keys: Optional[List[str]] = None,
        adaptive_threshold: bool = True,
        **kwargs,
    ) -> "CacheEngine":
        """Convenience factory: creates a zero-infra CacheEngine backed by FastEmbed, LanceDB, and SQLite."""
        from ..backends.embedding.fastembed_embedder import FastEmbedder
        from ..backends.vector.lancedb_store import LanceDBStore
        from ..backends.exact.sqlite_store import SQLiteStore

        return cls(
            embedder=FastEmbedder(),
            vector_store=LanceDBStore(uri=vector_dir),
            exact_store=SQLiteStore(db_path=db_path),
            metadata_filter_keys=metadata_filter_keys or [],
            adaptive_threshold=adaptive_threshold,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _coll_name(self, base_coll: str, tenant_id: str = "default") -> str:
        if base_coll == "l2_cache" and hasattr(self, "_l2_collection") and self._l2_collection:
            return self._l2_collection
        if base_coll == "l3_cache" and hasattr(self, "_l3_collection") and self._l3_collection:
            return self._l3_collection
        if self.tenant_isolation_mode == "collection":
            return f"{tenant_id}_{base_coll}"
        return base_coll

    def _setup_collections(self, tenant_id: str = "default"):
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)

        if self._collections_setup.get(coll_l2) and self._collections_setup.get(coll_l3):
            return

        try:
            if not self.vector_store.collection_exists(coll_l2):
                self.vector_store.create_collection(coll_l2, None)
            if not self.vector_store.collection_exists(coll_l3):
                self.vector_store.create_collection(
                    coll_l3,
                    {
                        "query": {"size": 384, "distance": "Cosine"},
                        "context": {"size": 384, "distance": "Cosine"},
                    },
                )
            self._collections_setup[coll_l2] = True
            self._collections_setup[coll_l3] = True
        except Exception:
            pass

    def _normalize(self, query: str) -> str:
        return " ".join(query.lower().strip().split())

    async def _same_question_score(self, query_emb: list, stored_query: str) -> Optional[float]:
        """Return embedding cosine between the incoming query and a stored
        query so a caller can verify both really ask the same question."""
        if not stored_query or not stored_query.strip():
            return None
        stored_emb = await self._embed(stored_query)
        if not stored_emb:
            return None
        return _cosine(query_emb, stored_emb)

    async def _embed(self, text: str) -> list:
        """Embed with an in-memory memo; contexts and stored queries repeat a lot."""
        key = self._normalize(text)[:2000]
        hit = self._emb_cache.get(key)
        if hit is None:
            hit = await _run_sync(self.embedder.embed, text)
            self._emb_cache[key] = hit
        return hit

    def _grounding_pass(self, payload: dict, context: Optional[str]) -> bool:
        """True when the CURRENT retrieved context still supports the evidence
        tokens of the answer that was originally cached. Lets a sub-threshold
        paraphrase serve only if it is independently grounded."""
        ev = payload.get("evidence") or []
        if not ev or not context:
            return False
        ctx_norm = " ".join(context.lower().split())
        hits = sum(1 for t in ev if t.lower() in ctx_norm)
        return hits / len(ev) >= self.evidence_overlap_threshold

    async def _serve_candidate(self, emb, stored_query, payload, context) -> Optional[dict]:
        """Two-tier serving: strong same-question OR (weaker question match AND
        answer still grounded in the incoming retrieved context)."""
        same_q = await self._same_question_score(emb, stored_query)
        if same_q is None:
            return None
        if same_q >= self.serve_threshold:
            return payload.get("answer")
        if (
            self.paraphrase_threshold
            and same_q >= self.paraphrase_threshold
            and self._grounding_pass(payload, context)
        ):
            return payload.get("answer")
        return None

    def _compute_env_hash(self) -> str:
        """Compute environment hash for cross-environment reproducibility."""
        parts = [
            sys.version.split()[0],
            platform.platform(),
            f"deps:{hashlib.sha256(str(sorted(sys.modules.keys())).encode()).hexdigest()[:8]}",
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def register_deterministic_function(
        self,
        name: str,
        version: str,
        func: Callable,
        description: str = "",
        arg_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a deterministic function for L0a caching.

        The function must be pure (no side effects, no external I/O, no randomness).
        Results are cached with content-addressable keys: det:{name}:{version}:{args_hash}:{env_hash}
        """
        if not callable(func):
            raise ValueError(f"Function {name} must be callable")
        self._det_functions[name] = DeterministicFunction(
            name=name,
            version=version,
            func=func,
            description=description,
            arg_schema=arg_schema,
        )
        logger.info("det_function_registered", name=name, version=version)

    def _auto_meta(self, text: str, explicit_meta: Optional[dict] = None) -> dict:
        auto = self.schema.extract(text) if self.schema else {}
        merged = {k: v for k, v in auto.items() if v is not None}
        if explicit_meta:
            merged.update({k: v for k, v in explicit_meta.items() if v is not None})
        return merged

    def _compute_model_fingerprint(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compute model fingerprint: sha256(model + provider + deterministic_params)[:12]."""
        model = model or self.default_model
        provider = provider or self.default_provider
        model_params = model_params or self.default_model_params

        deterministic_params = {
            k: v for k, v in model_params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed")
        }
        model_fp_raw = f"{model}|{provider}|{str(sorted(deterministic_params.items()))}"
        return hashlib.sha256(model_fp_raw.encode()).hexdigest()[:12]

    def _l1_key(
        self,
        query: str,
        meta: dict,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        context: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build L1 key per Phase 3 spec:
        {tenant_id}:l1:sha256(normalized_query + "|" + model_fingerprint + "|" + provider + "|" + prompt_version + "|" + context_hash + "|" + canonical_meta_suffix)
        """
        normalized = self._normalize(query)
        suffix = canonical_meta_suffix(meta)

        model = model or self.default_model
        provider = provider or self.default_provider
        prompt_version = prompt_version or self.default_prompt_version
        model_params = model_params or self.default_model_params

        model_fingerprint = self._compute_model_fingerprint(model, provider, model_params)
        context_h = context_hash(context)

        return build_l1_key(
            tenant_id=tenant_id,
            normalized_query=normalized,
            model_fingerprint=model_fingerprint,
            provider=provider,
            prompt_version=prompt_version,
            context_hash=context_h,
            canonical_meta_suffix=suffix,
        )

    async def _record_result(self, hit: bool):
        """Count every outcome unconditionally, then adapt if enabled."""
        if hit:
            self._stats_hits += 1
        else:
            self._stats_misses += 1
        self._update_adaptive_threshold(hit)

    def _update_adaptive_threshold(self, hit: bool):
        # NOTE: counting happens in _record_result so metrics are truthful
        # even when adaptive_threshold is disabled.
        if not self.adaptive_threshold:
            return
        total = self._stats_hits + self._stats_misses
        if total > 0 and total % 10 == 0:
            current_hit_rate = self._stats_hits / total
            if current_hit_rate < self.target_hit_rate:
                self.thresh_semantic = max(
                    self.min_threshold,
                    self.thresh_semantic - self.adjustment_rate,
                )
            else:
                self.thresh_semantic = min(
                    self.max_threshold,
                    self.thresh_semantic + self.adjustment_rate,
                )

    def build_meta_filter(self, meta_in: dict, tenant_id: str = "default"):
        from qdrant_client.http import models

        conditions = []
        if self.tenant_isolation_mode == "payload":
            conditions.append(
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id),
                )
            )

        if meta_in:
            for k, v in meta_in.items():
                conditions.append(
                    models.Filter(
                        should=[
                            models.FieldCondition(
                                key=f"meta.{k}",
                                match=models.MatchValue(value=v),
                            ),
                            models.IsEmptyCondition(
                                is_empty=models.PayloadField(key=f"meta.{k}")
                            ),
                        ]
                    )
                )
        return models.Filter(must=conditions) if conditions else None

    # ------------------------------------------------------------------
    # L1 — exact / Redis / SQLite
    # ------------------------------------------------------------------

    async def get_l1(
        self,
        query: str,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        context: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params)
        val = await _run_sync(self.exact_store.get, key)
        if val:
            try:
                return json.loads(val.decode())
            except Exception:
                return None
        return None

    def set_l1(
        self,
        query: str,
        response: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        context: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
        nx: bool = False,
    ) -> bool:
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params)
        return self.exact_store.set(
            key, json.dumps(response).encode(), ex=self.l1_ttl, nx=nx
        )

    # ------------------------------------------------------------------
    # L0a — Deterministic Computation Cache
    # ------------------------------------------------------------------

    def _build_l0a_key(self, fn_name: str, args: Dict[str, Any]) -> str:
        """Build L0a deterministic function cache key."""
        from .decision_engine import build_l0a_key
        return build_l0a_key(fn_name, args, self._det_functions[fn_name].version, self._env_hash)

    async def get_l0a(self, fn_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """Get cached result for a deterministic function."""
        if fn_name not in self._det_functions:
            return None
        key = self._build_l0a_key(fn_name, args)
        val = await _run_sync(self.exact_store.get, key)
        if val:
            try:
                return json.loads(val.decode())
            except Exception:
                return None
        return None

    async def set_l0a(self, fn_name: str, args: Dict[str, Any], result: Any) -> bool:
        """Cache result for a deterministic function (infinite TTL)."""
        if fn_name not in self._det_functions:
            return False
        key = self._build_l0a_key(fn_name, args)
        # Infinite TTL for content-addressable keys
        return self.exact_store.set(key, json.dumps(result).encode(), ex=None, nx=True)

    async def execute_deterministic(self, fn_name: str, args: Dict[str, Any]) -> Any:
        """
        Execute a deterministic function with L0a caching.

        Checks cache first; on miss, executes function, caches result, returns.
        Uses single-flight to deduplicate concurrent executions of same function+args.
        """
        if fn_name not in self._det_functions:
            raise ValueError(f"Deterministic function '{fn_name}' not registered")

        record_l0a = self.enable_decision_tracing
        t_l0a_start = time.perf_counter()

        # Check cache
        cached = await self.get_l0a(fn_name, args)
        if cached is not None:
            if record_l0a:
                record_layer(
                    "L0a",
                    LayerStatus.HIT,
                    reason=f"L0a deterministic function cache hit: {fn_name}",
                    latency_ms=(time.perf_counter() - t_l0a_start) * 1000,
                    hit=True,
                    reuse_source="deterministic_function",
                    cache_key=self._build_l0a_key(fn_name, args),
                )
            return cached

        # Single-flight key
        key = self._build_l0a_key(fn_name, args)

        existing = self._inflight.get(key)
        if existing is not None:
            # Join the in-progress execution instead of starting a new one.
            if record_l0a:
                record_layer(
                    "L0a",
                    LayerStatus.HIT,
                    reason=f"L0a deterministic function cache hit (single-flight wait): {fn_name}",
                    latency_ms=(time.perf_counter() - t_l0a_start) * 1000,
                    hit=True,
                    reuse_source="deterministic_function",
                    cache_key=key,
                )
            return await asyncio.shield(existing)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._inflight[key] = future
        try:
            # Execute function
            func = self._det_functions[fn_name].func
            if asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                result = await _run_sync(func, **args)

            # Cache result
            await self.set_l0a(fn_name, args, result)

            if not future.done():
                future.set_result(result)
            if record_l0a:
                record_layer(
                    "L0a",
                    LayerStatus.MISS,
                    reason=f"L0a deterministic function cache miss: executed {fn_name}",
                    latency_ms=(time.perf_counter() - t_l0a_start) * 1000,
                    hit=False,
                    cache_key=key,
                )
            return result
        except BaseException:
            # Includes CancelledError. Resolve waiters (so they never hang) and
            # re-raise for the leader. Waiters degrade to executing function again
            # rather than sharing the failure.
            if not future.done():
                future.set_result(None)
            if record_l0a:
                record_layer(
                    "L0a",
                    LayerStatus.MISS,
                    reason=f"L0a deterministic function execution failed: {fn_name}",
                    latency_ms=(time.perf_counter() - t_l0a_start) * 1000,
                    hit=False,
                    cache_key=key,
                )
            raise
        finally:
            self._inflight.pop(key, None)

    # ------------------------------------------------------------------
    # L0b — Embedding Cache
    # ------------------------------------------------------------------

    def _l0b_collection(self, tenant_id: str = "default") -> str:
        """Get L0b embedding cache collection name."""
        return self._coll_name("l0b_embeddings", tenant_id)

    async def _setup_l0b_collection(self, tenant_id: str = "default"):
        """Setup L0b embedding cache collection."""
        coll = self._l0b_collection(tenant_id)
        if self._collections_setup.get(coll):
            return
        try:
            if not self.vector_store.collection_exists(coll):
                # Get embedding dimension from embedder
                test_emb = await _run_sync(self.embedder.embed, "test")
                dim = len(test_emb)
                self.vector_store.create_collection(coll, {"size": dim, "distance": "Cosine"})
            self._collections_setup[coll] = True
        except Exception as e:
            logger.warning("l0b_collection_setup_failed", collection=coll, error=str(e))

    def _build_l0b_key(self, model_fingerprint: str, text: str) -> str:
        """Build L0b embedding cache key."""
        from .decision_engine import build_l0b_key
        return build_l0b_key(model_fingerprint, text)

    async def get_embedding(
        self, text: str, model_fingerprint: Optional[str] = None, *, record_l0b: bool = True
    ) -> List[float]:
        """
        Get embedding for text, using L0b cache if available.

        Checks L0b cache first; on miss, computes embedding, caches it, returns.
        Uses single-flight protection to prevent duplicate computation.

        Args:
            text: The text to embed.
            model_fingerprint: Optional model fingerprint for isolation.
            record_l0b: Whether to record this lookup in the active decision trace.
                Should be False for write-path embeddings (e.g., async_write_l2/l3).
        """
        if model_fingerprint is None:
            model_fingerprint = self.embedder.model_version

        _ = self._build_l0b_key(model_fingerprint, text)
        emb_id = _stable_id("l0b", model_fingerprint, text)

        # Try to get from L0b cache via get_vectors (exact ID lookup)
        await self._setup_l0b_collection("default")
        coll = self._l0b_collection("default")

        t_l0b_start = time.perf_counter()
        record_l0b = record_l0b and self.enable_decision_tracing

        # First try exact ID lookup
        if hasattr(self.vector_store, "get_vectors"):
            vectors = await self.vector_store.get_vectors(coll, [emb_id])
            if vectors and vectors[0] is not None:
                self._l0b_stats["hits"] += 1
                if record_l0b:
                    record_layer(
                        "L0b",
                        LayerStatus.HIT,
                        reason="L0b embedding cache hit",
                        latency_ms=(time.perf_counter() - t_l0b_start) * 1000,
                        hit=True,
                        reuse_source="embedding_cache",
                        cache_key=emb_id,
                    )
                return vectors[0]

        # Single-flight protection: check if another task is already computing this embedding
        if emb_id in self._l0b_inflight:
            future = self._l0b_inflight[emb_id]
            result = await future
            if result is not None:
                self._l0b_stats["hits"] += 1  # Count as hit since we waited for it
                if record_l0b:
                    record_layer(
                        "L0b",
                        LayerStatus.HIT,
                        reason="L0b embedding cache hit (single-flight wait)",
                        latency_ms=(time.perf_counter() - t_l0b_start) * 1000,
                        hit=True,
                        reuse_source="embedding_cache",
                        cache_key=emb_id,
                    )
                return result
            # If result is None (failure), fall through to compute ourselves

        # Create future for this computation
        future = asyncio.Future()
        self._l0b_inflight[emb_id] = future

        try:
            # Compute embedding
            self._l0b_stats["misses"] += 1
            embedding = await _run_sync(self.embedder.embed, text)

            # Store in L0b cache
            await self.vector_store.insert(
                collection=coll,
                id=emb_id,
                vector=embedding,
                payload={"model_fingerprint": model_fingerprint, "text_hash": hashlib.sha256(text.encode()).hexdigest()[:16]},
            )

            # Resolve waiters
            if not future.done():
                future.set_result(embedding)
            if record_l0b:
                record_layer(
                    "L0b",
                    LayerStatus.MISS,
                    reason="L0b embedding cache miss: computed embedding",
                    latency_ms=(time.perf_counter() - t_l0b_start) * 1000,
                    hit=False,
                    cache_key=emb_id,
                )
            return embedding
        except BaseException:
            if not future.done():
                future.set_result(None)
            if record_l0b:
                record_layer(
                    "L0b",
                    LayerStatus.MISS,
                    reason="L0b embedding cache miss: computation failed",
                    latency_ms=(time.perf_counter() - t_l0b_start) * 1000,
                    hit=False,
                    cache_key=emb_id,
                )
            raise
        finally:
            self._l0b_inflight.pop(emb_id, None)

    def get_l0b_stats(self) -> dict:
        """Get L0b embedding cache statistics."""
        total = self._l0b_stats["hits"] + self._l0b_stats["misses"]
        return {
            "hits": self._l0b_stats["hits"],
            "misses": self._l0b_stats["misses"],
            "hit_rate": (self._l0b_stats["hits"] / total) if total > 0 else 0.0,
        }

    # ------------------------------------------------------------------
    # L2 — semantic / vector
    # ------------------------------------------------------------------

    async def get_l2(
        self, query: str, meta: Optional[dict] = None, tenant_id: str = "default", corpus_version: Optional[str] = None,
        model: Optional[str] = None, provider: Optional[str] = None, model_params: Optional[Dict[str, Any]] = None,
        prompt_version: Optional[str] = None, context: Optional[str] = None
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        # Add corpus_version to metadata for isolation
        if corpus_version:
            effective_meta["corpus_version"] = corpus_version
        # Add model_fingerprint for isolation (matches CRITICAL_FIELDS for L2)
        if model or provider:
            effective_meta["model_fingerprint"] = self._compute_model_fingerprint(model, provider, model_params)
        # Add prompt_version for isolation
        if prompt_version:
            effective_meta["prompt_version"] = prompt_version
        # Add context_hash for isolation when context is provided
        if context:
            effective_meta["context_hash"] = context_hash(context)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)
        emb = await self.get_embedding(query)

        hits = await self.vector_store.search(
            collection=coll_l2,
            vector=emb,
            query_filter=q_filter,
            limit=1,
            score_threshold=self.thresh_semantic,
        )

        if hits:
            payload = hits[0].payload
            cached_meta = payload.get("meta", {})
            gate_result = hard_gate(effective_meta, cached_meta, self.metadata_filter_keys, layer="L2")
            if isinstance(gate_result, tuple):
                allowed = gate_result[0]
            else:
                allowed = gate_result
            if allowed:
                return payload.get("answer")
        return None

    async def async_write_l2(
        self,
        query: str,
        generated: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        corpus_version: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
        prompt_version: Optional[str] = None,
        context: Optional[str] = None,
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        # Add corpus_version to metadata for isolation
        if corpus_version:
            effective_meta["corpus_version"] = corpus_version
        # Add model_fingerprint for isolation (matches CRITICAL_FIELDS for L2)
        if model or provider:
            effective_meta["model_fingerprint"] = self._compute_model_fingerprint(model, provider, model_params)
        # Add prompt_version for isolation
        if prompt_version:
            effective_meta["prompt_version"] = prompt_version
        # Add context_hash for isolation when context is provided
        if context:
            effective_meta["context_hash"] = context_hash(context)
        emb = await _run_sync(self.embedder.embed, query)

        payload: dict = {"query": query, "answer": generated, "meta": effective_meta}
        if self.tenant_isolation_mode == "payload":
            payload["tenant_id"] = tenant_id

        emb = await self.get_embedding(query, record_l0b=False)

        await self.vector_store.insert(
            collection=coll_l2,
            id=_stable_id(
                "l2",
                tenant_id,
                self._normalize(query),
                _canonical_meta_suffix(effective_meta),
            ),
            vector=emb,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # L3 — context-aware / dual-vector
    # ------------------------------------------------------------------

    async def get_l3(
        self,
        query: str,
        context: str,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        corpus_version: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        if not context or not context.strip():
            return None

        effective_meta = self._auto_meta(query, meta)
        # Add corpus_version to metadata for isolation
        if corpus_version:
            effective_meta["corpus_version"] = corpus_version
        # Add model_fingerprint for isolation (matches CRITICAL_FIELDS for L3)
        if model or provider:
            effective_meta["model_fingerprint"] = self._compute_model_fingerprint(model, provider, model_params)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)

        emb_q = await self.get_embedding(query)
        emb_c = await self.get_embedding(context)

        hits_q = await self.vector_store.search(
            collection=coll_l3,
            vector=emb_q,
            query_filter=q_filter,
            limit=5,
            score_threshold=self.thresh_ctx_q,
            using="query",
        )
        if not hits_q:
            return None

        hits_c = await self.vector_store.search(
            collection=coll_l3,
            vector=emb_c,
            query_filter=q_filter,
            limit=5,
            score_threshold=self.thresh_ctx_c,
            using="context",
        )
        if not hits_c:
            return None

        q_ids = {h.id for h in hits_q}
        c_ids = {h.id for h in hits_c}
        common = q_ids.intersection(c_ids)

        if common:
            incoming_ctx_meta = self.schema.extract(context) if self.schema else {}

            for cid in common:
                h = next(h for h in hits_q if h.id == cid)
                cached_payload = h.payload
                cached_ctx_str = cached_payload.get("context", "")
                cached_ctx_meta = self.schema.extract(cached_ctx_str) if self.schema else {}
                cached_meta = cached_payload.get("meta", {})

                full_cached_meta = {
                    **cached_meta,
                    **{k: v for k, v in cached_ctx_meta.items() if v is not None},
                }
                full_incoming_meta = {
                    **effective_meta,
                    **{k: v for k, v in incoming_ctx_meta.items() if v is not None},
                }

                gate_result = hard_gate(full_incoming_meta, full_cached_meta, self.metadata_filter_keys, layer="L3")
                allowed = gate_result[0] if isinstance(gate_result, tuple) else gate_result
                if allowed:
                    return cached_payload.get("answer")
        return None

    async def async_write_l3(
        self,
        query: str,
        context: str,
        generated: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        corpus_version: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        ctx_meta = self.schema.extract(context) if self.schema else {}
        full_meta = {**effective_meta, **{k: v for k, v in ctx_meta.items() if v is not None}}
        # Add corpus_version to metadata for isolation
        if corpus_version:
            full_meta["corpus_version"] = corpus_version
        # Add model_fingerprint for isolation (matches CRITICAL_FIELDS for L3)
        if model or provider:
            full_meta["model_fingerprint"] = self._compute_model_fingerprint(model, provider, model_params)
            full_meta["corpus_version"] = corpus_version

        emb_q = await self.get_embedding(query, record_l0b=False)
        emb_c = await self.get_embedding(context, record_l0b=False)

        payload: dict = {
            "query": query,
            "context": context,
            "answer": generated,
            "meta": full_meta,
        }
        if self.tenant_isolation_mode == "payload":
            payload["tenant_id"] = tenant_id

        await self.vector_store.insert(
            collection=coll_l3,
            id=_stable_id(
                "l3",
                tenant_id,
                self._normalize(query),
                context,
                _canonical_meta_suffix(full_meta),
            ),
            vector={"query": emb_q, "context": emb_c},
            payload=payload,
        )

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: ~4 chars per token."""
        return max(len(text) // 4, 1)

    # ------------------------------------------------------------------
    # Public resolve
    # ------------------------------------------------------------------

    async def _safe_lookup(self, layer: str, awaitable):
        """Run a layer lookup with a timeout; any failure degrades to a miss."""
        try:
            return await asyncio.wait_for(awaitable, timeout=self.lookup_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "cache_lookup_timeout", layer=layer, timeout_s=self.lookup_timeout
            )
        except Exception as e:
            logger.warning("cache_lookup_failed", layer=layer, error=str(e))
        return None

    async def resolve(
        self,
        query: str,
        context: Optional[str] = None,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
        corpus_version: Optional[str] = None,
    ):
        t0 = time.perf_counter()
        model = model or self.default_model
        provider = provider or self.default_provider
        model_params = model_params or self.default_model_params

        # Phase 5: Decision Trace - start or join active trace
        trace, token, created = (None, None, False)
        if self.enable_decision_tracing:
            trace, token, created = begin_trace(
                tenant_id=tenant_id, query=query, model=model, provider=provider
            )

        try:
            # L1 Lookup
            with trace_cache_lookup("L1", tenant_id=tenant_id, query=query) as rec_l1:
                t_l1_start = time.perf_counter()
                res = await self._safe_lookup(
                    "L1", self.get_l1(query, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params)
                )
                t_l1_ms = (time.perf_counter() - t_l1_start) * 1000
                rec_l1.record_result(hit=res is not None)
                record_lookup("L1", res is not None, t_l1_ms / 1000)
                record_latency("cache_lookup", "L1", t_l1_ms / 1000)
                if trace is not None:
                    record_layer(
                        "L1",
                        LayerStatus.HIT if res else LayerStatus.MISS,
                        reason="L1 exact match" if res else "L1 exact key miss",
                        latency_ms=t_l1_ms,
                        hit=res is not None,
                        reuse_source="exact_match" if res else None,
                        cache_key=res.get("_l1_key") if res else None,
                    )
                if res:
                    await self._record_result(True)
                    self._layer_stats["L1"] += 1
                    # Record tokens saved on cache hit (estimate based on response size)
                    self._record_cache_hit_savings(res, tenant_id, model, provider)
                    logger.info(
                        "cache_hit",
                        layer="L1",
                        tenant_id=tenant_id,
                        query=query,
                        latency_ms=round(t_l1_ms, 3),
                    )
                    if trace is not None and created:
                        trace.finalize(
                            DecisionOutcome.CACHE_RESPONSE,
                            final_layer="L1",
                            final_confidence=1.0,
                            final_reason="L1 exact match",
                        )
                        if self.decision_traces is not None:
                            self.decision_traces.store(trace)
                    return {"source": "L1", "response": res}

            # L2 Lookup
            with trace_cache_lookup("L2", tenant_id=tenant_id, query=query) as rec_l2:
                t_l2_start = time.perf_counter()
                res2 = await self._safe_lookup(
                    "L2", self.get_l2(query, meta, tenant_id=tenant_id, corpus_version=corpus_version, model=model, provider=provider, model_params=model_params, prompt_version=prompt_version, context=context)
                )
                t_l2_ms = (time.perf_counter() - t_l2_start) * 1000
                rec_l2.record_result(hit=res2 is not None)
                record_lookup("L2", res2 is not None, t_l2_ms / 1000)
                record_latency("cache_lookup", "L2", t_l2_ms / 1000)
                if trace is not None:
                    record_layer(
                        "L2",
                        LayerStatus.HIT if res2 else LayerStatus.MISS,
                        reason="L2 semantic match" if res2 else "L2 no candidates above threshold",
                        latency_ms=t_l2_ms,
                        hit=res2 is not None,
                        reuse_source="semantic_match" if res2 else None,
                    )
                if res2:
                    await self._record_result(True)
                    self._layer_stats["L2"] += 1
                    self._record_cache_hit_savings(res2, tenant_id, model, provider)
                    logger.info(
                        "cache_hit",
                        layer="L2",
                        tenant_id=tenant_id,
                        query=query,
                        latency_ms=round(t_l2_ms, 3),
                    )
                    if trace is not None and created:
                        trace.finalize(
                            DecisionOutcome.CACHE_RESPONSE,
                            final_layer="L2",
                            final_confidence=1.0,
                            final_reason="L2 semantic match",
                        )
                        if self.decision_traces is not None:
                            self.decision_traces.store(trace)
                    return {"source": "L2", "response": res2}

            # L3 Lookup
            with trace_cache_lookup("L3", tenant_id=tenant_id, query=query) as rec_l3:
                t_l3_start = time.perf_counter()
                res3 = await self._safe_lookup(
                    "L3", self.get_l3(query, context, meta, tenant_id=tenant_id, corpus_version=corpus_version, model=model, provider=provider, model_params=model_params)
                )
                t_l3_ms = (time.perf_counter() - t_l3_start) * 1000
                rec_l3.record_result(hit=res3 is not None)
                record_lookup("L3", res3 is not None, t_l3_ms / 1000)
                record_latency("cache_lookup", "L3", t_l3_ms / 1000)
                if trace is not None:
                    record_layer(
                        "L3",
                        LayerStatus.HIT if res3 else LayerStatus.MISS,
                        reason="L3 context match" if res3 else "L3 no context match",
                        latency_ms=t_l3_ms,
                        hit=res3 is not None,
                        reuse_source="context_match" if res3 else None,
                    )
                if res3:
                    await self._record_result(True)
                    self._layer_stats["L3"] += 1
                    self._record_cache_hit_savings(res3, tenant_id, model, provider)
                    logger.info(
                        "cache_hit",
                        layer="L3",
                        tenant_id=tenant_id,
                        query=query,
                        latency_ms=round(t_l3_ms, 3),
                    )
                    if trace is not None and created:
                        trace.finalize(
                            DecisionOutcome.CACHE_RESPONSE,
                            final_layer="L3",
                            final_confidence=1.0,
                            final_reason="L3 context match",
                        )
                        if self.decision_traces is not None:
                            self.decision_traces.store(trace)
                    return {"source": "L3", "response": res3}

            total_ms = (time.perf_counter() - t0) * 1000
            await self._record_result(False)
            self._layer_stats["MISS"] += 1
            logger.info(
                "cache_miss",
                tenant_id=tenant_id,
                query=query,
                total_latency_ms=round(total_ms, 3),
                l1_latency_ms=round(t_l1_ms, 3),
                l2_latency_ms=round(t_l2_ms, 3),
                l3_latency_ms=round(t_l3_ms, 3),
            )
            if trace is not None and created:
                trace.finalize(
                    DecisionOutcome.GENERATE_LLM,
                    final_layer=None,
                    final_confidence=0.0,
                    final_reason="All cache layers missed; LLM generation required",
                )
                if self.decision_traces is not None:
                    self.decision_traces.store(trace)
            return {"source": "MISS", "response": None}
        finally:
            if token is not None:
                reset_active_trace(token)

    def _record_cache_hit_savings(self, response: dict, tenant_id: str, model: str, provider: str, layer: str = "L1") -> None:
        """Record token/cost savings from a cache hit using SavingsCalculator."""
        # Extract token usage from response
        usage = response.get("usage") or response.get("token_usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        if input_tokens == 0 and output_tokens == 0:
            # Fallback: estimate from response text
            answer = response.get("answer", "")
            if isinstance(answer, str):
                estimated_output = max(len(answer) // 4, 1)
                estimated_input = estimated_output * 3
                input_tokens = estimated_input
                output_tokens = estimated_output

        if input_tokens > 0 or output_tokens > 0:
            # Calculate savings using SavingsCalculator
            savings = self._savings_calculator.calculate_savings(
                layer=layer,
                decision_action=DecisionAction.EXACT_REUSE if layer == "L1" else (DecisionAction.SEMANTIC_REUSE if layer == "L2" else DecisionAction.CONTEXT_REUSE),
                provider=provider,
                model=model,
                baseline_input_tokens=input_tokens,
                baseline_output_tokens=output_tokens,
                actual_input_tokens=0,
                actual_output_tokens=0,
                actual_latency_ms=0.0,
            )

            avoided_input = savings["avoided_input_tokens"]
            avoided_output = savings["avoided_output_tokens"]
            avoided_total = savings["avoided_total_tokens"]
            cost_saved = savings["cost_saved"]

            # Emit UsageRecord for cache hit using factory method (handles cost_saved metrics)
            decision_action = DecisionAction.EXACT_REUSE if layer == "L1" else (DecisionAction.SEMANTIC_REUSE if layer == "L2" else DecisionAction.CONTEXT_REUSE)
            record = UsageRecord(
                request_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                timestamp=datetime.now(timezone.utc),
                layer=layer,
                decision_action=decision_action,
                cache_hit=1,
                cache_miss=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cached_input_tokens=avoided_input,
                avoided_input_tokens=avoided_input,
                avoided_output_tokens=avoided_output,
                avoided_total_tokens=avoided_total,
                estimated_cost=0.0,
                actual_cost=0.0,
                tokens_saved=avoided_total,
                cost_saved=cost_saved,
                latency_saved=0.0,
                latency_ms=0.0,
                model=model,
                provider=provider,
                success=True,
                usage_source=UsageSource.PROVIDER_RESPONSE,
            )
            record_usage(record)

        record_request("CACHE_HIT", self.agent_type, tenant_id)

    # ------------------------------------------------------------------
    # Single-flight resolve-or-generate
    # ------------------------------------------------------------------

    @staticmethod
    def _is_cacheable(generated) -> bool:
        """Error and refusal results must never be cached."""
        if generated is None:
            return False
        if isinstance(generated, dict):
            answer = generated.get("answer")
            if answer is None:
                return False
            if isinstance(answer, str):
                text = answer.strip()
                if not text or text == INSUFFICIENT_CONTEXT:
                    return False
                if text.startswith("LLM generation failed") or text == "Error generating response.":
                    return False
        return True

    async def resolve_or_generate(
        self,
        query: str,
        context: Optional[str] = None,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        generate_fn=None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
        corpus_version: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        """
        Cache lookup; on MISS, run ``generate_fn`` under single-flight so that
        concurrent identical misses trigger exactly one generation. Only
        successful (cacheable) results are written, and writes are conditional
        so an already-populated entry is never overwritten.

        Phase 5: records a DecisionTrace (L0a → L0b → L1 → L2 → L3 → L4 → L5 → LLM)
        retrievable via :meth:`get_decision_trace` with the provided ``request_id``.
        """
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params)

        # Phase 5: Decision Trace - start trace for the request
        trace, token, created = (None, None, False)
        if self.enable_decision_tracing:
            trace, token, created = begin_trace(
                request_id=request_id,
                tenant_id=tenant_id,
                query=query,
                model=model or self.default_model,
                provider=provider or self.default_provider,
            )

        # Single-flight: check if there's already an in-flight generation for this key
        # Do this BEFORE any cache lookups to ensure true single-flight
        async with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                # Waiter path: join the in-progress generation
                if trace is not None and created:
                    # Record waiter layers (all skipped) and LLM wait time
                    t_wait_start = time.perf_counter()
                    result = await asyncio.shield(existing)
                    wait_ms = (time.perf_counter() - t_wait_start) * 1000
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L0a", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L0b", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L1", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L2", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L3", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L4", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="L5", status=LayerStatus.SKIPPED, reason="Joined in-flight generation (single-flight dedup)"
                        )
                    )
                    trace.add_layer_trace(
                        LayerTrace(
                            layer="LLM",
                            status=LayerStatus.ATTEMPTED,
                            reason="Response shared from in-flight generation (single-flight)",
                            latency_ms=wait_ms,
                            hit=False,
                            metadata={"single_flight": "waiter"},
                        )
                    )
                    trace.finalize(
                        DecisionOutcome.GENERATE_LLM,
                        final_layer=None,
                        final_confidence=0.0,
                        final_reason="Response shared from in-flight LLM generation (single-flight leader)",
                    )
                    if self.decision_traces is not None:
                        self.decision_traces.store(trace)
                else:
                    result = await asyncio.shield(existing)
                if token is not None:
                    reset_active_trace(token)
                return result

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self._inflight[key] = future

            try:
                # Leader does cache lookups while holding the lock to prevent
                # other tasks from becoming leaders.
                res = await self.resolve(query, context, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, model_params=model_params, corpus_version=corpus_version)
                if res["source"] != "MISS" or generate_fn is None:
                    if not future.done():
                        future.set_result(res)
                    if trace is not None and created:
                        trace.finalize(
                            DecisionOutcome.CACHE_RESPONSE,
                            final_layer=res["source"],
                            final_confidence=1.0,
                            final_reason=f"Cache hit at {res['source']}",
                        )
                        if self.decision_traces is not None:
                            self.decision_traces.store(trace)
                    return res

                result = await self._generate_and_store(
                    query, context, meta, tenant_id, generate_fn, model=model, provider=provider, prompt_version=prompt_version, model_params=model_params, corpus_version=corpus_version
                )
                if not future.done():
                    future.set_result(result)
                if trace is not None and created:
                    # LLM layer recorded in _generate_and_store
                    # RAG L4/L5 layers recorded in RAGPipeline if active trace exists
                    final_outcome = derive_outcome(trace)
                    trace.finalize(
                        final_outcome,
                        final_layer=result["source"] if result["source"] != "MISS" else None,
                        final_confidence=1.0 if result["source"] != "MISS" else 0.0,
                        final_reason=f"Generated with LLM (source: {result['source']})",
                    )
                    if self.decision_traces is not None:
                        self.decision_traces.store(trace)
                return result
            except BaseException:
                # Includes CancelledError. Resolve waiters (so they never hang) and
                # re-raise for the leader. Waiters degrade to a miss rather than
                # sharing the failure.
                if not future.done():
                    future.set_result({"source": "MISS", "response": None})
                if trace is not None and created:
                    trace.finalize(
                        DecisionOutcome.GENERATE_LLM,
                        final_layer=None,
                        final_confidence=0.0,
                        final_reason="Exception during resolution/generation",
                    )
                    if self.decision_traces is not None:
                        self.decision_traces.store(trace)
                raise
            finally:
                self._inflight.pop(key, None)
                if token is not None:
                    reset_active_trace(token)

    async def _generate_and_store(
        self, query, context, meta, tenant_id, generate_fn, model=None, provider=None, prompt_version=None, model_params=None, corpus_version=None
    ) -> dict:
        # Conditional double-check: another writer may have populated the entry
        # while this coroutine was waiting to become the leader.
        existing = await self.get_l1(query, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params)
        if existing is not None:
            return {"source": "L1", "response": existing}

        inflight_inc()
        t_gen = time.perf_counter()
        try:
            generated = await generate_fn()
        finally:
            gen_time = time.perf_counter() - t_gen
            record_generation(gen_time)
            record_latency("generation", "LLM", gen_time)
            inflight_dec()
            # Phase 5: Record LLM layer in active trace
            record_layer(
                "LLM",
                LayerStatus.ATTEMPTED,
                reason="LLM generation completed",
                latency_ms=gen_time * 1000,
                hit=False,
                metadata={"success": True},
            )

        if not self._is_cacheable(generated):
            return {"source": "MISS", "response": generated}

        if await self.get_l1(query, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params) is not None:
            # Someone else won the race; do not overwrite.
            return {"source": "MISS", "response": generated}

        # Record actual token usage and cost from generation
        self._record_generation_usage(generated, tenant_id, model or self.default_model, provider or self.default_provider)

        await _run_sync(self.set_l1, query, generated, meta, tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, model_params=model_params, nx=True)
        await self.async_write_l2(query, generated, meta=meta, tenant_id=tenant_id, corpus_version=corpus_version, model=model, provider=provider, model_params=model_params, prompt_version=prompt_version, context=context)
        if context:
            await self.async_write_l3(
                query, context, generated, meta=meta, tenant_id=tenant_id, corpus_version=corpus_version, model=model, provider=provider, model_params=model_params
            )
        return {"source": "MISS", "response": generated}

    def _record_generation_usage(self, response: dict, tenant_id: str, model: str, provider: str) -> None:
        """Record token usage and cost from actual LLM generation using CostCalculator."""
        # Extract token usage from response
        usage = response.get("usage") or response.get("token_usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        # If no usage info, estimate from response
        if total_tokens == 0:
            answer = response.get("answer", "")
            if isinstance(answer, str):
                # Rough estimation
                estimated_output = max(len(answer) // 4, 1)
                estimated_input = estimated_output * 3
                input_tokens = estimated_input
                output_tokens = estimated_output
                total_tokens = input_tokens + output_tokens

        if total_tokens > 0:
            cost = self._cost_calculator.calculate(provider, model, input_tokens, output_tokens)

            # Emit UsageRecord for generation using factory method (handles metrics emission)
            record = UsageRecord(
                request_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                timestamp=datetime.now(timezone.utc),
                layer="NONE",
                decision_action=DecisionAction.FULL_LLM_CALL,
                cache_hit=0,
                cache_miss=1,
                llm_called=1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost=0.0,
                actual_cost=cost or 0.0,
                tokens_saved=0,
                cost_saved=0.0,
                latency_saved=0.0,
                latency_ms=0.0,
                model=model,
                provider=provider,
                success=True,
                usage_source=UsageSource.PROVIDER_RESPONSE,
            )
            record_usage(record)

        # Record request with decision
        record_request("FULL_LLM_CALL", self.agent_type, tenant_id)

    async def invalidate(
        self, tenant_id: str = "default", filter_dict: Optional[dict] = None
    ) -> dict:
        """
        Purges matching entries from L1, L2, and L3 for a tenant.
        """
        # 1. Purge L1 (v3 schema keys)
        l1_purged = 0
        if hasattr(self.exact_store, "delete_prefix"):
            l1_purged = await _run_sync(self.exact_store.delete_prefix, f"v3:{tenant_id}:")

        # 2. Purge L2
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_l2_filter = dict(filter_dict or {})
        if self.tenant_isolation_mode == "payload":
            effective_l2_filter["tenant_id"] = tenant_id

        l2_purged = 0
        if hasattr(self.vector_store, "delete_matching"):
            l2_purged = await self.vector_store.delete_matching(
                coll_l2,
                effective_l2_filter if (filter_dict or self.tenant_isolation_mode == "payload") else None,
            )
        elif hasattr(self.vector_store, "delete_collection") and not filter_dict and self.tenant_isolation_mode != "payload":
            await _run_sync(self.vector_store.delete_collection, coll_l2)
            l2_purged = -1

        # 3. Purge L3
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        effective_l3_filter = dict(filter_dict or {})
        if self.tenant_isolation_mode == "payload":
            effective_l3_filter["tenant_id"] = tenant_id

        l3_purged = 0
        if hasattr(self.vector_store, "delete_matching"):
            l3_purged = await self.vector_store.delete_matching(
                coll_l3,
                effective_l3_filter if (filter_dict or self.tenant_isolation_mode == "payload") else None,
            )
        elif hasattr(self.vector_store, "delete_collection") and not filter_dict and self.tenant_isolation_mode != "payload":
            await _run_sync(self.vector_store.delete_collection, coll_l3)
            l3_purged = -1

        # Reset collections setup cache for this tenant
        if coll_l2 in self._collections_setup:
            del self._collections_setup[coll_l2]
        if coll_l3 in self._collections_setup:
            del self._collections_setup[coll_l3]
        await _run_sync(self._setup_collections, tenant_id=tenant_id)

        logger.info(
            "cache_invalidated",
            tenant_id=tenant_id,
            l1_purged=l1_purged,
            l2_purged=l2_purged,
            l3_purged=l3_purged,
            filter=filter_dict,
        )

        return {
            "status": "success",
            "tenant_id": tenant_id,
            "filter": filter_dict,
            "l1_purged": l1_purged,
            "l2_purged": l2_purged,
            "l3_purged": l3_purged,
        }

    # ------------------------------------------------------------------
    # L5 — Context Cache (assembled RAG context)
    # ------------------------------------------------------------------

    def _build_l5_key(
        self,
        tenant_id: str,
        chunks_hash: str,
        template_version: str,
        token_budget: int,
        model_fingerprint: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """Build L5 context cache key."""
        model_fingerprint = model_fingerprint or self._compute_model_fingerprint(
            self.default_model, self.default_provider, self.default_model_params
        )
        provider = provider or self.default_provider
        return build_l5_key(tenant_id, chunks_hash, template_version, token_budget, model_fingerprint, provider)

    async def get_l5(
        self,
        query: str,
        chunks: List[dict],
        template_version: str,
        token_budget: int,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Get cached assembled context from L5.

        L5 is an exact-match layer (Hot Store). Key includes: tenant_id,
        chunks_hash, template_version, token_budget, model_fingerprint, provider.
        """
        chunks_hash = compute_chunks_hash(chunks)
        model_fingerprint = self._compute_model_fingerprint(model, provider, model_params)
        key = self._build_l5_key(
            tenant_id, chunks_hash, template_version, token_budget, model_fingerprint, provider
        )

        val = await _run_sync(self.exact_store.get, key)
        if not val:
            self._l5_stats["misses"] += 1
            return None

        try:
            entry = json.loads(val.decode())
        except Exception:
            self._l5_stats["misses"] += 1
            return None

        # Defense in depth: re-verify critical fields even though the key
        # already encodes them (protects against tampered/stale values).
        incoming_meta = {
            "tenant_id": tenant_id,
            "chunk_content_hashes": chunks_hash,
            "template_version": template_version,
            "token_budget": token_budget,
            "model_fingerprint": model_fingerprint,
            "provider": provider or self.default_provider,
        }
        allowed, gates_passed, gates_failed = hard_gate(  # type: ignore[misc]
            incoming_meta,
            entry.get("meta", {}),
            layer="L5",
            mode=GateMode.STRICT,
            schema=self.schema,
        )

        if allowed:
            self._l5_stats["hits"] += 1
            self._layer_stats["L5"] = self._layer_stats.get("L5", 0) + 1
            logger.info("l5_cache_hit", tenant_id=tenant_id, key=key)
            return entry.get("context")

        self._l5_stats["misses"] += 1
        return None

    async def set_l5(
        self,
        query: str,
        chunks: List[dict],
        context: str,
        template_version: str,
        token_budget: int,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_params: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> bool:
        """Store assembled context in L5 cache (Hot Store / exact match)."""
        chunks_hash = compute_chunks_hash(chunks)
        model_fingerprint = self._compute_model_fingerprint(model, provider, model_params)
        key = self._build_l5_key(
            tenant_id, chunks_hash, template_version, token_budget, model_fingerprint, provider
        )

        meta = {
            "tenant_id": tenant_id,
            "chunk_content_hashes": chunks_hash,
            "template_version": template_version,
            "token_budget": token_budget,
            "model_fingerprint": model_fingerprint,
            "provider": provider or self.default_provider,
            "l5_key": key,
        }

        entry = {
            "query": query,
            "context": context,
            "meta": meta,
        }

        return await _run_sync(
            self.exact_store.set,
            key,
            json.dumps(entry).encode(),
            ex=ttl if ttl is not None else self.l1_ttl,
        )

    def get_l5_stats(self) -> dict:
        """Get L5 context cache statistics."""
        total = self._l5_stats["hits"] + self._l5_stats["misses"]
        return {
            "hits": self._l5_stats["hits"],
            "misses": self._l5_stats["misses"],
            "hit_rate": (self._l5_stats["hits"] / total) if total > 0 else 0.0,
        }

    # ------------------------------------------------------------------
    # Phase 3: Layer-agnostic primitives for DecisionEngine
    # ------------------------------------------------------------------

    async def get_layer(self, layer: str, key: str) -> Optional[Any]:
        """
        Get a value from a specific cache layer by raw key.

        Used by DecisionEngine for layer-agnostic lookups.
        """
        if layer in ("L0a", "L1", "L4", "L5", "L6", "L8", "L9"):
            # Hot Store layers
            val = await _run_sync(self.exact_store.get, key)
            if val:
                try:
                    return json.loads(val.decode())
                except Exception:
                    return val
            return None
        elif layer in ("L0b", "L2", "L3", "L7"):
            # Vector Store layers - not directly keyed by simple string
            # These require vector search, not direct key lookup
            logger.warning("get_layer not supported for vector layer", layer=layer)
            return None
        else:
            logger.warning("unknown layer for get_layer", layer=layer)
            return None

    async def set_layer(self, layer: str, key: str, value: Any, ttl: int = 3600) -> bool:
        """
        Set a value in a specific cache layer by raw key.

        Used by DecisionEngine for layer-agnostic writes.
        """
        if layer in ("L0a", "L1", "L4", "L5", "L6", "L8", "L9"):
            # Hot Store layers
            data = json.dumps(value).encode() if not isinstance(value, bytes) else value
            return self.exact_store.set(key, data, ex=ttl)
        elif layer in ("L0b", "L2", "L3", "L7"):
            # Vector Store layers - not directly keyed by simple string
            logger.warning("set_layer not supported for vector layer", layer=layer)
            return False
        else:
            logger.warning("unknown layer for set_layer", layer=layer)
            return False

    async def invalidate_layer(self, layer: str, pattern: str) -> int:
        """
        Invalidate entries in a layer matching a pattern.

        Used by DecisionEngine for layer-agnostic invalidation.
        """
        if layer in ("L0a", "L1", "L4", "L5", "L6", "L8", "L9"):
            # Hot Store layers
            if hasattr(self.exact_store, "delete_prefix"):
                return await _run_sync(self.exact_store.delete_prefix, pattern)
            return 0
        elif layer in ("L0b", "L2", "L3", "L7"):
            # Vector Store layers - need collection name from pattern
            # Pattern format: "tenant:collection" or just "collection"
            logger.warning("invalidate_layer for vector layer requires collection", layer=layer)
            return 0
        else:
            logger.warning("unknown layer for invalidate_layer", layer=layer)
            return 0

    # Storage abstraction accessors
    @property
    def hot_store(self) -> BaseExactStore:
        """Access to Hot Store (exact/operational cache)."""
        return self.exact_store

    @property
    def vector_store_backend(self) -> BaseVectorStore:
        """Access to Vector Store (semantic/vector cache)."""
        return self.vector_store

    @property
    def durable_store(self):
        """Access to Durable Store (relational/metadata memory).

        Not yet implemented - returns None for now.
        """
        return None

    def record_decision_action(self, action: str, tenant_id: str) -> None:
        """Record a decision action for metrics."""
        record_request(action, self.agent_type, tenant_id)

    # ──────────────────────────────────────────────────────────────────────────────
    # Phase 5: Decision Trace Public API
    # ──────────────────────────────────────────────────────────────────────────────

    def get_decision_trace(self, request_id: str) -> Optional[dict]:
        """
        Retrieve a decision trace by request ID.

        Returns the trace as a dictionary suitable for JSON serialization,
        or None if no trace exists for the given request_id.
        """
        if self.decision_traces is None:
            return None
        trace = self.decision_traces.get_by_request_id(request_id)
        return trace.to_dict() if trace else None

    def get_decision_trace_by_id(self, trace_id: str) -> Optional[dict]:
        """Retrieve a decision trace by trace ID."""
        if self.decision_traces is None:
            return None
        trace = self.decision_traces.get_by_trace_id(trace_id)
        return trace.to_dict() if trace else None

    def get_decision_traces(
        self, tenant_id: Optional[str] = None, limit: int = 10
    ) -> List[dict]:
        """
        Get recent decision traces, optionally filtered by tenant.

        Returns a list of trace dictionaries, most recent first.
        """
        if self.decision_traces is None:
            return []
        traces = self.decision_traces.get_recent(tenant_id=tenant_id, limit=limit)
        return [t.to_dict() for t in traces]

    def get_decision_trace_stats(self) -> dict:
        """Get statistics about stored decision traces."""
        if self.decision_traces is None:
            return {"enabled": False, "total_traces": 0}
        stats = self.decision_traces.stats()
        stats["enabled"] = True
        return stats

    def clear_decision_traces(self) -> None:
        """Clear all stored decision traces."""
        if self.decision_traces is not None:
            self.decision_traces.clear()

