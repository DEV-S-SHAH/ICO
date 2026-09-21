"""Decorators for seamless caching of LLM calls, tools, and functions."""

import asyncio
import functools
import inspect
import time
from typing import Any, Callable, Optional, Union

from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.entry import CacheHitType, CacheResult
from intelligent_cache.core.key import generate_embedding_key, generate_tool_key

_DEFAULT_CACHE: Optional[IntelligentCache] = None


def get_default_cache() -> IntelligentCache:
    """Return the global default IntelligentCache singleton."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        _DEFAULT_CACHE = IntelligentCache()
    return _DEFAULT_CACHE


def set_default_cache(cache_instance: IntelligentCache) -> None:
    """Set the global default IntelligentCache instance."""
    global _DEFAULT_CACHE
    _DEFAULT_CACHE = cache_instance


def _extract_query_from_args(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    key_builder: Optional[Callable[..., str]] = None,
) -> str:
    """Extract query string from function arguments."""
    if key_builder is not None:
        return key_builder(*args, **kwargs)

    # Check kwargs for common LLM argument names
    for param_name in ("prompt", "query", "question", "text", "input", "messages", "content"):
        if param_name in kwargs:
            val = kwargs[param_name]
            return str(val)

    # Inspect function signature
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        for name, val in bound.arguments.items():
            if name in ("self", "cls"):
                continue
            return str(val)
    except Exception:
        pass

    # Fallback to first non-self arg
    if args:
        first = args[0]
        if hasattr(first, func.__name__):  # likely 'self'
            if len(args) > 1:
                return str(args[1])
        return str(first)

    # Fallback to sorted kwargs representation
    return str(sorted(kwargs.items()))


def cache(
    ttl: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    namespace: Optional[str] = None,
    exact_only: bool = False,
    tags: Optional[list[str]] = None,
    key_builder: Optional[Callable[..., str]] = None,
    condition: Optional[Callable[[Any], bool]] = None,
    cache_instance: Optional[IntelligentCache] = None,
    return_result_obj: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to add intelligent caching to sync or async functions/methods.
    
    Args:
        ttl: Time to live in seconds (None for default).
        similarity_threshold: Minimum cosine similarity score for semantic hits.
        namespace: Namespace for partitioning cache entries.
        exact_only: If True, disables semantic search and uses exact matching only.
        tags: List of tags for group invalidation.
        key_builder: Custom function to extract cache query string from args/kwargs.
        condition: Optional callable (result) -> bool to filter what gets cached.
        cache_instance: Custom IntelligentCache instance (uses default if None).
        return_result_obj: If True, returns CacheResult instead of raw function output.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        c_inst = cache_instance or get_default_cache()
        ns = namespace or fn.__name__

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                bypass = kwargs.pop("bypass_cache", False) or kwargs.pop("force_refresh", False)
                query_str = _extract_query_from_args(fn, args, kwargs, key_builder)

                if not bypass:
                    hit = await c_inst.aget(
                        query=query_str,
                        namespace=ns,
                        threshold=similarity_threshold,
                        exact_only=exact_only,
                    )
                    if hit is not None:
                        return hit if return_result_obj else hit.value

                start = time.perf_counter()
                result = await fn(*args, **kwargs)
                lat_ms = (time.perf_counter() - start) * 1000.0

                if condition is None or condition(result):
                    await c_inst.aset(
                        query=query_str,
                        value=result,
                        ttl=ttl,
                        namespace=ns,
                        tags=tags,
                        latency_ms=lat_ms,
                    )

                if return_result_obj:
                    return CacheResult(value=result, hit_type=None, latency_saved_ms=0.0)
                return result

            async_wrapper.cache_instance = c_inst
            return async_wrapper

        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                bypass = kwargs.pop("bypass_cache", False) or kwargs.pop("force_refresh", False)
                query_str = _extract_query_from_args(fn, args, kwargs, key_builder)

                if not bypass:
                    hit = c_inst.get(
                        query=query_str,
                        namespace=ns,
                        threshold=similarity_threshold,
                        exact_only=exact_only,
                    )
                    if hit is not None:
                        return hit if return_result_obj else hit.value

                start = time.perf_counter()
                result = fn(*args, **kwargs)
                lat_ms = (time.perf_counter() - start) * 1000.0

                if condition is None or condition(result):
                    c_inst.set(
                        query=query_str,
                        value=result,
                        ttl=ttl,
                        namespace=ns,
                        tags=tags,
                        latency_ms=lat_ms,
                    )

                if return_result_obj:
                    return CacheResult(value=result, hit_type=None, latency_saved_ms=0.0)
                return result

            sync_wrapper.cache_instance = c_inst
            return sync_wrapper

    return decorator


def cache_tool(
    deterministic: bool = True,
    ttl: Optional[int] = 86400,
    namespace: str = "tools",
    tool_name: Optional[str] = None,
    cache_instance: Optional[IntelligentCache] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Specialized decorator for caching deterministic AI agent tools and API calls.
    
    If deterministic=True, uses exact argument hashing and bypasses semantic search
    for maximum speed and mathematical precision.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        c_inst = cache_instance or get_default_cache()
        t_name = tool_name or fn.__name__

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_tool_wrapper(*args: Any, **kwargs: Any) -> Any:
                bypass = kwargs.pop("bypass_cache", False)
                tool_key = generate_tool_key(t_name, args, kwargs, namespace=namespace)

                if not bypass:
                    entry = await asyncio.to_thread(c_inst.backend.get, tool_key)
                    if entry is not None:
                        c_inst.metrics.record_hit(
                            hit_type=CacheHitType.TOOL,
                            latency_ms=entry.latency_ms,
                            namespace=namespace,
                        )
                        return entry.value

                start = time.perf_counter()
                result = await fn(*args, **kwargs)
                lat_ms = (time.perf_counter() - start) * 1000.0

                if deterministic:
                    from intelligent_cache.core.entry import CacheEntry
                    entry = CacheEntry(
                        key=tool_key,
                        query=f"tool:{t_name}",
                        value=result,
                        namespace=namespace,
                        tags=["tool", t_name],
                        latency_ms=lat_ms,
                    )
                    await asyncio.to_thread(c_inst.backend.set, tool_key, entry, ttl)

                return result

            async_tool_wrapper.cache_instance = c_inst
            return async_tool_wrapper

        else:
            @functools.wraps(fn)
            def sync_tool_wrapper(*args: Any, **kwargs: Any) -> Any:
                bypass = kwargs.pop("bypass_cache", False)
                tool_key = generate_tool_key(t_name, args, kwargs, namespace=namespace)

                if not bypass:
                    entry = c_inst.backend.get(tool_key)
                    if entry is not None:
                        c_inst.metrics.record_hit(
                            hit_type=CacheHitType.TOOL,
                            latency_ms=entry.latency_ms,
                            namespace=namespace,
                        )
                        return entry.value

                start = time.perf_counter()
                result = fn(*args, **kwargs)
                lat_ms = (time.perf_counter() - start) * 1000.0

                if deterministic:
                    from intelligent_cache.core.entry import CacheEntry
                    entry = CacheEntry(
                        key=tool_key,
                        query=f"tool:{t_name}",
                        value=result,
                        namespace=namespace,
                        tags=["tool", t_name],
                        latency_ms=lat_ms,
                    )
                    c_inst.backend.set(tool_key, entry, ttl)

                return result

            sync_tool_wrapper.cache_instance = c_inst
            return sync_tool_wrapper

    return decorator


def cache_embeddings(
    ttl: Optional[int] = None,
    namespace: str = "embeddings",
    model_name: str = "default",
    cache_instance: Optional[IntelligentCache] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Specialized decorator for caching embedding model vectors by text hash."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        c_inst = cache_instance or get_default_cache()

        @functools.wraps(fn)
        def wrapper(text: str, *args: Any, **kwargs: Any) -> Any:
            emb_key = generate_embedding_key(text, model_name=model_name)
            entry = c_inst.backend.get(emb_key)
            if entry is not None:
                c_inst.metrics.record_hit(hit_type=CacheHitType.EXACT, latency_ms=entry.latency_ms, namespace=namespace)
                return entry.value

            start = time.perf_counter()
            result = fn(text, *args, **kwargs)
            lat_ms = (time.perf_counter() - start) * 1000.0

            from intelligent_cache.core.entry import CacheEntry
            entry = CacheEntry(
                key=emb_key,
                query=text[:100],
                value=result,
                namespace=namespace,
                tags=["embedding", model_name],
                latency_ms=lat_ms,
            )
            c_inst.backend.set(emb_key, entry, ttl=ttl)
            return result

        return wrapper

    return decorator
