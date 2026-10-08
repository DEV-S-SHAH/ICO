import asyncio
import functools
import hashlib
import json
import time
import uuid
from typing import Any, List, Optional
import litellm
from ..backends.base import BaseEmbedder, BaseVectorStore, BaseExactStore
from ..telemetry.metrics import record_generation, record_tokens, record_cost, record_latency
from ..telemetry.tracing import trace_rag_fallback
from ..telemetry.accounting import (
    AccountingContext,
    CacheLayer,
    DecisionAction,
    record_usage,
)
from ..telemetry.cost_model import get_cost_model
from ..core.decision_engine import build_l5_key, compute_chunks_hash
from ..core.decision_trace import (
    LayerStatus,
    record_layer,
)


def validate_model_spec(model: str) -> None:
    """Validates that model string is non-empty and well-formed for litellm."""
    if not model or not isinstance(model, str) or not model.strip():
        raise ValueError("LLM model string must be a non-empty string.")


async def _run_sync(fn, *args, **kwargs):
    """Run a blocking callable in a worker thread so it never blocks the loop."""
    if kwargs:
        fn = functools.partial(fn, **kwargs)
    return await asyncio.to_thread(fn, *args)


class RAGPipeline:
    def __init__(
        self,
        dense_embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        metadata_filter_keys: Optional[List[str]] = None,
        filtered_threshold: float = -8.50,
        unfiltered_threshold: float = 0.10,
        collection_name: str = "rag_corpus",
        reranker: Any = None,
        model: str = "gemini/gemini-flash-latest",
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        num_retries: int = 3,
        langfuse: Any = None,
        # Accounting configuration
        enable_accounting: bool = True,
        tenant_id: str = "default",
        provider: str = "gemini",
        # L4 Retrieval Cache configuration
        exact_store: Optional[BaseExactStore] = None,
        enable_l4_cache: bool = True,
        l4_ttl: int = 3600,  # 1 hour default
        corpus_version: str = "v1",
        # L5 Context Cache configuration
        enable_l5_cache: bool = True,
        prompt_template_version: str = "v1",
        token_budget: int = 4000,
    ):
        validate_model_spec(model)
        self.dense_embedder = dense_embedder
        self.vector_store = vector_store
        self.metadata_filter_keys = metadata_filter_keys or []

        self.filtered_threshold = filtered_threshold
        self.unfiltered_threshold = unfiltered_threshold
        self.collection_name = collection_name
        self.reranker = reranker
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.timeout = timeout
        self.num_retries = num_retries
        self.langfuse = langfuse

        # Accounting
        self.enable_accounting = enable_accounting
        self.default_tenant_id = tenant_id
        self.provider = provider
        self.cost_model = get_cost_model()

        # L4 Retrieval Cache
        self.exact_store = exact_store
        self.enable_l4_cache = enable_l4_cache and exact_store is not None
        self.l4_ttl = l4_ttl
        self.corpus_version = corpus_version
        self._l4_stats = {"hits": 0, "misses": 0}
        self._l4_inflight: dict = {}  # Single-flight for L4 retrieval

        # L5 Context Cache
        self.enable_l5_cache = enable_l5_cache and exact_store is not None
        self.prompt_template_version = prompt_template_version
        self.token_budget = token_budget
        self._l5_stats = {"hits": 0, "misses": 0}

    def _has_active_filters(self, meta: dict) -> bool:
        return any(k in meta for k in self.metadata_filter_keys)

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: ~4 chars per token."""
        return max(len(text) // 4, 1)

    def _build_l4_key(
        self,
        query: str,
        tenant_id: str,
        top_k: int,
        meta: Optional[dict] = None,
        corpus_version: Optional[str] = None,
    ) -> str:
        """
        Build L4 retrieval cache key with complete isolation:
        - tenant_id
        - query/embedding fingerprint
        - corpus_version
        - retriever_version (embedding model)
        - filters (metadata)
        - top_k
        - reranker_config/version
        """
        # Normalize query for consistent cache keys
        normalized_query = " ".join(query.lower().strip().split())

        # Query hash
        query_hash = hashlib.sha256(normalized_query.encode()).hexdigest()[:16]

        # Retriever version (embedding model version)
        retriever_version = getattr(self.dense_embedder, 'model_version', 'default')

        # Metadata filter fingerprint
        meta = meta or {}
        active_filters = {k: v for k, v in meta.items() if k in self.metadata_filter_keys and v is not None}
        filter_str = "&".join(f"{k}={v}" for k, v in sorted(active_filters.items())) if active_filters else "none"
        filter_hash = hashlib.sha256(filter_str.encode()).hexdigest()[:8]

        # Reranker config fingerprint
        if self.reranker:
            reranker_id = f"{type(self.reranker).__name__}:{getattr(self.reranker, 'version', 'v1')}"
        else:
            reranker_id = "none"
        reranker_hash = hashlib.sha256(reranker_id.encode()).hexdigest()[:8]

        # Corpus version
        corpus_v = corpus_version or self.corpus_version

        # Build composite key: l4:{tenant}:{query_hash}:{corpus_v}:{retriever_v}:{filter_hash}:{top_k}:{reranker_hash}
        key = f"l4:{tenant_id}:{query_hash}:{corpus_v}:{retriever_version}:{filter_hash}:{top_k}:{reranker_hash}"
        return key

    async def _get_l4_cached_retrieval(
        self,
        query: str,
        tenant_id: str,
        top_k: int,
        meta: Optional[dict] = None,
        corpus_version: Optional[str] = None,
    ) -> Optional[List[dict]]:
        """Get cached retrieval results from L4 cache."""
        if not self.enable_l4_cache or not self.exact_store:
            return None

        key = self._build_l4_key(query, tenant_id, top_k, meta, corpus_version)

        try:
            val = await _run_sync(self.exact_store.get, key)
            if val:
                cached_data = json.loads(val.decode())
                self._l4_stats["hits"] += 1
                return cached_data.get("results", [])
        except Exception:
            pass

        self._l4_stats["misses"] += 1
        return None

    async def _set_l4_cached_retrieval(
        self,
        query: str,
        tenant_id: str,
        top_k: int,
        results: List[dict],
        meta: Optional[dict] = None,
        corpus_version: Optional[str] = None,
    ) -> bool:
        """Store retrieval results in L4 cache."""
        if not self.enable_l4_cache or not self.exact_store:
            return False

        key = self._build_l4_key(query, tenant_id, top_k, meta, corpus_version)

        try:
            cached_data = {
                "results": results,
                "timestamp": time.time(),
                "corpus_version": corpus_version or self.corpus_version,
            }
            return self.exact_store.set(
                key,
                json.dumps(cached_data).encode(),
                ex=self.l4_ttl,
                nx=False,  # Allow overwrite
            )
        except Exception:
            return False

    def get_l4_stats(self) -> dict:
        """Get L4 retrieval cache statistics."""
        total = self._l4_stats["hits"] + self._l4_stats["misses"]
        return {
            "hits": self._l4_stats["hits"],
            "misses": self._l4_stats["misses"],
            "hit_rate": (self._l4_stats["hits"] / total) if total > 0 else 0.0,
        }

    def get_l5_stats(self) -> dict:
        """Get L5 context cache statistics."""
        total = self._l5_stats["hits"] + self._l5_stats["misses"]
        return {
            "hits": self._l5_stats["hits"],
            "misses": self._l5_stats["misses"],
            "hit_rate": (self._l5_stats["hits"] / total) if total > 0 else 0.0,
        }

    # ──────────────────────────────────────────────────────────────────────────────
    # L5 Context Cache Methods
    # ──────────────────────────────────────────────────────────────────────────────

    def _build_l5_key(
        self,
        chunks: List[dict],
        template_version: str,
        token_budget: int,
        tenant_id: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """
        Build L5 context cache key with complete isolation:
        - tenant_id
        - chunk_content_hashes (deterministic hash of chunk contents)
        - template_version
        - token_budget
        - model_fingerprint
        - provider
        """
        chunks_hash = compute_chunks_hash(chunks)
        model_fp = model or self.model
        prov = provider or self.provider
        return build_l5_key(tenant_id, chunks_hash, template_version, token_budget, model_fp, prov)

    async def _get_l5_cached_context(
        self,
        chunks: List[dict],
        template_version: str,
        token_budget: int,
        tenant_id: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        """Get cached assembled context from L5 cache."""
        if not self.enable_l5_cache or not self.exact_store:
            return None

        key = self._build_l5_key(chunks, template_version, token_budget, tenant_id, model, provider)

        try:
            val = await _run_sync(self.exact_store.get, key)
            if val:
                cached_data = json.loads(val.decode())
                self._l5_stats["hits"] += 1
                return cached_data.get("context")
        except Exception:
            pass

        self._l5_stats["misses"] += 1
        return None

    async def _set_l5_cached_context(
        self,
        chunks: List[dict],
        template_version: str,
        token_budget: int,
        tenant_id: str,
        context: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> bool:
        """Store assembled context in L5 cache."""
        if not self.enable_l5_cache or not self.exact_store:
            return False

        key = self._build_l5_key(chunks, template_version, token_budget, tenant_id, model, provider)

        try:
            cached_data = {
                "context": context,
                "timestamp": time.time(),
                "chunks_hash": compute_chunks_hash(chunks),
                "template_version": template_version,
                "token_budget": token_budget,
            }
            return self.exact_store.set(
                key,
                json.dumps(cached_data).encode(),
                ex=self.l4_ttl,  # Reuse L4 TTL for now
                nx=False,
            )
        except Exception:
            return False

    async def retrieve(
        self,
        query: str,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        top_k: int = 30,
        accounting: Optional[AccountingContext] = None,
        corpus_version: Optional[str] = None,
        **kwargs
    ) -> List[dict]:
        """Retrieve relevant chunks from vector store with L4 caching and accounting."""
        meta = meta or {}
        t_start = time.perf_counter()

        # L4 Cache Lookup
        corpus_v = corpus_version or self.corpus_version
        cached_results = await self._get_l4_cached_retrieval(query, tenant_id, top_k, meta, corpus_v)

        if cached_results is not None:
            # L4 Cache Hit
            t_l4 = (time.perf_counter() - t_start) * 1000
            record_layer(
                "L4",
                LayerStatus.HIT,
                reason="L4 retrieval cache hit",
                latency_ms=t_l4,
                hit=True,
                reuse_source="retrieval_cache",
            )

            if accounting:
                accounting.retrieval_calls_avoided += 1
                accounting.retrieval_cache_hits += 1
                accounting.retrieval_latency_saved_ms = accounting.retrieval_latency_ms  # Save baseline latency
                accounting.chunks_retrieved = len(cached_results)
                # Record that we avoided embedding + retrieval
                accounting.embedding_calls_avoided += 1

            return cached_results

        # L4 Cache Miss - Perform actual retrieval
        if accounting:
            accounting.retrieval_cache_misses += 1

        # Embed query
        dense_vec = await _run_sync(self.dense_embedder.embed, query)
        embedding_latency = (time.perf_counter() - t_start) * 1000

        if accounting:
            accounting.embedding_calls += 1
            accounting.embedding_input_tokens += self._estimate_tokens(query)
            accounting.embedding_latency_ms += embedding_latency

        # Build filter
        from qdrant_client.http import models
        q_filter = None
        conditions = []
        for k in self.metadata_filter_keys:
            if k in meta:
                conditions.append(
                    models.FieldCondition(
                        key=f"meta.{k}",
                        match=models.MatchValue(value=meta[k])
                    )
                )
        if conditions:
            q_filter = models.Filter(must=conditions)

        target_coll = f"{tenant_id}_{self.collection_name}" if tenant_id != "default" else self.collection_name

        t_ret_start = time.perf_counter()
        try:
            d_res = await self.vector_store.search(
                collection=target_coll,
                vector=dense_vec,
                query_filter=q_filter,
                limit=top_k,
                score_threshold=0.0,
                using=kwargs.get("using") if kwargs else None
            )
            retrieval_latency = (time.perf_counter() - t_ret_start) * 1000

            if accounting:
                accounting.retrieval_calls += 1
                accounting.chunks_retrieved = len(d_res)
                accounting.retrieval_latency_ms += retrieval_latency
                if d_res:
                    # Handle both objects with .score attribute and dicts
                    scores = []
                    for p in d_res:
                        if hasattr(p, 'score'):
                            scores.append(p.score)
                        elif isinstance(p, dict) and 'score' in p:
                            scores.append(p['score'])
                    if scores:
                        accounting.retrieval_score = max(scores)

            # Extract payloads
            results = [p.payload for p in d_res]

            # Store in L4 cache for future reuse
            await self._set_l4_cached_retrieval(query, tenant_id, top_k, results, meta, corpus_v)

            # Record L4 miss in trace
            t_l4_total = (time.perf_counter() - t_start) * 1000
            record_layer(
                "L4",
                LayerStatus.MISS,
                reason="L4 retrieval cache miss: performed vector search",
                latency_ms=t_l4_total,
                hit=False,
            )

            return results
        except Exception as e:
            if accounting:
                accounting.error = str(e)
                accounting.error_phase = "retrieval"
            print("Retrieve error:", e)
            return []

    async def generate(
        self,
        query: str,
        meta: Optional[dict] = None,
        tenant_id: str = "default",
        llm_generate_fn=None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
        corpus_version: Optional[str] = None,
    ):
        """Generate answer using RAG with full accounting instrumentation."""
        request_id = request_id or str(uuid.uuid4())[:16]
        tenant_id = tenant_id or self.default_tenant_id

        # Initialize accounting context
        accounting = AccountingContext(
            request_id=request_id,
            tenant_id=tenant_id,
            layer=CacheLayer.RAG_FALLBACK,
            decision_action=DecisionAction.RAG_RETRIEVAL,
        ) if self.enable_accounting else None

        t_total_start = time.perf_counter()

        with trace_rag_fallback(tenant_id=tenant_id, query=query) as fb:
            # Phase 1: Retrieval (with L4 cache)
            t0 = time.perf_counter()
            retrieved_payloads = await self.retrieve(
                query, meta, tenant_id=tenant_id, top_k=30, accounting=accounting, corpus_version=corpus_version
            )
            t_ret = time.perf_counter() - t0

            if not retrieved_payloads:
                if accounting:
                    accounting.decision_action = DecisionAction.FULL_LLM_CALL
                    accounting.error = "No retrieved chunks"
                    accounting.error_phase = "retrieval"
                    accounting.total_latency_ms = (time.perf_counter() - t_total_start) * 1000
                    record_usage(accounting.to_record())
                fb.record_completion(citations_count=0, score=-99.9)
                return "Insufficient context.", t_ret, 0.0, -99.9, []

            best_score = 0.0
            top_chunks = []

            # Phase 2: Reranking (if available)
            if self.reranker:
                t_rerank_start = time.perf_counter()
                pairs = [[query, p.get("text", "")] for p in retrieved_payloads]
                scores = await _run_sync(self.reranker.predict, pairs)
                ranked = sorted(zip(scores, retrieved_payloads), key=lambda x: x[0], reverse=True)
                best_score = ranked[0][0]
                top_chunks = ranked[:3]
                reranking_latency = (time.perf_counter() - t_rerank_start) * 1000

                if accounting:
                    accounting.reranker_calls += 1
                    accounting.chunks_reranked = len(pairs)
                    accounting.chunks_used = len(top_chunks)
                    accounting.reranking_latency_ms += reranking_latency
                    accounting.reranker_score = best_score
            else:
                best_score = 1.0
                top_chunks = [(1.0, p) for p in retrieved_payloads[:3]]
                if accounting:
                    accounting.chunks_used = len(top_chunks)
                    accounting.reranker_calls_avoided += 1

            is_filtered = self._has_active_filters(meta or {})
            threshold = self.filtered_threshold if is_filtered else self.unfiltered_threshold

            if best_score < threshold:
                if accounting:
                    accounting.error = f"Score {best_score:.3f} below threshold {threshold}"
                    accounting.error_phase = "reranking"
                    accounting.total_latency_ms = (time.perf_counter() - t_total_start) * 1000
                    record_usage(accounting.to_record())
                fb.record_completion(citations_count=0, score=best_score)
                return "Insufficient context.", t_ret, 0.0, best_score, []

            # Phase 3: L5 Context Cache Lookup (before construction, so a hit
            # genuinely skips the work)
            chunk_dicts = [p for s, p in top_chunks]
            l5_context = None
            t_l5_start = time.perf_counter()
            if self.enable_l5_cache and self.exact_store:
                l5_context = await self._get_l5_cached_context(
                    chunk_dicts,
                    self.prompt_template_version,
                    self.token_budget,
                    tenant_id,
                    model,
                    self.provider,
                )

            t_l5_ms = (time.perf_counter() - t_l5_start) * 1000

            # Phase 3b: Context Construction
            t_ctx_start = time.perf_counter()
            context_parts = []
            for s, p in top_chunks:
                section = p.get('page_or_section', '')
                text = p.get('text', '')
                context_parts.append(f"[{section}] {text}")
            constructed_context = "\n\n".join(context_parts)
            context_construction_latency = (time.perf_counter() - t_ctx_start) * 1000

            if accounting:
                accounting.context_chunks = len(top_chunks)

            if l5_context:
                # L5 Cache Hit - reuse previously assembled context
                if accounting:
                    accounting.context_cache_hits += 1
                    accounting.context_construction_tokens_avoided = self._estimate_tokens(constructed_context)
                    accounting.context_construction_latency_saved_ms = context_construction_latency
                context = l5_context
                record_layer(
                    "L5",
                    LayerStatus.HIT,
                    reason="L5 context cache hit",
                    latency_ms=t_l5_ms,
                    hit=True,
                    reuse_source="context_cache",
                )
            else:
                context = constructed_context
                if accounting:
                    accounting.context_construction_latency_ms += context_construction_latency
                    accounting.context_construction_tokens = self._estimate_tokens(context)
                    accounting.context_cache_misses += 1
                # Phase 3c: Store assembled context in L5 cache for future reuse
                if self.enable_l5_cache and self.exact_store:
                    await self._set_l5_cached_context(
                        chunk_dicts,
                        self.prompt_template_version,
                        self.token_budget,
                        tenant_id,
                        context,
                        model,
                        self.provider,
                    )
                record_layer(
                    "L5",
                    LayerStatus.MISS,
                    reason="L5 context cache miss: assembled new context",
                    latency_ms=t_l5_ms + context_construction_latency,
                    hit=False,
                )

            citations = [p.get("source_file", "") for s, p in top_chunks]
            self.last_retrieved_chunks = [
                {
                    "source": p.get("source_file", ""),
                    "section": p.get("page_or_section", ""),
                    "loader_type": p.get("loader_type") or p.get("loader") or "text",
                    "extraction_method": p.get("extraction_method")
                        or (p.get("meta", {}).get("extraction_method", "direct") if isinstance(p.get("meta"), dict) else "direct"),
                    "metadata": p.get("meta") if isinstance(p.get("meta"), dict) else {},
                    "content": p.get("text", "")[:300],
                }
                for s, p in top_chunks
            ]

            # Phase 4: LLM Generation
            prompt = f"""Answer using the provided context below.
