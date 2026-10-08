"""RAG Retriever with ICO-Cache L4 Retrieval Cache and provenance preservation."""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from ico_cache.backends.base import BaseExactStore
from ico_cache.core.decision_trace import LayerStatus, record_layer
from .embeddings import CachedEmbedder
from .vectorstore import RAGVectorStore


class RAGRetriever:
    """
    Retriever that consults ICO-Cache L4 retrieval cache before vector search.
    Enforces strict corpus_version and tenant_id isolation.
    """

    def __init__(
        self,
        vector_store: RAGVectorStore,
        embedder: CachedEmbedder,
        exact_store: Optional[BaseExactStore] = None,
        enable_l4_cache: bool = True,
        l4_ttl: int = 3600,
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.exact_store = exact_store
        self.enable_l4_cache = enable_l4_cache and (exact_store is not None)
        self.l4_ttl = l4_ttl

        # Telemetry counters
        self.retrieval_calls = 0
        self.retrieval_cache_hits = 0
        self.retrieval_cache_misses = 0
        self.retrieval_calls_avoided = 0
        self.total_retrieval_latency_ms = 0.0
        self.total_latency_saved_ms = 0.0
        self.baseline_retrieval_latency_ms = 15.0

    def _build_l4_key(
        self,
        query: str,
        tenant_id: str,
        top_k: int,
        corpus_version: str,
    ) -> str:
        """
        Build isolated L4 retrieval cache key:
        l4:{tenant_id}:{query_hash}:{corpus_version}:{retriever_version}:{top_k}
        """
        normalized = " ".join(query.lower().strip().split())
        query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        retriever_version = self.embedder.model_fingerprint
        return f"l4:{tenant_id}:{query_hash}:{corpus_version}:{retriever_version}:{top_k}"

    async def retrieve(
        self,
        query: str,
        corpus_version: str,
        tenant_id: str = "default",
        top_k: int = 5,
        record_trace: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant chunks for query with L4 caching."""
        self.retrieval_calls += 1
        t_start = time.perf_counter()

        l4_key = self._build_l4_key(query, tenant_id, top_k, corpus_version)

        # 1. Check L4 Retrieval Cache
        if self.enable_l4_cache and self.exact_store:
            try:
                cached_bytes = self.exact_store.get(l4_key)
                if cached_bytes:
                    cached_data = json.loads(cached_bytes.decode("utf-8"))
                    results = cached_data.get("results", [])
                    dur_ms = (time.perf_counter() - t_start) * 1000

                    self.retrieval_cache_hits += 1
                    self.retrieval_calls_avoided += 1
                    self.total_latency_saved_ms += max(0.0, self.baseline_retrieval_latency_ms - dur_ms)

                    if record_trace:
                        record_layer(
                            "L4",
                            LayerStatus.HIT,
                            reason=f"L4 retrieval cache hit for corpus {corpus_version}",
                            latency_ms=dur_ms,
                            hit=True,
                            cache_key=l4_key,
                            reuse_source="retrieval_cache",
                            metadata={"corpus_version": corpus_version, "num_chunks": len(results)},
                        )
                    return results
            except Exception:
                pass

        # 2. L4 Cache Miss: Embed query + search vector store
        self.retrieval_cache_misses += 1
        t_search_start = time.perf_counter()
        query_vector = self.embedder.embed(query, record_trace=record_trace)
        results = await self.vector_store.search(
            query_vector=query_vector,
            top_k=top_k,
            corpus_version=corpus_version,
            tenant_id=tenant_id,
        )
        dur_ms = (time.perf_counter() - t_start) * 1000
        self.total_retrieval_latency_ms += dur_ms
        self.baseline_retrieval_latency_ms = (self.baseline_retrieval_latency_ms * 0.9) + (dur_ms * 0.1)

        # 3. Store in L4 Cache
        if self.enable_l4_cache and self.exact_store:
            try:
                payload = {
                    "results": results,
                    "timestamp": time.time(),
                    "corpus_version": corpus_version,
                    "query": query,
                }
                self.exact_store.set(
                    l4_key,
                    json.dumps(payload).encode("utf-8"),
                    ex=self.l4_ttl,
                )
            except Exception:
                pass

        if record_trace:
            record_layer(
                "L4",
                LayerStatus.MISS,
                reason=f"L4 retrieval cache miss: executed vector search on {self.vector_store.db_type}",
                latency_ms=dur_ms,
                hit=False,
                cache_key=l4_key,
                metadata={"corpus_version": corpus_version, "num_chunks": len(results)},
            )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Returns retrieval telemetry metrics."""
        total = self.retrieval_calls
        hit_rate = (self.retrieval_cache_hits / total) if total > 0 else 0.0
        return {
            "retrieval_calls": self.retrieval_calls,
            "retrieval_cache_hits": self.retrieval_cache_hits,
            "retrieval_calls_avoided": self.retrieval_calls_avoided,
            "retrieval_hit_rate": round(hit_rate, 4),
            "total_retrieval_latency_ms": round(self.total_retrieval_latency_ms, 2),
            "total_latency_saved_ms": round(self.total_latency_saved_ms, 2),
        }