"""Redis storage backend with fallback and TTL support."""

import json
import logging
from typing import Any, Optional, Sequence
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.entry import CacheEntry
from intelligent_cache.similarity.vector_ops import find_top_matches

logger = logging.getLogger(__name__)


class RedisBackend(BaseStorageBackend):
    """Redis-backed cache storage with native TTL, tag/namespace sets, and vector search."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "icache:",
        client: Optional[Any] = None,
    ):
        self.redis_url = redis_url
        self.prefix = prefix
        self._client = client

    @property
    def client(self) -> Optional[Any]:
        if self._client is not None:
            return self._client
        try:
            import redis
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self._client.ping()
            return self._client
        except Exception as exc:
            logger.warning("Redis connection failed (%s). Operating without active Redis.", exc)
            self._client = None
            return None

    def _format_key(self, key: str) -> str:
        return f"{self.prefix}entry:{key}"

    def _ns_key(self, ns: str) -> str:
        return f"{self.prefix}ns:{ns}"

    def _tag_key(self, tag: str) -> str:
        return f"{self.prefix}tag:{tag}"

    def get(self, key: str) -> Optional[CacheEntry]:
        c = self.client
        if c is None:
            return None
        rkey = self._format_key(key)
        try:
            raw = c.get(rkey)
            if not raw:
                return None
            data = json.loads(raw)
            entry = CacheEntry.from_dict(data)
            entry.touch()
            # Update last accessed and hit count asynchronously or lazily
            c.set(rkey, json.dumps(entry.to_dict()), keepttl=True)
            return entry
        except Exception as exc:
            logger.warning("RedisBackend.get failed for '%s': %s", key, exc)
            return None

    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        c = self.client
        if c is None:
            return False
        rkey = self._format_key(key)
        try:
            payload = json.dumps(entry.to_dict())
            if ttl is not None and ttl > 0:
                c.setex(rkey, int(ttl), payload)
            else:
                c.set(rkey, payload)

            # Register in namespace set
            c.sadd(self._ns_key(entry.namespace), key)
            for tag in entry.tags:
                c.sadd(self._tag_key(tag), key)
            return True
        except Exception as exc:
            logger.warning("RedisBackend.set failed for '%s': %s", key, exc)
            return False

    def delete(self, key: str) -> bool:
        c = self.client
        if c is None:
            return False
        rkey = self._format_key(key)
        try:
            # Check entry to remove from sets
            entry = self.get(key)
            if entry:
                c.srem(self._ns_key(entry.namespace), key)
                for tag in entry.tags:
                    c.srem(self._tag_key(tag), key)
            return bool(c.delete(rkey))
        except Exception as exc:
            logger.warning("RedisBackend.delete failed: %s", exc)
            return False

    def clear(self, namespace: Optional[str] = None) -> None:
        c = self.client
        if c is None:
            return
        try:
            if namespace is None:
                keys = [k for k in c.scan_iter(match=f"{self.prefix}*")]
                if keys:
                    c.delete(*keys)
            else:
                self.invalidate_namespace(namespace)
        except Exception as exc:
            logger.warning("RedisBackend.clear failed: %s", exc)

    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        c = self.client
        if c is None:
            return []
        try:
            if namespace is not None:
                keys = list(c.smembers(self._ns_key(namespace)))
            else:
                raw_keys = [k for k in c.scan_iter(match=f"{self.prefix}entry:*")]
                prefix_len = len(f"{self.prefix}entry:")
                keys = [k[prefix_len:] for k in raw_keys]

            candidates: list[tuple[CacheEntry, list[float]]] = []
            for k in keys:
                entry = self.get(k)
                if entry and entry.embedding is not None:
                    candidates.append((entry, entry.embedding))

            return find_top_matches(
                query_vector=query_vector,
                candidates=candidates,
                threshold=threshold,
                top_k=top_k,
                metric=metric,
            )
        except Exception as exc:
            logger.warning("RedisBackend.search_similarity failed: %s", exc)
            return []

    def invalidate_namespace(self, namespace: str) -> int:
        c = self.client
        if c is None:
            return 0
        try:
            ns_key = self._ns_key(namespace)
            keys = list(c.smembers(ns_key))
            if not keys:
                return 0
            entry_keys = [self._format_key(k) for k in keys]
            c.delete(*entry_keys, ns_key)
            return len(keys)
        except Exception as exc:
            logger.warning("RedisBackend.invalidate_namespace failed: %s", exc)
            return 0

    def invalidate_tag(self, tag: str) -> int:
        c = self.client
        if c is None:
            return 0
        try:
            tag_key = self._tag_key(tag)
            keys = list(c.smembers(tag_key))
            if not keys:
                return 0
            entry_keys = [self._format_key(k) for k in keys]
            c.delete(*entry_keys, tag_key)
            return len(keys)
        except Exception as exc:
            logger.warning("RedisBackend.invalidate_tag failed: %s", exc)
            return 0

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
        count = 0
        for entry, _ in matches:
            if self.delete(entry.key):
                count += 1
        return count

    def stats(self) -> dict[str, Any]:
        c = self.client
        if c is None:
            return {"backend": "redis", "status": "disconnected"}
        try:
            info = c.info("memory")
            return {
                "backend": "redis",
                "status": "connected",
                "used_memory_human": info.get("used_memory_human"),
                "total_entries": sum(1 for _ in c.scan_iter(match=f"{self.prefix}entry:*")),
            }
        except Exception as exc:
            return {"backend": "redis", "status": "error", "error": str(exc)}
