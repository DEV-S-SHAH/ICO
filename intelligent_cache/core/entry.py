"""CacheEntry, CacheResult, and CacheHitType definitions."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CacheHitType(str, Enum):
    """Enumeration of cache hit types."""
    EXACT = "exact"
    SEMANTIC = "semantic"
    TOOL = "tool"


@dataclass
class CacheEntry:
    """Represents a cached item with full metadata."""

    key: str
    query: str
    value: Any
    embedding: Optional[list[float]] = None
    namespace: str = "default"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    hit_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0

    @property
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def touch(self) -> None:
        """Update last accessed time and increment hit count."""
        self.last_accessed = time.time()
        self.hit_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize cache entry to dictionary."""
        return {
            "key": self.key,
            "query": self.query,
            "value": self.value,
            "embedding": self.embedding,
            "namespace": self.namespace,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "expires_at": self.expires_at,
            "hit_count": self.hit_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        """Deserialize cache entry from dictionary."""
        return cls(
            key=data["key"],
            query=data.get("query", ""),
            value=data["value"],
            embedding=data.get("embedding"),
            namespace=data.get("namespace", "default"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            expires_at=data.get("expires_at"),
            hit_count=data.get("hit_count", 0),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            latency_ms=data.get("latency_ms", 0.0),
        )


@dataclass
class CacheResult:
    """Represents the outcome of a cache lookup."""

    value: Any
    hit_type: Optional[CacheHitType] = None
    similarity_score: Optional[float] = None
    latency_saved_ms: float = 0.0
    key: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt_tokens_saved: int = 0
    completion_tokens_saved: int = 0
    cost_saved_usd: float = 0.0

    @property
    def is_hit(self) -> bool:
        """True if the lookup was a cache hit."""
        return self.hit_type is not None