Context:
{context}

Question: {query}
Answer:"""

            t1 = time.perf_counter()
            ans = "Error generating response."
            target_model = model or self.model

            # Estimate input tokens for prompt
            if accounting:
                accounting.input_tokens = self._estimate_tokens(prompt)

            if llm_generate_fn:
                ans = llm_generate_fn(prompt)
            else:
                call_kwargs = {}
                if self.api_base:
                    call_kwargs["api_base"] = self.api_base
                if self.api_key:
                    call_kwargs["api_key"] = self.api_key

                async def _invoke_llm():
                    resp = await _run_sync(
                        litellm.completion,
                        model=target_model,
                        messages=[{"role": "user", "content": prompt}],
                        timeout=self.timeout,
                        num_retries=self.num_retries,
                        **call_kwargs,
                    )
                    return resp.choices[0].message.content.strip()

                try:
                    if self.langfuse is not None:
                        with self.langfuse.generation(
                            name="rag-answer", model=target_model, prompt=prompt
                        ) as generation:
                            ans = await _invoke_llm()
                            generation.update(output=ans)
                    else:
                        ans = await _invoke_llm()
                except Exception as e:
                    ans = f"LLM generation failed: {e}"
                    if accounting:
                        accounting.error = str(e)
                        accounting.error_phase = "generation"

            t_gen = time.perf_counter() - t1
            generation_latency_ms = t_gen * 1000

            if accounting:
                accounting.generation_latency_ms += generation_latency_ms
                accounting.output_tokens = self._estimate_tokens(ans)

                # Extract actual usage from LiteLLM response if available
                # Note: LiteLLM returns usage in the response object
                # For mock/generate_fn path, we use estimates

                # Record token usage to metrics
                record_tokens("input", accounting.input_tokens, tenant_id)
                record_tokens("output", accounting.output_tokens, tenant_id)

                # Estimate cost
                cost = self.cost_model.estimate_cost(self.provider, target_model, accounting.input_tokens, accounting.output_tokens)
                if cost is not None:
                    accounting.actual_cost_usd = cost
                    record_cost("actual", cost, tenant_id)

            record_generation(t_gen)
            record_latency("generation", "RAG_FALLBACK", t_gen)

            # Finalize accounting
            if accounting:
                accounting.total_latency_ms = (time.perf_counter() - t_total_start) * 1000
                accounting.reuse_confidence = best_score  # For RAG, confidence = retrieval score
                record_usage(accounting.to_record())

            fb.record_completion(citations_count=len(citations), score=best_score)
            return ans, t_ret, t_gen, best_score, citations


__all__ = ["RAGPipeline", "validate_model_spec"]
