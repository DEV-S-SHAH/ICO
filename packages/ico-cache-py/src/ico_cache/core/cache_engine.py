"""
cache_engine.py — Generalized, dataset-agnostic, multi-tenant ICO-Cache CacheEngine.
"""

import hashlib
import json
import time
from typing import List, Optional

import structlog

from ..backends.base import BaseEmbedder, BaseExactStore, BaseVectorStore
from .metadata_guard import MetadataSchema, hard_gate

logger = structlog.get_logger("ico_cache.core.cache_engine")


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

        self._stats_hits = 0
        self._stats_misses = 0
        self._layer_stats = {"L1": 0, "L2": 0, "L3": 0, "MISS": 0}
        self._collections_setup: dict = {}

    def get_metrics(self) -> dict:
        total = self._stats_hits + self._stats_misses
        return {
            "hits": self._stats_hits,
            "misses": self._stats_misses,
            "hit_rate": (self._stats_hits / total) if total > 0 else 0.0,
            "layer_stats": dict(self._layer_stats),
            "threshold_semantic": self.thresh_semantic,
        }

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

    def _l1_key(self, query: str, meta: dict, tenant_id: str = "default") -> str:
        normalized = self._normalize(query)
        suffix = _canonical_meta_suffix(meta)
        raw = normalized + suffix
        return f"{tenant_id}:l1:" + hashlib.sha256(raw.encode()).hexdigest()

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
        self, query: str, meta: Optional[dict] = None, tenant_id: str = "default"
    ) -> Optional[dict]:
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id)
        val = self.exact_store.get(key)
        if val:
            return json.loads(val.decode())
        return None

    def set_l1(
        self,
        query: str,
        response: dict,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
    ):
        effective_meta = self._auto_meta(query, meta)
        key = self._l1_key(query, effective_meta, tenant_id=tenant_id)
        self.exact_store.set(key, json.dumps(response).encode(), ex=self.l1_ttl)

    # ------------------------------------------------------------------
    # L2 — semantic / vector
    # ------------------------------------------------------------------

    async def get_l2(
        self, query: str, meta: Optional[dict] = None, tenant_id: str = "default"
    ):
        self._setup_collections(tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)
        emb = self.embedder.embed(query)

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
        self._setup_collections(tenant_id=tenant_id)
        coll_l2 = self._coll_name("l2_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        emb = self.embedder.embed(query)

        payload: dict = {"query": query, "answer": generated, "meta": effective_meta}
        if self.tenant_isolation_mode == "payload":
            payload["tenant_id"] = tenant_id

        await self.vector_store.insert(
            collection=coll_l2,
            id=hash(tenant_id + query + _canonical_meta_suffix(effective_meta)) % (10**10),
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
        self._setup_collections(tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        if not context or not context.strip():
            return None

        effective_meta = self._auto_meta(query, meta)
        q_filter = self.build_meta_filter(effective_meta, tenant_id=tenant_id)

        emb_q = self.embedder.embed(query)
        emb_c = self.embedder.embed(context)

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
        self._setup_collections(tenant_id=tenant_id)
        coll_l3 = self._coll_name("l3_cache", tenant_id)
        effective_meta = self._auto_meta(query, meta)
        ctx_meta = self.schema.extract(context) if self.schema else {}
        full_meta = {**effective_meta, **{k: v for k, v in ctx_meta.items() if v is not None}}

        emb_q = self.embedder.embed(query)
        emb_c = self.embedder.embed(context)

        key_raw = tenant_id + ":" + query + ":" + context + _canonical_meta_suffix(full_meta)
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
            id=hash(key_raw) % (10**10),
            vector={"query": emb_q, "context": emb_c},
            payload=payload,
        )

    # ------------------------------------------------------------------
    # Public resolve
    # ------------------------------------------------------------------

    async def resolve(
        self,
        query: str,
        context: Optional[str] = None,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
    ):
        t0 = time.perf_counter()

        t_l1_start = time.perf_counter()
        res = await self.get_l1(query, meta, tenant_id=tenant_id)
        t_l1_ms = (time.perf_counter() - t_l1_start) * 1000
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

        t_l2_start = time.perf_counter()
        res2 = await self.get_l2(query, meta, tenant_id=tenant_id)
        t_l2_ms = (time.perf_counter() - t_l2_start) * 1000
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

        t_l3_start = time.perf_counter()
        res3 = await self.get_l3(query, context, meta, tenant_id=tenant_id)
        t_l3_ms = (time.perf_counter() - t_l3_start) * 1000
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
