"""Factory for resolving and instantiating storage backends."""

import logging
from typing import Any, Optional, Union
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.backends.memory import MemoryBackend
from intelligent_cache.config import CacheConfig

logger = logging.getLogger(__name__)


def create_backend(
    backend: Union[str, BaseStorageBackend, None] = "memory",
    config: Optional[CacheConfig] = None,
    **kwargs: Any,
) -> BaseStorageBackend:
    """Create or return a storage backend instance."""
    if isinstance(backend, BaseStorageBackend):
        return backend

    cfg = config or CacheConfig()
    name = (backend or cfg.backend or "memory").lower().strip()

    if name in ("memory", "in-memory", "ram"):
        max_entries = kwargs.get("max_entries", cfg.max_entries)
        eviction = kwargs.get("eviction_policy", cfg.eviction_policy)
        return MemoryBackend(max_entries=max_entries, eviction_policy=eviction)

    if name in ("sqlite", "sqlite3"):
        from intelligent_cache.backends.sqlite import SQLiteBackend
        db_path = kwargs.get("sqlite_path", cfg.sqlite_path)
        return SQLiteBackend(db_path=db_path)

    if name in ("disk", "file", "filesystem"):
        from intelligent_cache.backends.disk import DiskBackend
        storage_dir = kwargs.get("disk_dir", cfg.disk_dir)
        return DiskBackend(storage_dir=storage_dir)

    if name == "redis":
        from intelligent_cache.backends.redis import RedisBackend
        redis_url = kwargs.get("redis_url", cfg.redis_url)
        return RedisBackend(redis_url=redis_url)

    if name in ("postgres", "postgresql", "pgvector"):
        from intelligent_cache.backends.postgres import PostgresBackend
        db_url = kwargs.get("database_url", cfg.database_url)
        if not db_url:
            logger.warning("No database_url provided for PostgresBackend. Falling back to MemoryBackend.")
            return MemoryBackend()
        return PostgresBackend(database_url=db_url)

    logger.warning("Unknown backend '%s'. Falling back to MemoryBackend.", name)
    return MemoryBackend()
