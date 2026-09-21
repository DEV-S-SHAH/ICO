"""LangChain cache adapter for IntelligentCache."""

import logging
from typing import Any, Optional, Sequence
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import get_default_cache

logger = logging.getLogger(__name__)

try:
    from langchain_core.caches import BaseCache
except ImportError:
    class BaseCache:  # type: ignore
        """Fallback stub if langchain is not installed."""
        pass


class IntelligentCacheLangChain(BaseCache):
    """LangChain-compatible cache adapter using IntelligentCache.
    
    Example:
        from langchain.globals import set_llm_cache
        from intelligent_cache import IntelligentCache
        from intelligent_cache.adapters.langchain import IntelligentCacheLangChain

        set_llm_cache(IntelligentCacheLangChain(IntelligentCache()))
    """

    def __init__(
        self,
        cache_instance: Optional[IntelligentCache] = None,
        namespace: str = "langchain",
        ttl: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ):
        self.cache = cache_instance or get_default_cache()
        self.namespace = namespace
        self.ttl = ttl
        self.similarity_threshold = similarity_threshold

    def lookup(self, prompt: str, llm_string: str) -> Optional[Any]:
        """Look up value based on prompt and llm_string."""
        ns = f"{self.namespace}:{llm_string}"
        hit = self.cache.get(
            query=prompt,
            namespace=ns,
            threshold=self.similarity_threshold,
        )
        if hit is not None:
            return hit.value
        return None

    def update(self, prompt: str, llm_string: str, return_val: Any) -> None:
        """Update cache based on prompt and llm_string."""
        ns = f"{self.namespace}:{llm_string}"
        self.cache.set(
            query=prompt,
            value=return_val,
            ttl=self.ttl,
            namespace=ns,
        )

    def clear(self, **kwargs: Any) -> None:
        """Clear cache."""
        self.cache.clear(namespace=self.namespace)
