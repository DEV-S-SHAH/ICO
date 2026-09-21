"""OpenAI API client adapter for IntelligentCache."""

import functools
import logging
from typing import Any, Optional
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import get_default_cache

logger = logging.getLogger(__name__)


def _extract_prompt_from_openai_kwargs(kwargs: dict[str, Any]) -> str:
    messages = kwargs.get("messages", [])
    if isinstance(messages, list):
        parts = []
        for msg in messages:
            if isinstance(msg, dict):
                parts.append(f"{msg.get('role', 'user')}: {msg.get('content', '')}")
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                parts.append(f"{getattr(msg, 'role')}: {getattr(msg, 'content')}")
        if parts:
            return "\n".join(parts)
    if "prompt" in kwargs:
        return str(kwargs["prompt"])
    return str(kwargs)


def wrap_openai(
    client: Any,
    cache_instance: Optional[IntelligentCache] = None,
    namespace: str = "openai",
    similarity_threshold: Optional[float] = None,
    ttl: Optional[int] = None,
) -> Any:
    """Wrap an OpenAI client with intelligent caching for chat completions.
    
    Example:
        from openai import OpenAI
        from intelligent_cache.adapters.openai import wrap_openai

        client = wrap_openai(OpenAI())
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "What is Python?"}]
        )
    """
    c_inst = cache_instance or get_default_cache()
    original_chat_create = client.chat.completions.create

    # Check if async
    import asyncio
    is_async = asyncio.iscoroutinefunction(original_chat_create)

    if is_async:
        @functools.wraps(original_chat_create)
        async def async_chat_create(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = _extract_prompt_from_openai_kwargs(kwargs)
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

            resp = await original_chat_create(*args, **kwargs)

            # Extract text & token usage
            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                prompt_tokens = getattr(resp.usage, "prompt_tokens", 0)
                comp_tokens = getattr(resp.usage, "completion_tokens", 0)

            await c_inst.aset(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        client.chat.completions.create = async_chat_create

    else:
        @functools.wraps(original_chat_create)
        def sync_chat_create(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = _extract_prompt_from_openai_kwargs(kwargs)
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

            resp = original_chat_create(*args, **kwargs)

            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                prompt_tokens = getattr(resp.usage, "prompt_tokens", 0)
                comp_tokens = getattr(resp.usage, "completion_tokens", 0)

            c_inst.set(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        client.chat.completions.create = sync_chat_create

    return client
