"""Google Gemini model adapter for IntelligentCache."""

import functools
import logging
from typing import Any, Optional
from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import get_default_cache

logger = logging.getLogger(__name__)


def wrap_gemini(
    model: Any,
    cache_instance: Optional[IntelligentCache] = None,
    namespace: str = "gemini",
    similarity_threshold: Optional[float] = None,
    ttl: Optional[int] = None,
) -> Any:
    """Wrap a Google Gemini GenerativeModel with intelligent caching.
    
    Example:
        import google.generativeai as genai
        from intelligent_cache.adapters.gemini import wrap_gemini

        model = wrap_gemini(genai.GenerativeModel("gemini-1.5-pro"))
        response = model.generate_content("Explain relativity in simple terms")
    """
    c_inst = cache_instance or get_default_cache()
    model_name = getattr(model, "model_name", "gemini-model")
    full_ns = f"{namespace}:{model_name}"

    if hasattr(model, "generate_content"):
        orig_gen = model.generate_content

        @functools.wraps(orig_gen)
        def sync_generate_content(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = str(args[0]) if args else str(kwargs.get("contents", ""))

            if not bypass:
                hit = c_inst.get(
                    query=query_str,
                    namespace=full_ns,
                    threshold=similarity_threshold,
                )
                if hit is not None:
                    return hit.value

            resp = orig_gen(*args, **kwargs)

            # Estimate token usage if metadata is available
            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage_metadata") and resp.usage_metadata:
                prompt_tokens = getattr(resp.usage_metadata, "prompt_token_count", 0)
                comp_tokens = getattr(resp.usage_metadata, "candidates_token_count", 0)

            c_inst.set(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        model.generate_content = sync_generate_content

    if hasattr(model, "generate_content_async"):
        orig_gen_async = model.generate_content_async

        @functools.wraps(orig_gen_async)
        async def async_generate_content(*args: Any, **kwargs: Any) -> Any:
            bypass = kwargs.pop("bypass_cache", False)
            query_str = str(args[0]) if args else str(kwargs.get("contents", ""))

            if not bypass:
                hit = await c_inst.aget(
                    query=query_str,
                    namespace=full_ns,
                    threshold=similarity_threshold,
                )
                if hit is not None:
                    return hit.value

            resp = await orig_gen_async(*args, **kwargs)

            prompt_tokens = 0
            comp_tokens = 0
            if hasattr(resp, "usage_metadata") and resp.usage_metadata:
                prompt_tokens = getattr(resp.usage_metadata, "prompt_token_count", 0)
                comp_tokens = getattr(resp.usage_metadata, "candidates_token_count", 0)

            await c_inst.aset(
                query=query_str,
                value=resp,
                ttl=ttl,
                namespace=full_ns,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
            )
            return resp

        model.generate_content_async = async_generate_content

    return model
