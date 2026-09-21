"""Base storage backend interface."""

from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence
from intelligent_cache.core.entry import CacheEntry


class BaseStorageBackend(ABC):
    """Abstract interface for all cache storage backends."""

    @abstractmethod
    def get(self, key: str) -> Optional[CacheEntry]:
        """Retrieve an entry by exact key. Returns None if missing or expired."""
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        """Store an entry with an optional TTL (in seconds)."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an entry by key. Returns True if deleted."""
        raise NotImplementedError

    @abstractmethod
    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear all entries, or all entries in a specific namespace."""
        raise NotImplementedError

    @abstractmethod
    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        """Search for entries with embedding similarity >= threshold."""
        raise NotImplementedError

    @abstractmethod
    def invalidate_namespace(self, namespace: str) -> int:
        """Invalidate and remove all entries in a namespace. Returns count deleted."""
        raise NotImplementedError

    @abstractmethod
    def invalidate_tag(self, tag: str) -> int:
        """Invalidate and remove all entries with a specific tag. Returns count deleted."""
        raise NotImplementedError

    @abstractmethod
    def invalidate_semantic(
        self,
        query_vector: Sequence[float],
        radius: float = 0.85,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> int:
        """Invalidate entries within semantic similarity radius. Returns count deleted."""
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Return backend-specific statistics (total entries, memory, etc.)."""
        raise NotImplementedError

    def close(self) -> None:
        """Clean up backend resources if needed."""
        pass
