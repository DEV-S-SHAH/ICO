"""Analytics and metrics collection for cache operations."""

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from intelligent_cache.core.entry import CacheHitType


@dataclass
class CacheStats:
    """Snapshot of cache performance metrics."""

    total_requests: int = 0
    total_hits: int = 0
    exact_hits: int = 0
    semantic_hits: int = 0
    tool_hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    latency_saved_ms: float = 0.0
    avg_latency_saved_ms: float = 0.0
    prompt_tokens_saved: int = 0
    completion_tokens_saved: int = 0
    total_tokens_saved: int = 0
    cost_saved_usd: float = 0.0
    per_namespace: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class MetricsCollector:
    """Thread-safe collector for cache hit/miss and resource savings metrics."""

    def __init__(
        self,
        cost_per_1k_prompt_tokens: float = 0.005,
        cost_per_1k_completion_tokens: float = 0.015,
    ):
        self.cost_prompt_1k = cost_per_1k_prompt_tokens
        self.cost_comp_1k = cost_per_1k_completion_tokens
        self._lock = threading.RLock()

        self._total_requests = 0
        self._exact_hits = 0
        self._semantic_hits = 0
        self._tool_hits = 0
        self._misses = 0
        self._latency_saved_ms = 0.0
        self._prompt_tokens_saved = 0
        self._completion_tokens_saved = 0
        self._cost_saved_usd = 0.0
        self._per_namespace: dict[str, dict[str, int]] = {}

    def _get_ns_dict(self, ns: str) -> dict[str, int]:
        if ns not in self._per_namespace:
            self._per_namespace[ns] = {
                "requests": 0,
                "exact_hits": 0,
                "semantic_hits": 0,
                "tool_hits": 0,
                "misses": 0,
            }
        return self._per_namespace[ns]

    def record_hit(
        self,
        hit_type: CacheHitType,
        latency_ms: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_saved: Optional[float] = None,
        namespace: str = "default",
    ) -> None:
        """Record a cache hit event."""
        with self._lock:
            self._total_requests += 1
            ns_dict = self._get_ns_dict(namespace)
            ns_dict["requests"] += 1

            if hit_type == CacheHitType.EXACT:
                self._exact_hits += 1
                ns_dict["exact_hits"] += 1
            elif hit_type == CacheHitType.SEMANTIC:
                self._semantic_hits += 1
                ns_dict["semantic_hits"] += 1
            elif hit_type == CacheHitType.TOOL:
                self._tool_hits += 1
                ns_dict["tool_hits"] += 1

            self._latency_saved_ms += max(0.0, latency_ms)
            self._prompt_tokens_saved += max(0, prompt_tokens)
            self._completion_tokens_saved += max(0, completion_tokens)

            if cost_saved is not None:
                self._cost_saved_usd += cost_saved
            else:
                calc_cost = (
                    (prompt_tokens / 1000.0) * self.cost_prompt_1k
                    + (completion_tokens / 1000.0) * self.cost_comp_1k
                )
                self._cost_saved_usd += calc_cost

    def record_miss(self, namespace: str = "default") -> None:
        """Record a cache miss event."""
        with self._lock:
            self._total_requests += 1
            self._misses += 1
            ns_dict = self._get_ns_dict(namespace)
            ns_dict["requests"] += 1
            ns_dict["misses"] += 1

    def get_stats(self) -> CacheStats:
        """Return a snapshot of current statistics."""
        with self._lock:
            total_hits = self._exact_hits + self._semantic_hits + self._tool_hits
            hit_rate = (total_hits / self._total_requests) if self._total_requests > 0 else 0.0
            avg_latency = (self._latency_saved_ms / total_hits) if total_hits > 0 else 0.0
            total_tokens = self._prompt_tokens_saved + self._completion_tokens_saved

            return CacheStats(
                total_requests=self._total_requests,
                total_hits=total_hits,
                exact_hits=self._exact_hits,
                semantic_hits=self._semantic_hits,
                tool_hits=self._tool_hits,
                misses=self._misses,
                hit_rate=round(hit_rate, 4),
                latency_saved_ms=round(self._latency_saved_ms, 2),
                avg_latency_saved_ms=round(avg_latency, 2),
                prompt_tokens_saved=self._prompt_tokens_saved,
                completion_tokens_saved=self._completion_tokens_saved,
                total_tokens_saved=total_tokens,
                cost_saved_usd=round(self._cost_saved_usd, 5),
                per_namespace=dict(self._per_namespace),
            )

    def to_prometheus(self) -> str:
        """Export metrics formatted for Prometheus scraper."""
        stats = self.get_stats()
        lines = [
            "# HELP intelligent_cache_requests_total Total cache requests",
            "# TYPE intelligent_cache_requests_total counter",
            f"intelligent_cache_requests_total {stats.total_requests}",
            "# HELP intelligent_cache_hits_total Total cache hits",
            "# TYPE intelligent_cache_hits_total counter",
            f"intelligent_cache_hits_total{{type=\"exact\"}} {stats.exact_hits}",
            f"intelligent_cache_hits_total{{type=\"semantic\"}} {stats.semantic_hits}",
            f"intelligent_cache_hits_total{{type=\"tool\"}} {stats.tool_hits}",
            "# HELP intelligent_cache_misses_total Total cache misses",
            "# TYPE intelligent_cache_misses_total counter",
            f"intelligent_cache_misses_total {stats.misses}",
            "# HELP intelligent_cache_hit_rate Overall cache hit rate",
            "# TYPE intelligent_cache_hit_rate gauge",
            f"intelligent_cache_hit_rate {stats.hit_rate}",
            "# HELP intelligent_cache_latency_saved_ms Total latency saved in milliseconds",
            "# TYPE intelligent_cache_latency_saved_ms counter",
            f"intelligent_cache_latency_saved_ms {stats.latency_saved_ms}",
            "# HELP intelligent_cache_tokens_saved Total LLM tokens saved",
            "# TYPE intelligent_cache_tokens_saved counter",
            f"intelligent_cache_tokens_saved {stats.total_tokens_saved}",
            "# HELP intelligent_cache_cost_saved_usd Total inference cost saved in USD",
            "# TYPE intelligent_cache_cost_saved_usd counter",
            f"intelligent_cache_cost_saved_usd {stats.cost_saved_usd}",
        ]
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Reset all metrics to zero."""
        with self._lock:
            self._total_requests = 0
            self._exact_hits = 0
            self._semantic_hits = 0
            self._tool_hits = 0
            self._misses = 0
            self._latency_saved_ms = 0.0
            self._prompt_tokens_saved = 0
            self._completion_tokens_saved = 0
            self._cost_saved_usd = 0.0
            self._per_namespace.clear()
