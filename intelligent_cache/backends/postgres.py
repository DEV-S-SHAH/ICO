"""PostgreSQL storage backend with pgvector and fallback support."""

import json
import logging
import time
from typing import Any, Optional, Sequence
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.entry import CacheEntry
from intelligent_cache.similarity.vector_ops import find_top_matches

logger = logging.getLogger(__name__)


class PostgresBackend(BaseStorageBackend):
    """PostgreSQL cache backend with pgvector support."""

    def __init__(
        self,
        database_url: str,
        table_name: str = "intelligent_cache_entries",
    ):
        self.database_url = database_url
        self.table_name = table_name
        self._engine = None
        self._has_vector = False

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from sqlalchemy import create_engine, text
            self._engine = create_engine(self.database_url, pool_pre_ping=True)
            with self._engine.connect() as conn:
                # Try enabling pgvector extension
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    conn.commit()
                    self._has_vector = True
                except Exception:
                    self._has_vector = False

                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        key VARCHAR(255) PRIMARY KEY,
                        namespace VARCHAR(100) NOT NULL,
                        query TEXT NOT NULL,
                        value JSONB NOT NULL,
                        embedding JSONB,
                        tags JSONB,
                        metadata JSONB,
                        created_at DOUBLE PRECISION NOT NULL,
                        last_accessed DOUBLE PRECISION NOT NULL,
                        expires_at DOUBLE PRECISION,
                        hit_count INTEGER DEFAULT 0,
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        latency_ms DOUBLE PRECISION DEFAULT 0.0
                    );
                """))
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_ns ON {self.table_name}(namespace);
                """))
                conn.commit()
            return self._engine
        except Exception as exc:
            logger.warning("PostgresBackend initialization failed: %s", exc)
            self._engine = None
            return None

    def get(self, key: str) -> Optional[CacheEntry]:
        engine = self._ensure_engine()
        if engine is None:
            return None
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(f"SELECT * FROM {self.table_name} WHERE key = :key"),
                    {"key": key},
                ).mappings().fetchone()
                if not row:
                    return None

                now = time.time()
                if row["expires_at"] is not None and row["expires_at"] < now:
                    conn.execute(
                        text(f"DELETE FROM {self.table_name} WHERE key = :key"),
                        {"key": key},
                    )
                    conn.commit()
                    return None

                entry = CacheEntry(
                    key=row["key"],
                    query=row["query"],
                    value=row["value"],
                    embedding=row["embedding"],
                    namespace=row["namespace"],
                    tags=row["tags"] or [],
                    metadata=row["metadata"] or {},
                    created_at=row["created_at"],
                    last_accessed=row["last_accessed"],
                    expires_at=row["expires_at"],
                    hit_count=row["hit_count"],
                    prompt_tokens=row["prompt_tokens"],
                    completion_tokens=row["completion_tokens"],
                    latency_ms=row["latency_ms"],
                )
                entry.touch()
                conn.execute(
                    text(f"""
                        UPDATE {self.table_name} 
                        SET last_accessed = :la, hit_count = hit_count + 1 
                        WHERE key = :key
                    """),
                    {"la": entry.last_accessed, "key": key},
                )
                conn.commit()
                return entry
        except Exception as exc:
            logger.warning("PostgresBackend.get failed for '%s': %s", key, exc)
            return None

    def set(self, key: str, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        engine = self._ensure_engine()
        if engine is None:
            return False
        from sqlalchemy import text
        if ttl is not None and ttl > 0:
            entry.expires_at = time.time() + ttl

        try:
            with engine.connect() as conn:
                conn.execute(
                    text(f"""
                        INSERT INTO {self.table_name} (
                            key, namespace, query, value, embedding, tags, metadata,
                            created_at, last_accessed, expires_at, hit_count,
                            prompt_tokens, completion_tokens, latency_ms
                        ) VALUES (
                            :key, :namespace, :query, :value, :embedding, :tags, :metadata,
                            :created_at, :last_accessed, :expires_at, :hit_count,
                            :prompt_tokens, :completion_tokens, :latency_ms
                        )
                        ON CONFLICT (key) DO UPDATE SET
                            query = EXCLUDED.query,
                            value = EXCLUDED.value,
                            embedding = EXCLUDED.embedding,
                            tags = EXCLUDED.tags,
                            metadata = EXCLUDED.metadata,
                            last_accessed = EXCLUDED.last_accessed,
                            expires_at = EXCLUDED.expires_at,
                            prompt_tokens = EXCLUDED.prompt_tokens,
                            completion_tokens = EXCLUDED.completion_tokens,
                            latency_ms = EXCLUDED.latency_ms;
                    """),
                    {
                        "key": key,
                        "namespace": entry.namespace,
                        "query": entry.query,
                        "value": json.dumps(entry.value),
                        "embedding": json.dumps(entry.embedding) if entry.embedding is not None else None,
                        "tags": json.dumps(entry.tags),
                        "metadata": json.dumps(entry.metadata),
                        "created_at": entry.created_at,
                        "last_accessed": entry.last_accessed,
                        "expires_at": entry.expires_at,
                        "hit_count": entry.hit_count,
                        "prompt_tokens": entry.prompt_tokens,
                        "completion_tokens": entry.completion_tokens,
                        "latency_ms": entry.latency_ms,
                    },
                )
                conn.commit()
            return True
        except Exception as exc:
            logger.warning("PostgresBackend.set failed for '%s': %s", key, exc)
            return False

    def delete(self, key: str) -> bool:
        engine = self._ensure_engine()
        if engine is None:
            return False
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE key = :key"),
                    {"key": key},
                )
                conn.commit()
                return res.rowcount > 0
        except Exception as exc:
            logger.warning("PostgresBackend.delete failed: %s", exc)
            return False

    def clear(self, namespace: Optional[str] = None) -> None:
        engine = self._ensure_engine()
        if engine is None:
            return
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                if namespace is None:
                    conn.execute(text(f"DELETE FROM {self.table_name};"))
                else:
                    conn.execute(
                        text(f"DELETE FROM {self.table_name} WHERE namespace = :ns;"),
                        {"ns": namespace},
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("PostgresBackend.clear failed: %s", exc)

    def search_similarity(
        self,
        query_vector: Sequence[float],
        threshold: float = 0.85,
        top_k: int = 1,
        namespace: Optional[str] = None,
        metric: str = "cosine",
    ) -> list[tuple[CacheEntry, float]]:
        engine = self._ensure_engine()
        if engine is None:
            return []
        from sqlalchemy import text
        try:
            now = time.time()
            with engine.connect() as conn:
                query_sql = f"""
                    SELECT * FROM {self.table_name}
                    WHERE embedding IS NOT NULL
                    AND (expires_at IS NULL OR expires_at >= :now)
                """
                params: dict[str, Any] = {"now": now}
                if namespace is not None:
                    query_sql += " AND namespace = :ns"
                    params["ns"] = namespace

                rows = conn.execute(text(query_sql), params).mappings().fetchall()
                candidates: list[tuple[CacheEntry, list[float]]] = []
                for r in rows:
                    entry = CacheEntry(
                        key=r["key"],
                        query=r["query"],
                        value=r["value"],
                        embedding=r["embedding"],
                        namespace=r["namespace"],
                        tags=r["tags"] or [],
                        metadata=r["metadata"] or {},
                        created_at=r["created_at"],
                        last_accessed=r["last_accessed"],
                        expires_at=r["expires_at"],
                        hit_count=r["hit_count"],
                        prompt_tokens=r["prompt_tokens"],
                        completion_tokens=r["completion_tokens"],
                        latency_ms=r["latency_ms"],
                    )
                    if entry.embedding:
                        candidates.append((entry, entry.embedding))

                return find_top_matches(
                    query_vector=query_vector,
                    candidates=candidates,
                    threshold=threshold,
                    top_k=top_k,
                    metric=metric,
                )
        except Exception as exc:
            logger.warning("PostgresBackend.search_similarity failed: %s", exc)
            return []

    def invalidate_namespace(self, namespace: str) -> int:
        engine = self._ensure_engine()
        if engine is None:
            return 0
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE namespace = :ns"),
                    {"ns": namespace},
                )
                conn.commit()
                return res.rowcount
        except Exception as exc:
            logger.warning("PostgresBackend.invalidate_namespace failed: %s", exc)
            return 0

    def invalidate_tag(self, tag: str) -> int:
        engine = self._ensure_engine()
        if engine is None:
            return 0
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE tags @> :tag"),
                    {"tag": json.dumps([tag])},
                )
                conn.commit()
                return res.rowcount
        except Exception as exc:
            logger.warning("PostgresBackend.invalidate_tag failed: %s", exc)
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
        engine = self._ensure_engine()
        if engine is None:
            return {"backend": "postgres", "status": "disconnected"}
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                total = conn.execute(
                    text(f"SELECT COUNT(*) FROM {self.table_name}")
                ).scalar()
                return {
                    "backend": "postgres",
                    "status": "connected",
                    "total_entries": total,
                    "has_pgvector": self._has_vector,
                }
        except Exception as exc:
            return {"backend": "postgres", "status": "error", "error": str(exc)}
