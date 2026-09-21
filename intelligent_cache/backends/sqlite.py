"""SQLite persistent storage backend with vector similarity support."""

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional, Sequence
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.entry import CacheEntry
from intelligent_cache.similarity.vector_ops import find_top_matches


class SQLiteBackend(BaseStorageBackend):
    """Zero-dependency persistent cache backend using SQLite."""

    def __init__(self, db_path: str = ".cache/intelligent_cache.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        key TEXT PRIMARY KEY,
                        namespace TEXT NOT NULL,
                        query TEXT NOT NULL,
                        value TEXT NOT NULL,
                        embedding TEXT,
                        tags TEXT,
                        metadata TEXT,
                        created_at REAL NOT NULL,
                        last_accessed REAL NOT NULL,
                        expires_at REAL,
                        hit_count INTEGER DEFAULT 0,
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        latency_ms REAL DEFAULT 0.0
                    );
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_ns ON cache_entries(namespace);
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);
                """)

    def _row_to_entry(self, row: sqlite3.Row) -> CacheEntry:
        embedding = json.loads(row["embedding"]) if row["embedding"] else None
        tags = json.loads(row["tags"]) if row["tags"] else []
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        value = json.loads(row["value"])

        return CacheEntry(
            key=row["key"],
            query=row["query"],
            value=value,
            embedding=embedding,
            namespace=row["namespace"],
            tags=tags,
            metadata=metadata,
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            expires_at=row["expires_at"],
            hit_count=row["hit_count"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            latency_ms=row["latency_ms"],
        )

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM cache_entries WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None

            entry = self._row_to_entry(row)
            now = time.time()
            if entry.expires_at is not None and entry.expires_at < now:
                cur.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                self._conn.commit()
                return None

            entry.touch()
            cur.execute(
                "UPDATE cache_entries SET last_accessed = ?, hit_count = hit_count + 1 WHERE key = ?",
                (entry.last_accessed, key),
            )
            self._conn.commit()
            return entry

    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        with self._lock:
            if ttl is not None and ttl > 0:
                entry.expires_at = time.time() + ttl

            value_json = json.dumps(entry.value)
            emb_json = json.dumps(entry.embedding) if entry.embedding is not None else None
            tags_json = json.dumps(entry.tags)
            meta_json = json.dumps(entry.metadata)

            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO cache_entries (
                        key, namespace, query, value, embedding, tags, metadata,
                        created_at, last_accessed, expires_at, hit_count,
                        prompt_tokens, completion_tokens, latency_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        query = excluded.query,
                        value = excluded.value,
                        embedding = excluded.embedding,
                        tags = excluded.tags,
                        metadata = excluded.metadata,
                        last_accessed = excluded.last_accessed,
                        expires_at = excluded.expires_at,
                        prompt_tokens = excluded.prompt_tokens,
                        completion_tokens = excluded.completion_tokens,
                        latency_ms = excluded.latency_ms;
                    """,
                    (
                        key,
                        entry.namespace,
                        entry.query,
                        value_json,
                        emb_json,
                        tags_json,
                        meta_json,
                        entry.created_at,
                        entry.last_accessed,
                        entry.expires_at,
                        entry.hit_count,
                        entry.prompt_tokens,
                        entry.completion_tokens,
                        entry.latency_ms,
                    ),
                )
            return True

    def delete(self, key: str) -> bool:
        with self._lock:
            with self._conn:
                cur = self._conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return cur.rowcount > 0

    def clear(self, namespace: Optional[str] = None) -> None:
        with self._lock:
            with self._conn:
                if namespace is None:
                    self._conn.execute("DELETE FROM cache_entries;")
                else:
                    self._conn.execute("DELETE FROM cache_entries WHERE namespace = ?;", (namespace,))

    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        with self._lock:
            cur = self._conn.cursor()
            now = time.time()
            if namespace is not None:
                cur.execute(
                    """
                    SELECT * FROM cache_entries 
                    WHERE namespace = ? AND embedding IS NOT NULL 
                    AND (expires_at IS NULL OR expires_at >= ?)
                    """,
                    (namespace, now),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM cache_entries 
                    WHERE embedding IS NOT NULL 
                    AND (expires_at IS NULL OR expires_at >= ?)
                    """,
                    (now,),
                )

            rows = cur.fetchall()
            candidates: list[tuple[CacheEntry, list[float]]] = []
            for r in rows:
                entry = self._row_to_entry(r)
                if entry.embedding:
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
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM cache_entries WHERE namespace = ?", (namespace,)
                )
                return cur.rowcount

    def invalidate_tag(self, tag: str) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT key, tags FROM cache_entries")
            rows = cur.fetchall()
            keys_to_delete = []
            for r in rows:
                tags = json.loads(r["tags"]) if r["tags"] else []
                if tag in tags:
                    keys_to_delete.append(r["key"])

            if keys_to_delete:
                with self._conn:
                    placeholders = ",".join("?" * len(keys_to_delete))
                    self._conn.execute(
                        f"DELETE FROM cache_entries WHERE key IN ({placeholders})",
                        keys_to_delete,
                    )
            return len(keys_to_delete)

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
            with self._conn:
                count = 0
                for entry, _ in matches:
                    self._conn.execute("DELETE FROM cache_entries WHERE key = ?", (entry.key,))
                    count += 1
                return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cache_entries")
            total = cur.fetchone()[0]
            now = time.time()
            cur.execute(
                "SELECT COUNT(*) FROM cache_entries WHERE expires_at IS NULL OR expires_at >= ?",
                (now,),
            )
            active = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT namespace) FROM cache_entries")
            ns_count = cur.fetchone()[0]

            db_size = 0
            if os.path.exists(self.db_path):
                db_size = os.path.getsize(self.db_path)

            return {
                "backend": "sqlite",
                "db_path": self.db_path,
                "total_entries": total,
                "active_entries": active,
                "namespaces_count": ns_count,
                "file_size_bytes": db_size,
            }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
