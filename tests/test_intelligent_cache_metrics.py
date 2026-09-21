"""Tests for cache metrics and analytics collector."""

from intelligent_cache import (
    CacheHitType,
    MetricsCollector,
)


def test_metrics_tracking():
    collector = MetricsCollector(
        cost_per_1k_prompt_tokens=0.005,
        cost_per_1k_completion_tokens=0.015,
    )

    # 1. Record Exact Hit
    collector.record_hit(
        hit_type=CacheHitType.EXACT,
        latency_ms=250.0,
        prompt_tokens=100,
        completion_tokens=200,
        namespace="gpt-4o",
    )

    # 2. Record Semantic Hit
    collector.record_hit(
        hit_type=CacheHitType.SEMANTIC,
        latency_ms=180.0,
        prompt_tokens=50,
        completion_tokens=100,
        namespace="gpt-4o",
    )

    # 3. Record Tool Hit
    collector.record_hit(
        hit_type=CacheHitType.TOOL,
        latency_ms=50.0,
        namespace="tools",
    )

    # 4. Record Miss
    collector.record_miss(namespace="gpt-4o")

    stats = collector.get_stats()
    assert stats.total_requests == 4
    assert stats.total_hits == 3
    assert stats.exact_hits == 1
    assert stats.semantic_hits == 1
    assert stats.tool_hits == 1
    assert stats.misses == 1
    assert stats.hit_rate == 0.75
    assert stats.latency_saved_ms == 480.0
    assert stats.avg_latency_saved_ms == 160.0
    assert stats.prompt_tokens_saved == 150
    assert stats.completion_tokens_saved == 300
    assert stats.total_tokens_saved == 450
    assert stats.cost_saved_usd > 0.0

    # Namespace check
    ns = stats.per_namespace
    assert "gpt-4o" in ns
    assert ns["gpt-4o"]["requests"] == 3
    assert ns["gpt-4o"]["exact_hits"] == 1
    assert ns["gpt-4o"]["semantic_hits"] == 1
    assert ns["gpt-4o"]["misses"] == 1


def test_prometheus_exposition():
    collector = MetricsCollector()
    collector.record_hit(hit_type=CacheHitType.EXACT, latency_ms=100.0)
    collector.record_miss()

    prom_text = collector.to_prometheus()
    assert "intelligent_cache_requests_total 2" in prom_text
    assert "intelligent_cache_hits_total{type=\"exact\"} 1" in prom_text
    assert "intelligent_cache_misses_total 1" in prom_text
    assert "intelligent_cache_hit_rate 0.5" in prom_text


def test_metrics_reset():
    collector = MetricsCollector()
    collector.record_hit(hit_type=CacheHitType.EXACT)
    assert collector.get_stats().total_hits == 1

    collector.reset()
    assert collector.get_stats().total_hits == 0
    assert collector.get_stats().total_requests == 0
