"""Embedding provider with ICO-Cache L0b embedding cache integration."""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from ico_cache.backends.base import BaseEmbedder, BaseExactStore
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.core.decision_engine import build_l0b_key
from ico_cache.core.decision_trace import LayerStatus, record_layer


class CachedEmbedder:
    """
    Embedding wrapper that routes calls through ICO-Cache L0b embedding cache.
    Tracks embedding calls, hits, calls avoided, latency, and savings.
    """

    def __init__(
        self,
        base_embedder: Optional[BaseEmbedder] = None,
        exact_store: Optional[BaseExactStore] = None,
        model_name: str = "BAAI/bge-small-en-v1.5",
        enable_cache: bool = True,
        ttl: int = 2592000,  # 30 days
    ):
        self.model_name = model_name
        self.embedder = base_embedder or FastEmbedder(model_name=model_name)
        self.exact_store = exact_store
        self.enable_cache = enable_cache
        self.ttl = ttl
        self.model_fingerprint = f"{model_name}@1.0.0"

        # Telemetry counters
        self.embedding_calls = 0
        self.embedding_cache_hits = 0
        self.embedding_calls_avoided = 0
        self.total_embedding_latency_ms = 0.0
        self.total_latency_saved_ms = 0.0
        self.baseline_embed_latency_ms = 25.0  # Estimated baseline latency

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def embed(self, text: str, record_trace: bool = True) -> List[float]:
        """Generate embedding for single text, utilizing L0b cache."""
        self.embedding_calls += 1
        t_start = time.perf_counter()

        cache_key = None
        if self.enable_cache and self.exact_store:
            cache_key = build_l0b_key(self.model_fingerprint, text)
            try:
                cached_bytes = self.exact_store.get(cache_key)
                if cached_bytes:
                    vector = json.loads(cached_bytes.decode("utf-8"))
                    dur_ms = (time.perf_counter() - t_start) * 1000
                    self.embedding_cache_hits += 1
                    self.embedding_calls_avoided += 1
                    self.total_latency_saved_ms += max(0.0, self.baseline_embed_latency_ms - dur_ms)

                    if record_trace:
                        record_layer(
                            "L0b",
                            LayerStatus.HIT,
                            reason=f"L0b embedding cache hit ({self.model_name})",
                            latency_ms=dur_ms,
                            hit=True,
                            cache_key=cache_key,
                            reuse_source="embedding_cache",
                        )
                    return vector
            except Exception:
                pass

        # Cache miss - compute embedding
        vector = self.embedder.embed(text)
        dur_ms = (time.perf_counter() - t_start) * 1000
        self.total_embedding_latency_ms += dur_ms
        self.baseline_embed_latency_ms = (self.baseline_embed_latency_ms * 0.9) + (dur_ms * 0.1)

        # Cache write
        if self.enable_cache and self.exact_store and cache_key:
            try:
                self.exact_store.set(
                    cache_key,
                    json.dumps(vector).encode("utf-8"),
                    ex=self.ttl,
                )
            except Exception:
                pass

        if record_trace:
            record_layer(
                "L0b",
                LayerStatus.MISS,
                reason=f"L0b embedding cache miss: computed embedding ({self.model_name})",
                latency_ms=dur_ms,
                hit=False,
                cache_key=cache_key,
            )

        return vector

    def embed_batch(self, texts: List[str], record_trace: bool = False) -> List[List[float]]:
        """Batch embedding with per-item L0b cache lookup."""
        return [self.embed(t, record_trace=record_trace) for t in texts]

    def get_stats(self) -> Dict[str, Any]:
        """Returns embedding telemetry metrics."""
        total = self.embedding_calls
        hit_rate = (self.embedding_cache_hits / total) if total > 0 else 0.0
        return {
            "embedding_calls": self.embedding_calls,
            "embedding_cache_hits": self.embedding_cache_hits,
            "embedding_calls_avoided": self.embedding_calls_avoided,
            "embedding_hit_rate": round(hit_rate, 4),
            "total_embedding_latency_ms": round(self.total_embedding_latency_ms, 2),
            "total_latency_saved_ms": round(self.total_latency_saved_ms, 2),
            "model_name": self.model_name,
            "model_fingerprint": self.model_fingerprint,
        }