"""LlamaIndex cache adapter for IntelligentCache."""

import logging
from typing import Any, Optional
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import get_default_cache

logger = logging.getLogger(__name__)


class IntelligentCacheLlamaIndex:
    """LlamaIndex cache helper for wrapping LLMs and query engines.
    
    Example:
        from intelligent_cache.adapters.llamaindex import IntelligentCacheLlamaIndex
        
        cached_llm = IntelligentCacheLlamaIndex(cache_instance).wrap_llm(llm)
    """

    def __init__(
        self,
        cache_instance: Optional[IntelligentCache] = None,
        namespace: str = "llamaindex",
        similarity_threshold: Optional[float] = None,
        ttl: Optional[int] = None,
    ):
        self.cache = cache_instance or get_default_cache()
        self.namespace = namespace
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl

    def wrap_llm(self, llm: Any) -> Any:
        """Wrap a LlamaIndex LLM instance with intelligent semantic caching."""
        if hasattr(llm, "complete"):
            orig_complete = llm.complete

            def cached_complete(prompt: str, *args: Any, **kwargs: Any) -> Any:
                hit = self.cache.get(
                    query=prompt,
                    namespace=self.namespace,
                    threshold=self.similarity_threshold,
                )
                if hit is not None:
                    return hit.value

                res = orig_complete(prompt, *args, **kwargs)
                self.cache.set(
                    query=prompt,
                    value=res,
                    ttl=self.ttl,
                    namespace=self.namespace,
                )
                return res

            llm.complete = cached_complete

        if hasattr(llm, "acomplete"):
            orig_acomplete = llm.acomplete

            async def cached_acomplete(prompt: str, *args: Any, **kwargs: Any) -> Any:
                hit = await self.cache.aget(
                    query=prompt,
                    namespace=self.namespace,
                    threshold=self.similarity_threshold,
                )
                if hit is not None:
                    return hit.value

                res = await orig_acomplete(prompt, *args, **kwargs)
                await self.cache.aset(
                    query=prompt,
                    value=res,
                    ttl=self.ttl,
                    namespace=self.namespace,
                )
                return res

            llm.acomplete = cached_acomplete

        return llm
