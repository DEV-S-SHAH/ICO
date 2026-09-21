"""Filesystem-based persistent storage backend."""

import json
import os
import shutil
import threading
import time
from typing import Any, Optional, Sequence
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.entry import CacheEntry
from intelligent_cache.similarity.vector_ops import find_top_matches


class DiskBackend(BaseStorageBackend):
    """Filesystem persistent cache storing JSON files per entry."""

    def __init__(self, storage_dir: str = ".cache/intelligent_cache_storage"):
        self.storage_dir = os.path.abspath(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self._lock = threading.RLock()

    def _get_path(self, key: str) -> str:
        safe_key = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in key)
        return os.path.join(self.storage_dir, f"{safe_key}.json")

    def get(self, key: str) -> Optional[CacheEntry]:
        path = self._get_path(key)
        with self._lock:
            if not os.path.isfile(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = CacheEntry.from_dict(data)
                now = time.time()
                if entry.expires_at is not None and entry.expires_at < now:
                    os.remove(path)
                    return None
                entry.touch()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(entry.to_dict(), f)
                return entry
            except Exception:
                return None

    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        if ttl is not None and ttl > 0:
            entry.expires_at = time.time() + ttl
        path = self._get_path(key)
        with self._lock:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(entry.to_dict(), f)
                return True
            except Exception:
                return False

    def delete(self, key: str) -> bool:
        path = self._get_path(key)
        with self._lock:
            if os.path.isfile(path):
                os.remove(path)
                return True
            return False

    def clear(self, namespace: Optional[str] = None) -> None:
        with self._lock:
            if namespace is None:
                shutil.rmtree(self.storage_dir, ignore_errors=True)
                os.makedirs(self.storage_dir, exist_ok=True)
            else:
                self.invalidate_namespace(namespace)

    def _read_all_entries(self) -> list[CacheEntry]:
        entries = []
        now = time.time()
        for fname in os.listdir(self.storage_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self.storage_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = CacheEntry.from_dict(data)
                if entry.expires_at is not None and entry.expires_at < now:
                    os.remove(path)
                    continue
                entries.append(entry)
            except Exception:
                continue
        return entries

    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        with self._lock:
            all_entries = self._read_all_entries()
            candidates = [
                (e, e.embedding)
                for e in all_entries
                if (namespace is None or e.namespace == namespace) and e.embedding is not None
            ]
            return find_top_matches(
                query_vector=query_vector,
                candidates=candidates,
                threshold=threshold,
                top_k=top_k,
                metric=metric,
            )

    def invalidate_namespace(self, namespace: str) -> int:
        with self._lock:
            entries = self._read_all_entries()
            count = 0
            for e in entries:
                if e.namespace == namespace:
                    path = self._get_path(e.key)
                    if os.path.isfile(path):
                        os.remove(path)
                        count += 1
            return count

    def invalidate_tag(self, tag: str) -> int:
        with self._lock:
            entries = self._read_all_entries()
            count = 0
            for e in entries:
                if tag in e.tags:
                    path = self._get_path(e.key)
                    if os.path.isfile(path):
                        os.remove(path)
                        count += 1
            return count

    def invalidate_semantic(
        self,
        query_vector: Sequence[float],
        radius: float = 0.85,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> int:
        matches = self.search_similarity(
            query_vector=query_vector,
            threshold=radius,
            top_k=1000,
            namespace=namespace,
            metric=metric,
        )
        with self._lock:
            count = 0
            for entry, _ in matches:
                if self.delete(entry.key):
                    count += 1
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            files = [f for f in os.listdir(self.storage_dir) if f.endswith(".json")]
            total_bytes = sum(
                os.path.getsize(os.path.join(self.storage_dir, f))
                for f in files
            )
            return {
                "backend": "disk",
                "storage_dir": self.storage_dir,
                "total_entries": len(files),
                "total_bytes": total_bytes,
            }
