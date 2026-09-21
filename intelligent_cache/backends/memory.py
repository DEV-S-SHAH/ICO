"""In-memory storage backend with thread-safety and vector similarity search."""

import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Optional, Sequence
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.entry import CacheEntry
from intelligent_cache.similarity.vector_ops import find_top_matches


class MemoryBackend(BaseStorageBackend):
    """Thread-safe in-memory cache backend with LRU/LFU/FIFO eviction and vector search."""

    def __init__(
        self,
        max_entries: int = 10000,
        eviction_policy: str = "lru",
    ):
        self.max_entries = max(1, max_entries)
        self.eviction_policy = eviction_policy.lower()
        self._lock = threading.RLock()

        # Storage
        self._entries: dict[str, CacheEntry] = {}
        # Order tracking for LRU / FIFO
        self._access_order: OrderedDict[str, float] = OrderedDict()
        # Tags index: tag -> set of keys
        self._tag_index: dict[str, set[str]] = {}
        # Namespace index: namespace -> set of keys
        self._namespace_index: dict[str, set[str]] = {}
        # Stats
        self._evictions_count: int = 0

    def _is_expired(self, entry: CacheEntry) -> bool:
        return entry.is_expired

    def _remove_key(self, key: str) -> None:
        """Internal key removal without lock (must be called with lock held)."""
        entry = self._entries.pop(key, None)
        self._access_order.pop(key, None)
        if entry is not None:
            # Clean namespace index
            ns = entry.namespace
            if ns in self._namespace_index:
                self._namespace_index[ns].discard(key)
                if not self._namespace_index[ns]:
                    del self._namespace_index[ns]
            # Clean tags index
            for tag in entry.tags:
                if tag in self._tag_index:
                    self._tag_index[tag].discard(key)
                    if not self._tag_index[tag]:
                        del self._tag_index[tag]

    def _evict_if_needed(self) -> None:
        """Evict an entry if max_entries is exceeded (lock must be held)."""
        while len(self._entries) >= self.max_entries:
            # First, try to evict expired items
            now = time.time()
            expired_keys = [
                k for k, v in self._entries.items()
                if v.expires_at is not None and v.expires_at < now
            ]
            if expired_keys:
                for k in expired_keys:
                    self._remove_key(k)
                    self._evictions_count += 1
                if len(self._entries) < self.max_entries:
                    return

            # If no expired items, evict according to policy
            key_to_evict = None
            if self.eviction_policy == "lfu":
                # Least frequently used
                key_to_evict = min(self._entries.keys(), key=lambda k: self._entries[k].hit_count)
            elif self.eviction_policy == "fifo":
                # First in first out (earliest created_at)
                key_to_evict = min(self._entries.keys(), key=lambda k: self._entries[k].created_at)
            else:
                # Default LRU
                if self._access_order:
                    key_to_evict, _ = self._access_order.popitem(last=False)

            if key_to_evict and key_to_evict in self._entries:
                self._remove_key(key_to_evict)
                self._evictions_count += 1
            else:
                # Safety fallback
                for k in list(self._entries.keys()):
                    self._remove_key(k)
                    self._evictions_count += 1
                    break

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._is_expired(entry):
                self._remove_key(key)
                return None

            entry.touch()
            # Update LRU order
            if key in self._access_order:
                self._access_order.move_to_end(key)
            else:
                self._access_order[key] = time.time()
            return entry

    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        with self._lock:
            if key in self._entries:
                self._remove_key(key)

            self._evict_if_needed()

            if ttl is not None and ttl > 0:
                entry.expires_at = time.time() + ttl

            self._entries[key] = entry
            self._access_order[key] = time.time()

            # Index namespace
            ns = entry.namespace
            if ns not in self._namespace_index:
                self._namespace_index[ns] = set()
            self._namespace_index[ns].add(key)

            # Index tags
            for tag in entry.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = set()
                self._tag_index[tag].add(key)

            return True

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._entries:
                self._remove_key(key)
                return True
            return False

    def clear(self, namespace: Optional[str] = None) -> None:
        with self._lock:
            if namespace is None:
                self._entries.clear()
                self._access_order.clear()
                self._tag_index.clear()
                self._namespace_index.clear()
            else:
                keys = list(self._namespace_index.get(namespace, set()))
                for k in keys:
                    self._remove_key(k)

    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        with self._lock:
            now = time.time()
            # Identify candidate keys
            if namespace is not None:
                keys = list(self._namespace_index.get(namespace, set()))
            else:
                keys = list(self._entries.keys())

            candidates: list[tuple[CacheEntry, list[float]]] = []
            for k in keys:
                entry = self._entries.get(k)
                if entry is None:
                    continue
                if entry.expires_at is not None and entry.expires_at < now:
                    self._remove_key(k)
                    continue
                if entry.embedding is not None:
                    candidates.append((entry, entry.embedding))

            return find_top_matches(
                query_vector=query_vector,
                candidates=candidates,
                threshold=threshold,
                top_k=top_k,
                metric=metric,
            )

    def invalidate_namespace(self, namespace: str) -> int:
        with self._lock:
            keys = list(self._namespace_index.get(namespace, set()))
            for k in keys:
                self._remove_key(k)
            return len(keys)

    def invalidate_tag(self, tag: str) -> int:
        with self._lock:
            keys = list(self._tag_index.get(tag, set()))
            for k in keys:
                self._remove_key(k)
            return len(keys)

    def invalidate_semantic(
        self,
        query_vector: Sequence[float],
        radius: float = 0.85,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> int:
        with self._lock:
            matches = self.search_similarity(
                query_vector=query_vector,
                threshold=radius,
                top_k=1000,
                namespace=namespace,
                metric=metric,
            )
            count = 0
            for entry, _ in matches:
                self._remove_key(entry.key)
                count += 1
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            active_count = sum(
                1 for e in self._entries.values()
                if e.expires_at is None or e.expires_at >= now
            )
            approx_bytes = sum(sys.getsizeof(e.value) for e in self._entries.values())
            return {
                "backend": "memory",
                "total_entries": len(self._entries),
                "active_entries": active_count,
                "evictions": self._evictions_count,
                "namespaces_count": len(self._namespace_index),
                "tags_count": len(self._tag_index),
                "approx_size_bytes": approx_bytes,
                "max_entries": self.max_entries,
                "eviction_policy": self.eviction_policy,
            }
