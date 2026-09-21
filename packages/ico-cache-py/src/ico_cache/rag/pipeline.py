import asyncio
import functools
import time
from typing import Any, List, Optional
import litellm
from ..backends.base import BaseEmbedder, BaseVectorStore
from ..telemetry.metrics import record_generation
from ..telemetry.tracing import trace_rag_fallback


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

    def _has_active_filters(self, meta: dict) -> bool:
        return any(k in meta for k in self.metadata_filter_keys)

    async def retrieve(self, query: str, meta: Optional[dict] = None, tenant_id: str = "default", top_k: int = 30, **kwargs) -> List[dict]:
        meta = meta or {}
        dense_vec = await _run_sync(self.dense_embedder.embed, query)

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

        try:
            d_res = await self.vector_store.search(
                collection=target_coll,
                vector=dense_vec,
                query_filter=q_filter,
                limit=top_k,
                score_threshold=0.0,
                using=kwargs.get("using") if kwargs else None
            )
            return [p.payload for p in d_res]
        except Exception as e:
            print("Retrieve error:", e)
            return []

    async def generate(self, query: str, meta: Optional[dict] = None, tenant_id: str = "default", llm_generate_fn=None, model: Optional[str] = None):
        with trace_rag_fallback(tenant_id=tenant_id, query=query) as fb:
            t0 = time.time()
            retrieved_payloads = await self.retrieve(query, meta, tenant_id=tenant_id, top_k=30)
            t_ret = time.time() - t0

            if not retrieved_payloads:
                fb.record_completion(citations_count=0, score=-99.9)
                return "Insufficient context.", t_ret, 0.0, -99.9, []

            best_score = 0.0
            top_chunks = []

            if self.reranker:
                pairs = [[query, p.get("text", "")] for p in retrieved_payloads]
                scores = await _run_sync(self.reranker.predict, pairs)
                ranked = sorted(zip(scores, retrieved_payloads), key=lambda x: x[0], reverse=True)
                best_score = ranked[0][0]
                top_chunks = ranked[:3]
            else:
                best_score = 1.0
                top_chunks = [(1.0, p) for p in retrieved_payloads[:3]]

            is_filtered = self._has_active_filters(meta or {})
            threshold = self.filtered_threshold if is_filtered else self.unfiltered_threshold

            if best_score < threshold:
                fb.record_completion(citations_count=0, score=best_score)
                return "Insufficient context.", t_ret, 0.0, best_score, []

            context = "\n\n".join([f"[{p.get('page_or_section','')}] {p.get('text','')}" for s, p in top_chunks])
            citations = [p.get("source_file", "") for s, p in top_chunks]
            self.last_retrieved_chunks = [
                {
                    "source": p.get("source_file", ""),
                    "section": p.get("page_or_section", ""),
                    "loader_type": p.get("loader_type") or p.get("loader") or "text",
                    "extraction_method": p.get("extraction_method") or (p.get("meta", {}).get("extraction_method", "direct") if isinstance(p.get("meta"), dict) else "direct"),
                    "metadata": p.get("meta") if isinstance(p.get("meta"), dict) else {},
                    "content": p.get("text", "")[:300],
                }
                for s, p in top_chunks
            ]

            prompt = f"""Answer using the provided context below.
Context:
{context}

Question: {query}
Answer:"""

            t1 = time.time()
            ans = "Error generating response."
            target_model = model or self.model
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
            t_gen = time.time() - t1
            record_generation(t_gen)

            fb.record_completion(citations_count=len(citations), score=best_score)
            return ans, t_ret, t_gen, best_score, citations
