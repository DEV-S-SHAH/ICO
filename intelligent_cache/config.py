"""Configuration module for intelligent_cache."""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


def _get_env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_env_int(name: str, default: Optional[int]) -> Optional[int]:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _get_env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


@dataclass
class CacheConfig:
    """Configuration for IntelligentCache."""

    backend: str = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_BACKEND", "memory")
    )
    similarity_threshold: float = field(
        default_factory=lambda: _get_env_float("INTELLIGENT_CACHE_SIMILARITY_THRESHOLD", 0.85)
    )
    default_ttl: Optional[int] = field(
        default_factory=lambda: _get_env_int("INTELLIGENT_CACHE_TTL", 3600)
    )
    namespace: str = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_NAMESPACE", "default")
    )
    embedder: str = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_EMBEDDER", "default")
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "INTELLIGENT_CACHE_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
        )
    )
    max_entries: int = field(
        default_factory=lambda: _get_env_int("INTELLIGENT_CACHE_MAX_ENTRIES", 10000) or 10000
    )
    eviction_policy: str = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_EVICTION", "lru")
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get(
            "INTELLIGENT_CACHE_REDIS_URL", "redis://localhost:6379/0"
        )
    )
    database_url: Optional[str] = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_DATABASE_URL")
    )
    sqlite_path: str = field(
        default_factory=lambda: os.environ.get(
            "INTELLIGENT_CACHE_SQLITE_PATH", ".cache/intelligent_cache.db"
        )
    )
    disk_dir: str = field(
        default_factory=lambda: os.environ.get(
            "INTELLIGENT_CACHE_DISK_DIR", ".cache/intelligent_cache_storage"
        )
    )
    enabled: bool = field(
        default_factory=lambda: _get_env_bool("INTELLIGENT_CACHE_ENABLED", True)
    )
    graceful_fallback: bool = field(
        default_factory=lambda: _get_env_bool("INTELLIGENT_CACHE_GRACEFUL_FALLBACK", True)
    )
    exact_match_enabled: bool = field(
        default_factory=lambda: _get_env_bool("INTELLIGENT_CACHE_EXACT_MATCH", True)
    )
    semantic_match_enabled: bool = field(
        default_factory=lambda: _get_env_bool("INTELLIGENT_CACHE_SEMANTIC_MATCH", True)
    )
    similarity_metric: str = field(
        default_factory=lambda: os.environ.get("INTELLIGENT_CACHE_SIMILARITY_METRIC", "cosine")
    )
    cost_per_1k_prompt_tokens: float = field(
        default_factory=lambda: _get_env_float("INTELLIGENT_CACHE_COST_PROMPT_1K", 0.005)
    )
    cost_per_1k_completion_tokens: float = field(
        default_factory=lambda: _get_env_float("INTELLIGENT_CACHE_COST_COMPLETION_1K", 0.015)
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "backend": self.backend,
            "similarity_threshold": self.similarity_threshold,
            "default_ttl": self.default_ttl,
            "namespace": self.namespace,
            "embedder": self.embedder,
            "embedding_model": self.embedding_model,
            "max_entries": self.max_entries,
            "eviction_policy": self.eviction_policy,
            "redis_url": self.redis_url,
            "database_url": self.database_url,
            "sqlite_path": self.sqlite_path,
            "disk_dir": self.disk_dir,
            "enabled": self.enabled,
            "graceful_fallback": self.graceful_fallback,
            "exact_match_enabled": self.exact_match_enabled,
            "semantic_match_enabled": self.semantic_match_enabled,
            "similarity_metric": self.similarity_metric,
            "cost_per_1k_prompt_tokens": self.cost_per_1k_prompt_tokens,
            "cost_per_1k_completion_tokens": self.cost_per_1k_completion_tokens,
        }
