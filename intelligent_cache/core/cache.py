"""IntelligentCache main orchestrator."""

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional, Sequence, Union

from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.backends.factory import create_backend
from intelligent_cache.config import CacheConfig
from intelligent_cache.core.entry import CacheEntry, CacheHitType, CacheResult
from intelligent_cache.core.key import generate_key
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.embeddings.factory import create_embedder
from intelligent_cache.intelligence.invalidation import InvalidationManager
from intelligent_cache.intelligence.scorer import CachePolicyScorer
from intelligent_cache.metrics.collector import CacheStats, MetricsCollector

logger = logging.getLogger(__name__)


class IntelligentCache:
    """Production-grade Intelligent Multi-Level Cache for LLM and AI applications.
    
    Provides exact-match caching, semantic similarity caching, intelligent TTL scoring,
    thread-safe & async operations, multi-backend persistence, and metrics collection.
    """

    def __init__(
        self,
        backend: Union[str, BaseStorageBackend, None] = None,
        embedder: Union[str, BaseEmbedder, Callable[[str], list[float]], None] = None,
        similarity_threshold: Optional[float] = None,
        default_ttl: Optional[int] = None,
        namespace: Optional[str] = None,
        config: Optional[CacheConfig] = None,
        **kwargs: Any,
    ):
        self.config = config or CacheConfig()

        # Apply overrides
        if similarity_threshold is not None:
            self.config.similarity_threshold = similarity_threshold
        if default_ttl is not None:
            self.config.default_ttl = default_ttl
        if namespace is not None:
            self.config.namespace = namespace

        # Instantiate backend and embedder
        backend_arg = backend if backend is not None else self.config.backend
        self.backend = create_backend(backend_arg, config=self.config, **kwargs)

        embedder_arg = embedder if embedder is not None else self.config.embedder
        self.embedder = create_embedder(
            embedder_arg,
            model_name=self.config.embedding_model,
            **kwargs,
        )

        # Scorer, metrics, invalidator
        self.scorer = CachePolicyScorer(
            default_ttl=self.config.default_ttl or 3600,
        )
        self.metrics = MetricsCollector(
            cost_per_1k_prompt_tokens=self.config.cost_per_1k_prompt_tokens,
            cost_per_1k_completion_tokens=self.config.cost_per_1k_completion_tokens,
        )
        self.invalidator = InvalidationManager(self.backend, self.embedder)

        # Track query frequency for policy scoring
        self._query_frequencies: dict[str, int] = {}

    def get(
        self,
        query: str,
        namespace: Optional[str] = None,
        threshold: Optional[float] = None,
        exact_only: bool = False,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> Optional[CacheResult]:
        """Look up a cached response by exact match or semantic similarity."""
        if not self.config.enabled:
            return None

        ns = namespace or self.config.namespace
        thresh = threshold if threshold is not None else self.config.similarity_threshold

        # Update frequency tracker
        norm_q = query.strip().lower()
        freq = self._query_frequencies.get(norm_q, 0) + 1
        self._query_frequencies[norm_q] = freq

        # 1. Exact Match
        if self.config.exact_match_enabled:
            key = generate_key(query, namespace=ns, extra_params=extra_params)
            try:
                entry = self.backend.get(key)
                if entry is not None:
                    self.metrics.record_hit(
                        hit_type=CacheHitType.EXACT,
                        latency_ms=entry.latency_ms,
                        prompt_tokens=entry.prompt_tokens,
                        completion_tokens=entry.completion_tokens,
                        namespace=ns,
                    )
                    return CacheResult(
                        value=entry.value,
                        hit_type=CacheHitType.EXACT,
                        similarity_score=1.0,
                        latency_saved_ms=entry.latency_ms,
                        key=key,
                        metadata=entry.metadata,
                        prompt_tokens_saved=entry.prompt_tokens,
                        completion_tokens_saved=entry.completion_tokens,
                    )
            except Exception as exc:
                if not self.config.graceful_fallback:
                    raise
                logger.warning("Backend exact match lookup failed: %s", exc)

        # 2. Semantic Similarity Match
        if not exact_only and self.config.semantic_match_enabled:
            try:
                query_vec = self.embedder.embed(query)
                matches = self.backend.search_similarity(
                    query_vector=query_vec,
                    threshold=thresh,
                    top_k=1,
                    namespace=ns,
                    metric=self.config.similarity_metric,
                )
                if matches:
                    best_entry, sim_score = matches[0]
                    best_entry.touch()
                    self.metrics.record_hit(
                        hit_type=CacheHitType.SEMANTIC,
                        latency_ms=best_entry.latency_ms,
                        prompt_tokens=best_entry.prompt_tokens,
                        completion_tokens=best_entry.completion_tokens,
                        namespace=ns,
                    )
                    return CacheResult(
                        value=best_entry.value,
                        hit_type=CacheHitType.SEMANTIC,
                        similarity_score=round(sim_score, 4),
                        latency_saved_ms=best_entry.latency_ms,
                        key=best_entry.key,
                        metadata=best_entry.metadata,
                        prompt_tokens_saved=best_entry.prompt_tokens,
                        completion_tokens_saved=best_entry.completion_tokens,
                    )
            except Exception as exc:
                if not self.config.graceful_fallback:
                    raise
                logger.warning("Backend semantic match lookup failed: %s", exc)

        # Cache Miss
        self.metrics.record_miss(namespace=ns)
        return None

    def set(
        self,
        query: str,
        value: Any,
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        apply_policy: bool = True,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Store a query-response pair in the cache with policy scoring and embedding."""
        if not self.config.enabled:
            return False

        ns = namespace or self.config.namespace
        final_ttl = ttl if ttl is not None else self.config.default_ttl

        # Apply intelligent caching policy
        if apply_policy:
            norm_q = query.strip().lower()
            freq = self._query_frequencies.get(norm_q, 1)
            policy = self.scorer.compute_decision(
                query=query,
                response=value,
                frequency=freq,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            if policy["decision"] == "DO_NOT_CACHE":
                logger.debug("Policy chose DO_NOT_CACHE for query: %s", query[:50])
                return False
            if ttl is None:
                final_ttl = policy["recommended_ttl"]

        key = generate_key(query, namespace=ns, extra_params=extra_params)

        # Compute embedding if semantic caching enabled
        embedding: Optional[list[float]] = None
        if self.config.semantic_match_enabled:
            try:
                embedding = self.embedder.embed(query)
            except Exception as exc:
                if not self.config.graceful_fallback:
                    raise
                logger.warning("Embedding generation failed: %s", exc)

        entry = CacheEntry(
            key=key,
            query=query,
            value=value,
            embedding=embedding,
            namespace=ns,
            tags=tags or [],
            metadata=metadata or {},
            created_at=time.time(),
            last_accessed=time.time(),
            expires_at=(time.time() + final_ttl) if (final_ttl and final_ttl > 0) else None,
            hit_count=0,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

        try:
            return self.backend.set(key, entry, ttl=final_ttl)
        except Exception as exc:
            if not self.config.graceful_fallback:
                raise
            logger.warning("Backend set failed for key '%s': %s", key, exc)
            return False

    def get_or_compute(
        self,
        query: str,
        compute_fn: Callable[[], Any],
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
        threshold: Optional[float] = None,
        exact_only: bool = False,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        extra_params: Optional[dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Any:
        """Get cached response, or compute via `compute_fn`, store, and return."""
        hit = self.get(
            query=query,
            namespace=namespace,
            threshold=threshold,
            exact_only=exact_only,
            extra_params=extra_params,
        )
        if hit is not None:
            return hit.value

        start_time = time.perf_counter()
        result = compute_fn()
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        self.set(
            query=query,
            value=result,
            ttl=ttl,
            namespace=namespace,
            tags=tags,
            metadata=metadata,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            extra_params=extra_params,
        )
        return result

    async def aget(
        self,
        query: str,
        namespace: Optional[str] = None,
        threshold: Optional[float] = None,
        exact_only: bool = False,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> Optional[CacheResult]:
        """Async version of `get`."""
        return await asyncio.to_thread(
            self.get,
            query=query,
            namespace=namespace,
            threshold=threshold,
            exact_only=exact_only,
            extra_params=extra_params,
        )

    async def aset(
        self,
        query: str,
        value: Any,
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        apply_policy: bool = True,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Async version of `set`."""
        return await asyncio.to_thread(
            self.set,
            query=query,
            value=value,
            ttl=ttl,
            namespace=namespace,
            tags=tags,
            metadata=metadata,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            apply_policy=apply_policy,
            extra_params=extra_params,
        )

    async def aget_or_compute(
        self,
        query: str,
        compute_fn: Union[Callable[[], Any], Callable[[], Coroutine[Any, Any, Any]]],
        ttl: Optional[int] = None,
        namespace: Optional[str] = None,
        threshold: Optional[float] = None,
        exact_only: bool = False,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        extra_params: Optional[dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Any:
        """Async version of `get_or_compute`."""
        hit = await self.aget(
            query=query,
            namespace=namespace,
            threshold=threshold,
            exact_only=exact_only,
            extra_params=extra_params,
        )
        if hit is not None:
            return hit.value

        start_time = time.perf_counter()
        if asyncio.iscoroutinefunction(compute_fn):
            result = await compute_fn()
        else:
            result = compute_fn()
            if asyncio.iscoroutine(result):
                result = await result

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        await self.aset(
            query=query,
            value=result,
            ttl=ttl,
            namespace=namespace,
            tags=tags,
            metadata=metadata,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            extra_params=extra_params,
        )
        return result

    def invalidate(
        self,
        key: Optional[str] = None,
        query: Optional[str] = None,
        namespace: Optional[str] = None,
        tag: Optional[str] = None,
        semantic_query: Optional[str] = None,
        radius: float = 0.85,
    ) -> int:
        """Invalidate entries across key, query, namespace, tag, or semantic radius."""
        return self.invalidator.invalidate(
            key=key,
            query=query,
            namespace=namespace,
            tag=tag,
            semantic_query=semantic_query,
            radius=radius,
        )

    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear the cache entirely, or clear a specific namespace."""
        self.backend.clear(namespace=namespace)

    def stats(self) -> CacheStats:
        """Return analytics and hit/miss statistics."""
        return self.metrics.get_stats()

    def backend_stats(self) -> dict[str, Any]:
        """Return storage backend statistics."""
        return self.backend.stats()

    def close(self) -> None:
        """Close backend connections and release resources."""
        self.backend.close()
