"""Core functionality tests for IntelligentCache library."""

import time
import pytest
from intelligent_cache import (
    IntelligentCache,
    CacheConfig,
    CacheHitType,
    CacheResult,
    DefaultEmbedder,
    MemoryBackend,
)


def test_cache_init_and_config():
    cache = IntelligentCache(
        similarity_threshold=0.88,
        default_ttl=1800,
        namespace="custom_ns",
    )
    assert cache.config.similarity_threshold == 0.88
    assert cache.config.default_ttl == 1800
    assert cache.config.namespace == "custom_ns"
    assert isinstance(cache.backend, MemoryBackend)
    assert isinstance(cache.embedder, DefaultEmbedder)


def test_exact_match_caching():
    cache = IntelligentCache(similarity_threshold=0.85)
    query = "What is the airspeed velocity of an unladen swallow?"
    response = "African or European?"

    # First lookup -> Miss
    miss = cache.get(query)
    assert miss is None

    # Set cache
    stored = cache.set(query, response, ttl=3600)
    assert stored is True

    # Exact lookup -> Hit
    hit = cache.get(query)
    assert hit is not None
    assert hit.is_hit is True
    assert hit.hit_type == CacheHitType.EXACT
    assert hit.value == response
    assert hit.similarity_score == 1.0


def test_semantic_match_caching():
    cache = IntelligentCache(similarity_threshold=0.70)
    query = "How do I calculate the area of a circle?"
    response = "The formula is pi * r^2."

    cache.set(query, response, ttl=3600)

    # Semantically close variation
    variation = "How can I find area of circle?"
    hit = cache.get(variation)
    assert hit is not None
    assert hit.is_hit is True
    assert hit.hit_type == CacheHitType.SEMANTIC
    assert hit.value == response
    assert hit.similarity_score >= 0.70

    # Unrelated query -> Miss
    unrelated = "Where is the Eiffel Tower located?"
    miss = cache.get(unrelated)
    assert miss is None


def test_namespace_isolation():
    cache = IntelligentCache(similarity_threshold=0.80)
    query = "Explain quantum computing"

    cache.set(query, "Explanation from GPT-4", namespace="gpt-4")
    cache.set(query, "Explanation from Claude", namespace="claude")

    hit_gpt = cache.get(query, namespace="gpt-4")
    hit_claude = cache.get(query, namespace="claude")
    hit_default = cache.get(query, namespace="default")

    assert hit_gpt is not None and hit_gpt.value == "Explanation from GPT-4"
    assert hit_claude is not None and hit_claude.value == "Explanation from Claude"
    assert hit_default is None


def test_ttl_expiration():
    cache = IntelligentCache(similarity_threshold=0.85)
    query = "Transient ephemeral data"

    # Set with 1 second TTL
    cache.set(query, "temporary_val", ttl=1)
    assert cache.get(query) is not None

    # Wait for expiration
    time.sleep(1.1)
    assert cache.get(query) is None


def test_get_or_compute_sync():
    cache = IntelligentCache(similarity_threshold=0.85)
    compute_count = 0

    def expensive_llm_call():
        nonlocal compute_count
        compute_count += 1
        return "expensive output"

    # First call computes
    res1 = cache.get_or_compute("test prompt", expensive_llm_call)
    assert res1 == "expensive output"
    assert compute_count == 1

    # Second call hits cache
    res2 = cache.get_or_compute("test prompt", expensive_llm_call)
    assert res2 == "expensive output"
    assert compute_count == 1


@pytest.mark.asyncio
async def test_get_or_compute_async():
    cache = IntelligentCache(similarity_threshold=0.85)
    compute_count = 0

    async def expensive_async_call():
        nonlocal compute_count
        compute_count += 1
        return "expensive async output"

    res1 = await cache.aget_or_compute("async prompt", expensive_async_call)
    assert res1 == "expensive async output"
    assert compute_count == 1

    res2 = await cache.aget_or_compute("async prompt", expensive_async_call)
    assert res2 == "expensive async output"
    assert compute_count == 1


def test_invalidation_by_key_and_query():
    cache = IntelligentCache()
    cache.set("query_alpha", "response_alpha")
    cache.set("query_beta", "response_beta")

    assert cache.get("query_alpha") is not None
    assert cache.get("query_beta") is not None

    # Invalidate query_alpha
    del_count = cache.invalidate(query="query_alpha")
    assert del_count == 1
    assert cache.get("query_alpha") is None
    assert cache.get("query_beta") is not None


def test_invalidation_by_namespace():
    cache = IntelligentCache()
    cache.set("q1", "r1", namespace="ns_test")
    cache.set("q2", "r2", namespace="ns_test")
    cache.set("q3", "r3", namespace="ns_other")

    deleted = cache.invalidate(namespace="ns_test")
    assert deleted == 2
    assert cache.get("q1", namespace="ns_test") is None
    assert cache.get("q2", namespace="ns_test") is None
    assert cache.get("q3", namespace="ns_other") is not None


def test_invalidation_by_tag():
    cache = IntelligentCache()
    cache.set("q1", "r1", tags=["v1", "finance"])
    cache.set("q2", "r2", tags=["v2", "finance"])
    cache.set("q3", "r3", tags=["v1", "legal"])

    deleted = cache.invalidate(tag="finance")
    assert deleted == 2
    assert cache.get("q1") is None
    assert cache.get("q2") is None
    assert cache.get("q3") is not None


def test_invalidation_by_semantic_radius():
    cache = IntelligentCache(similarity_threshold=0.60)
    cache.set("refund policy inquiry", "Refunds available within 30 days.")
    cache.set("shipping questions", "Shipping takes 3-5 days.")

    # Invalidate anything semantically similar to refund policy
    deleted = cache.invalidate(semantic_query="refund policy", radius=0.60)
    assert deleted >= 1
    assert cache.get("refund policy inquiry") is None
    assert cache.get("shipping questions") is not None
