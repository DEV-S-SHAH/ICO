"""
cache_engine.py — Generalized, dataset-agnostic, multi-tenant ICO-Cache CacheEngine.
"""

import asyncio
import functools
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import structlog

from ..backends.base import BaseEmbedder, BaseExactStore, BaseVectorStore
from ..telemetry.metrics import (
    inflight_dec,
    inflight_inc,
    record_generation,
    record_lookup,
)
from ..telemetry.tracing import trace_cache_lookup
from .decision_engine import (
    build_l1_key,
    canonical_meta_suffix,
    context_hash,
)
from .metadata_guard import MetadataSchema, hard_gate

logger = structlog.get_logger("ico_cache.core.cache_engine")

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
        # Phase 3: New parameters for DecisionEngine integration
        default_model: str = "gpt-4o",
        default_provider: str = "openai",
        default_prompt_version: str = "v1",
        default_model_params: Optional[Dict[str, Any]] = None,
    ):
        self.embedder = embedder
        self.vector_store = vector_store
        self.exact_store = exact_store
        self.schema = schema or MetadataSchema()
        self.tenant_isolation_mode = tenant_isolation_mode

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

    def _auto_meta(self, text: str, explicit_meta: Optional[dict] = None) -> dict:
        auto = self.schema.extract(text) if self.schema else {}
        merged = {k: v for k, v in auto.items() if v is not None}
        if explicit_meta:
            merged.update({k: v for k, v in explicit_meta.items() if v is not None})
        return merged

    def _l1_key(
        self,
        query: str,
        meta: dict,
        tenant_id: str = "default",
        model: Optional[str] = None,
        provider: Optional[str] = None,
        prompt_version: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        """
        Build L1 key per Phase 3 spec:
        {tenant_id}:l1:sha256(normalized_query + "|" + model_fingerprint + "|" + provider + "|" + prompt_version + "|" + context_hash + "|" + canonical_meta_suffix)
        """
        normalized = self._normalize(query)
        suffix = canonical_meta_suffix(meta)

        # Use provided values or defaults
        model = model or self.default_model
        provider = provider or self.default_provider
        prompt_version = prompt_version or self.default_prompt_version

        # Compute model fingerprint: sha256(model + provider + deterministic_params)[:12]
        deterministic_params = {
            k: v for k, v in self.default_model_params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed")
        }
        model_fp_raw = f"{model}|{provider}|{str(sorted(deterministic_params.items()))}"
        model_fingerprint = hashlib.sha256(model_fp_raw.encode()).hexdigest()[:12]

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

    def _update_adaptive_threshold(self, hit: bool):
        if not self.adaptive_threshold:
            return
        if hit:
            self._stats_hits += 1
        else:
            self._stats_misses += 1
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
    ) -> Optional[dict]:
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context)
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
        nx: bool = False,
    ) -> bool:
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context)
        return self.exact_store.set(
            key, json.dumps(response).encode(), ex=self.l1_ttl, nx=nx
        )

    # ------------------------------------------------------------------
    # L2 — semantic / vector
    # ------------------------------------------------------------------

    async def get_l2(
        self, query: str, meta: Optional[dict] = None, tenant_id: str = "default"
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)
        emb = await _run_sync(self.embedder.embed, query)

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
            if hard_gate(effective_meta, cached_meta, self.metadata_filter_keys):
                return payload.get("answer")
        return None

    async def async_write_l2(
        self,
        query: str,
        generated: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        emb = await _run_sync(self.embedder.embed, query)

        payload: dict = {"query": query, "answer": generated, "meta": effective_meta}
        if self.tenant_isolation_mode == "payload":
            payload["tenant_id"] = tenant_id

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
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        if not context or not context.strip():
            return None

        effective_meta = self._auto_meta(query, meta)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)

        emb_q = await _run_sync(self.embedder.embed, query)
        emb_c = await _run_sync(self.embedder.embed, context)

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

                if hard_gate(full_incoming_meta, full_cached_meta, self.metadata_filter_keys):
                    return cached_payload.get("answer")
        return None

    async def async_write_l3(
        self,
        query: str,
        context: str,
        generated: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
    ):
        await _run_sync(self._setup_collections, tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        ctx_meta = self.schema.extract(context) if self.schema else {}
        full_meta = {**effective_meta, **{k: v for k, v in ctx_meta.items() if v is not None}}

        emb_q = await _run_sync(self.embedder.embed, query)
        emb_c = await _run_sync(self.embedder.embed, context)

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
    ):
        t0 = time.perf_counter()

        # L1 Lookup
        with trace_cache_lookup("L1", tenant_id=tenant_id, query=query) as rec_l1:
            t_l1_start = time.perf_counter()
            res = await self._safe_lookup(
                "L1", self.get_l1(query, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context)
            )
            t_l1_ms = (time.perf_counter() - t_l1_start) * 1000
            rec_l1.record_result(hit=res is not None)
            record_lookup("L1", res is not None, t_l1_ms / 1000)
            if res:
                self._update_adaptive_threshold(True)
                self._layer_stats["L1"] += 1
                logger.info(
                    "cache_hit",
                    layer="L1",
                    tenant_id=tenant_id,
                    query=query,
                    latency_ms=round(t_l1_ms, 3),
                )
                return {"source": "L1", "response": res}

        # L2 Lookup
        with trace_cache_lookup("L2", tenant_id=tenant_id, query=query) as rec_l2:
            t_l2_start = time.perf_counter()
            res2 = await self._safe_lookup(
                "L2", self.get_l2(query, meta, tenant_id=tenant_id)
            )
            t_l2_ms = (time.perf_counter() - t_l2_start) * 1000
            rec_l2.record_result(hit=res2 is not None)
            record_lookup("L2", res2 is not None, t_l2_ms / 1000)
            if res2:
                self._update_adaptive_threshold(True)
                self._layer_stats["L2"] += 1
                logger.info(
                    "cache_hit",
                    layer="L2",
                    tenant_id=tenant_id,
                    query=query,
                    latency_ms=round(t_l2_ms, 3),
                )
                return {"source": "L2", "response": res2}

        # L3 Lookup
        with trace_cache_lookup("L3", tenant_id=tenant_id, query=query) as rec_l3:
            t_l3_start = time.perf_counter()
            res3 = await self._safe_lookup(
                "L3", self.get_l3(query, context, meta, tenant_id=tenant_id)
            )
            t_l3_ms = (time.perf_counter() - t_l3_start) * 1000
            rec_l3.record_result(hit=res3 is not None)
            record_lookup("L3", res3 is not None, t_l3_ms / 1000)
            if res3:
                self._update_adaptive_threshold(True)
                self._layer_stats["L3"] += 1
                logger.info(
                    "cache_hit",
                    layer="L3",
                    tenant_id=tenant_id,
                    query=query,
                    latency_ms=round(t_l3_ms, 3),
                )
                return {"source": "L3", "response": res3}

        total_ms = (time.perf_counter() - t0) * 1000
        self._update_adaptive_threshold(False)
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
        return {"source": "MISS", "response": None}

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
    ) -> dict:
        """
        Cache lookup; on MISS, run ``generate_fn`` under single-flight so that
        concurrent identical misses trigger exactly one generation. Only
        successful (cacheable) results are written, and writes are conditional
        so an already-populated entry is never overwritten.
        """
        res = await self.resolve(query, context, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version)
        if res["source"] != "MISS" or generate_fn is None:
            return res

        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context)

        existing = self._inflight.get(key)
        if existing is not None:
            # Join the in-progress generation instead of starting a new one.
            return await asyncio.shield(existing)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._inflight[key] = future
        try:
            result = await self._generate_and_store(
                query, context, meta, tenant_id, generate_fn, model=model, provider=provider, prompt_version=prompt_version
            )
            if not future.done():
                future.set_result(result)
            return result
        except BaseException:
            # Includes CancelledError. Resolve waiters (so they never hang) and
            # re-raise for the leader. Waiters degrade to a miss rather than
            # sharing the failure.
            if not future.done():
                future.set_result({"source": "MISS", "response": None})
            raise
        finally:
            self._inflight.pop(key, None)

    async def _generate_and_store(
        self, query, context, meta, tenant_id, generate_fn, model=None, provider=None, prompt_version=None
    ) -> dict:
        # Conditional double-check: another writer may have populated the entry
        # while this coroutine was waiting to become the leader.
        existing = await self.get_l1(query, meta, tenant_id=tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context)
        if existing is not None:
            return {"source": "L1", "response": existing}

        inflight_inc()
        t_gen = time.perf_counter()
        try:
            generated = await generate_fn()
        finally:
            record_generation(time.perf_counter() - t_gen)
            inflight_dec()

        if not self._is_cacheable(generated):
            return {"source": "MISS", "response": generated}

        if await self.get_l1(query, meta, tenant_id=tenant_id) is not None:
            # Someone else won the race; do not overwrite.
            return {"source": "MISS", "response": generated}

        await _run_sync(self.set_l1, query, generated, meta, tenant_id, model=model, provider=provider, prompt_version=prompt_version, context=context, nx=True)
        await self.async_write_l2(query, generated, meta=meta, tenant_id=tenant_id)
        if context:
            await self.async_write_l3(
                query, context, generated, meta=meta, tenant_id=tenant_id
            )
        return {"source": "MISS", "response": generated}

    async def invalidate(
        self, tenant_id: str = "default", filter_dict: Optional[dict] = None
    ) -> dict:
        """
        Purges matching entries from L1, L2, and L3 for a tenant.
        """
        # 1. Purge L1
        l1_purged = 0
        if hasattr(self.exact_store, "delete_prefix"):
            l1_purged = await _run_sync(self.exact_store.delete_prefix, f"{tenant_id}:")

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

