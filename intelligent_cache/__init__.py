"""Intelligent Cache: Model-Agnostic Intelligent Cache Optimization for AI Agents and LLMs.

Intelligently cache and reuse:
- LLM responses (exact & semantic similarity)
- Embeddings
- Tool/API calls
- Agent intermediate results
- Repeated or semantically similar queries
"""

__version__ = "1.0.0"

from intelligent_cache.config import CacheConfig
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
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.backends.memory import MemoryBackend
from intelligent_cache.backends.sqlite import SQLiteBackend
from intelligent_cache.backends.disk import DiskBackend
from intelligent_cache.backends.redis import RedisBackend
from intelligent_cache.backends.postgres import PostgresBackend
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.embeddings.default import DefaultEmbedder
from intelligent_cache.embeddings.factory import create_embedder
from intelligent_cache.intelligence.scorer import CachePolicyScorer
from intelligent_cache.intelligence.invalidation import InvalidationManager
from intelligent_cache.metrics.collector import CacheStats, MetricsCollector
from intelligent_cache.adapters.openai import wrap_openai
from intelligent_cache.adapters.anthropic import wrap_anthropic
from intelligent_cache.adapters.gemini import wrap_gemini
from intelligent_cache.adapters.langchain import IntelligentCacheLangChain
from intelligent_cache.adapters.llamaindex import IntelligentCacheLlamaIndex
from intelligent_cache.adapters.tool import AgentCache

__all__ = [
    "IntelligentCache",
    "cache",
    "cache_tool",
    "cache_embeddings",
    "get_default_cache",
    "set_default_cache",
    "CacheConfig",
    "CacheEntry",
    "CacheHitType",
    "CacheResult",
    "CacheStats",
    "MetricsCollector",
    "CachePolicyScorer",
    "InvalidationManager",
    "BaseStorageBackend",
    "MemoryBackend",
    "SQLiteBackend",
    "DiskBackend",
    "RedisBackend",
    "PostgresBackend",
    "BaseEmbedder",
    "DefaultEmbedder",
    "create_embedder",
    "wrap_openai",
    "wrap_anthropic",
    "wrap_gemini",
    "IntelligentCacheLangChain",
    "IntelligentCacheLlamaIndex",
    "AgentCache",
    "generate_key",
    "generate_tool_key",
    "generate_embedding_key",
    "normalize_query",
    "__version__",
]
