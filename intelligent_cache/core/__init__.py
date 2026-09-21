"""Core subpackage of intelligent_cache."""

from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.decorator import (
    cache,
    cache_tool,
    cache_embeddings,
    get_default_cache,
    set_default_cache,
)
from intelligent_cache.core.entry import CacheEntry, CacheHitType, CacheResult
from intelligent_cache.core.key import (
    generate_key,
    generate_tool_key,
    generate_embedding_key,
    normalize_query,
)

__all__ = [
    "IntelligentCache",
    "cache",
    "cache_tool",
    "cache_embeddings",
    "get_default_cache",
    "set_default_cache",
    "CacheEntry",
    "CacheHitType",
    "CacheResult",
    "generate_key",
    "generate_tool_key",
    "generate_embedding_key",
    "normalize_query",
]
