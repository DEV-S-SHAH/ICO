"""Agent tool and intermediate result caching utilities."""

import functools
import logging
from typing import Any, Callable, Optional
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import cache_tool, get_default_cache
from intelligent_cache.core.entry import CacheHitType

logger = logging.getLogger(__name__)


class AgentCache:
    """Helper for caching agent subtasks, intermediate reasoning steps, and tool execution."""

    def __init__(
        self,
        cache_instance: Optional[IntelligentCache] = None,
        namespace: str = "agent_intermediate",
    ):
        self.cache = cache_instance or get_default_cache()
        self.namespace = namespace

    def step(
        self,
        step_name: str,
        inputs: Any,
        ttl: Optional[int] = 7200,
        similarity_threshold: Optional[float] = 0.90,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for caching an agent intermediate reasoning step."""
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                query_key = f"{step_name}:{inputs}"
                hit = self.cache.get(
                    query=query_key,
                    namespace=self.namespace,
                    threshold=similarity_threshold,
                )
                if hit is not None:
                    return hit.value

                res = fn(*args, **kwargs)
                self.cache.set(
                    query=query_key,
                    value=res,
                    ttl=ttl,
                    namespace=self.namespace,
                    tags=["step", step_name],
                )
                return res
            return wrapper
        return decorator

    def cache_tool(
        self,
        deterministic: bool = True,
        ttl: Optional[int] = 86400,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for agent tool functions."""
        return cache_tool(
            deterministic=deterministic,
            ttl=ttl,
            namespace=f"{self.namespace}:tools",
            cache_instance=self.cache,
        )
