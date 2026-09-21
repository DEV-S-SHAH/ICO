"""Persistent Backends Example: SQLite, Redis, Disk.

Demonstrates configuring persistent backends with zero code changes to application logic.
"""

from intelligent_cache import IntelligentCache

# =====================================================================
# 1. SQLite Persistent Storage Backend (Zero-setup local persistence)
# =====================================================================
print("1. Initializing SQLite Persistent Cache...")
sqlite_cache = IntelligentCache(
    backend="sqlite",
    sqlite_path=".cache/example_cache.db",
    similarity_threshold=0.80,
    default_ttl=86400, # 24 hours
)

sqlite_cache.set("What is SQLite?", "SQLite is a C-language library that implements a SQL database engine.")
hit = sqlite_cache.get("What is SQLite?")
print(f"SQLite Hit: {hit.value if hit else 'Miss'}")
print(f"SQLite Backend Stats: {sqlite_cache.backend_stats()}")


# =====================================================================
# 2. Disk Storage Backend (Folder of JSON entries)
# =====================================================================
print("\n2. Initializing Disk Storage Cache...")
disk_cache = IntelligentCache(
    backend="disk",
    disk_dir=".cache/example_disk_cache",
    similarity_threshold=0.80,
)
disk_cache.set("What is Docker?", "Docker packages code and dependencies in containers.")
print(f"Disk Hit: {disk_cache.get('What is Docker?').value}")
print(f"Disk Backend Stats: {disk_cache.backend_stats()}")


# =====================================================================
# 3. Redis Distributed Storage Backend (Multi-node / production cluster)
# =====================================================================
print("\n3. Demonstrating Redis Cache configuration:")
print("""
# Production Redis Setup:
redis_cache = IntelligentCache(
    backend="redis",
    redis_url="redis://localhost:6379/0",
    similarity_threshold=0.85,
    default_ttl=3600,
)
# If Redis goes offline, IntelligentCache catches the connection error,
# logs a warning, and falls back to executing the LLM without crashing!
""")
