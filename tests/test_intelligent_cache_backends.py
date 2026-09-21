"""Tests for storage backends: Memory, SQLite, Disk, Redis, Postgres."""

import os
import shutil
import pytest
from unittest.mock import MagicMock, patch
from intelligent_cache import (
    CacheEntry,
    MemoryBackend,
    SQLiteBackend,
    DiskBackend,
    RedisBackend,
    PostgresBackend,
)


def test_memory_backend_lru_eviction():
    # Max entries = 3, LRU policy
    backend = MemoryBackend(max_entries=3, eviction_policy="lru")

    entry1 = CacheEntry(key="k1", query="q1", value="v1")
    entry2 = CacheEntry(key="k2", query="q2", value="v2")
    entry3 = CacheEntry(key="k3", query="q3", value="v3")
    entry4 = CacheEntry(key="k4", query="q4", value="v4")

    backend.set("k1", entry1)
    backend.set("k2", entry2)
    backend.set("k3", entry3)

    # Access k1 to make k2 least recently used
    backend.get("k1")

    # Inserting 4th should evict k2
    backend.set("k4", entry4)

    assert backend.get("k1") is not None
    assert backend.get("k2") is None  # Evicted!
    assert backend.get("k3") is not None
    assert backend.get("k4") is not None

    stats = backend.stats()
    assert stats["evictions"] == 1
    assert stats["total_entries"] == 3


def test_memory_backend_lfu_eviction():
    backend = MemoryBackend(max_entries=2, eviction_policy="lfu")

    entry1 = CacheEntry(key="k1", query="q1", value="v1")
    entry2 = CacheEntry(key="k2", query="q2", value="v2")
    entry3 = CacheEntry(key="k3", query="q3", value="v3")

    backend.set("k1", entry1)
    backend.set("k2", entry2)

    # Touch k1 multiple times so hit_count is higher
    backend.get("k1")
    backend.get("k1")

    # Set k3, k2 has hit_count 0 so it should be evicted
    backend.set("k3", entry3)

    assert backend.get("k1") is not None
    assert backend.get("k2") is None
    assert backend.get("k3") is not None


def test_sqlite_backend_persistence():
    db_path = ".cache/test_backend.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    try:
        backend1 = SQLiteBackend(db_path=db_path)
        entry = CacheEntry(
            key="k_sql",
            query="test query",
            value={"data": "hello sqlite"},
            embedding=[0.1, 0.2, 0.3],
            namespace="db_test",
            tags=["tag1", "tag2"],
        )
        backend1.set("k_sql", entry)
        backend1.close()

        # Reopen with new instance
        backend2 = SQLiteBackend(db_path=db_path)
        fetched = backend2.get("k_sql")
        assert fetched is not None
        assert fetched.value == {"data": "hello sqlite"}
        assert fetched.embedding == [0.1, 0.2, 0.3]
        assert "tag1" in fetched.tags

        # Test search_similarity
        matches = backend2.search_similarity(
            query_vector=[0.1, 0.2, 0.3],
            threshold=0.99,
            namespace="db_test",
        )
        assert len(matches) == 1
        assert matches[0][0].key == "k_sql"

        # Delete
        assert backend2.delete("k_sql") is True
        assert backend2.get("k_sql") is None
        backend2.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_disk_backend_persistence():
    storage_dir = ".cache/test_disk_backend"
    if os.path.exists(storage_dir):
        shutil.rmtree(storage_dir)

    try:
        disk = DiskBackend(storage_dir=storage_dir)
        entry = CacheEntry(
            key="disk_key",
            query="disk query",
            value="disk value",
            embedding=[0.5, 0.5],
            namespace="disk_ns",
        )
        disk.set("disk_key", entry)

        # Check retrieval
        disk2 = DiskBackend(storage_dir=storage_dir)
        retrieved = disk2.get("disk_key")
        assert retrieved is not None
        assert retrieved.value == "disk value"

        # Stats
        st = disk2.stats()
        assert st["total_entries"] == 1

        # Clear
        disk2.clear()
        assert disk2.get("disk_key") is None
    finally:
        if os.path.exists(storage_dir):
            shutil.rmtree(storage_dir)


def test_redis_backend_with_mock():
    mock_client = MagicMock()
    mock_client.get.return_value = None
    mock_client.ping.return_value = True

    backend = RedisBackend(client=mock_client)
    entry = CacheEntry(
        key="r_key",
        query="redis query",
        value="redis value",
        namespace="r_ns",
    )

    # Set
    mock_client.setex.return_value = True
    assert backend.set("r_key", entry, ttl=60) is True
    mock_client.setex.assert_called_once()

    # Get None
    assert backend.get("missing_key") is None

    # Delete
    mock_client.delete.return_value = 1
    assert backend.delete("r_key") is True


def test_postgres_backend_with_mock():
    backend = PostgresBackend(database_url="postgresql://mock:5432/mockdb")
    mock_engine = MagicMock()
    backend._engine = mock_engine

    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # Set
    entry = CacheEntry(key="p_key", query="pg query", value="pg val")
    mock_conn.execute.return_value.rowcount = 1
    assert backend.set("p_key", entry) is True

    # Delete
    assert backend.delete("p_key") is True
