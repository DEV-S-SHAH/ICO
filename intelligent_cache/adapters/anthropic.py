"""Anthropic API client adapter for IntelligentCache."""

import functools
import logging
from typing import Any, Optional
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import get_default_cache

logger = logging.getLogger(__name__)


def _extract_prompt_from_anthropic_kwargs(kwargs: dict[str, Any]) -> str:
    messages = kwargs.get("messages", [])
    parts = []
    if "system" in kwargs:
        parts.append(f"system: {kwargs['system']}")
    for msg in messages:
        if isinstance(msg, dict):
            parts.append(f"{msg.get('role', 'user')}: {msg.get('content', '')}")
        elif hasattr(msg, "role") and hasattr(msg, "content"):
            parts.append(f"{getattr(msg, 'role')}: {getattr(msg, 'content')}")
    if parts:
        return "\n".join(parts)
    return str(kwargs)


def wrap_anthropic(
    client: Any,
    cache_instance: Optional[IntelligentCache] = None,
    namespace: str = "anthropic",
    similarity_threshold: Optional[float] = None,
    ttl: Optional[int] = None,
) -> Any:
    """Wrap an Anthropic client with intelligent caching for messages.
    
    Example:
        from anthropic import Anthropic
        from intelligent_cache.adapters.anthropic import wrap_anthropic

        client = wrap_anthropic(Anthropic())
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": "Explain quantum computing"}]
        )
    """
    c_inst = cache_instance or get_default_cache()
    original_create = client.messages.create

    import asyncio
    is_async = asyncio.iscoroutinefunction(original_create)

    if is_async:
        @functools.wraps(original_create)
        async def async_messages_create(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = _extract_prompt_from_anthropic_kwargs(kwargs)
            model_name = kwargs.get("model", "default")
            full_ns = f"{namespace}:{model_name}"

            if not bypass:
                hit = await c_inst.aget(
                    query=query_str,
                    namespace=full_ns,
                    threshold=similarity_threshold,
                )
                if hit is not None:
                    return hit.value

            resp = await original_create(*args, **kwargs)

            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                prompt_tokens = getattr(resp.usage, "input_tokens", 0)
                comp_tokens = getattr(resp.usage, "output_tokens", 0)

            await c_inst.aset(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        client.messages.create = async_messages_create

    else:
        @functools.wraps(original_create)
        def sync_messages_create(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = _extract_prompt_from_anthropic_kwargs(kwargs)
            model_name = kwargs.get("model", "default")
            full_ns = f"{namespace}:{model_name}"

            if not bypass:
                hit = c_inst.get(
                    query=query_str,
                    namespace=full_ns,
                    threshold=similarity_threshold,
                )
                if hit is not None:
                    return hit.value

            resp = original_create(*args, **kwargs)

            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                prompt_tokens = getattr(resp.usage, "input_tokens", 0)
                comp_tokens = getattr(resp.usage, "output_tokens", 0)

            c_inst.set(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        client.messages.create = sync_messages_create

    return client
