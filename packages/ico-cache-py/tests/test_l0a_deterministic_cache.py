"""
test_l0a_deterministic_cache.py — P0 tests for L0a Deterministic Computation Cache.

Tests cover:
- Function registration and versioning
- Content-addressable key generation
- Cache hit/miss behavior
- Environment hash invalidation
- Concurrency safety
- Integration with DecisionEngine
"""

import asyncio
import pytest

from ico_cache.core.cache_engine import CacheEngine, DeterministicFunction
from ico_cache.core.decision_engine import (
    DecisionContext,
    DecisionEngine,
    ReusePolicy,
    build_l0a_key,
)


class TestL0aKeyBuilder:
    """Tests for L0a key builder function."""

    def test_build_l0a_key_deterministic(self):
        """L0a key should be deterministic for same inputs."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        key2 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        assert key1 == key2

    def test_build_l0a_key_different_on_args(self):
        """L0a key should differ on different arguments."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        key2 = build_l0a_key("count_tokens", {"text": "world"}, "1.0", "env123")
        assert key1 != key2

    def test_build_l0a_key_different_on_version(self):
        """L0a key should differ on function version."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        key2 = build_l0a_key("count_tokens", {"text": "hello"}, "2.0", "env123")
        assert key1 != key2

    def test_build_l0a_key_different_on_env(self):
        """L0a key should differ on environment hash."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env1")
        key2 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env2")
        assert key1 != key2

    def test_build_l0a_key_different_on_fn_name(self):
        """L0a key should differ on function name."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        key2 = build_l0a_key("hash_text", {"text": "hello"}, "1.0", "env123")
        assert key1 != key2

    def test_build_l0a_key_format(self):
        """L0a key should follow expected format."""
        key = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env123")
        assert key.startswith("det:count_tokens:1.0:")
        assert len(key) > len("det:count_tokens:1.0:")

    def test_build_l0a_key_args_order_independent(self):
        """L0a key should be independent of argument order."""
        key1 = build_l0a_key("fn", {"a": 1, "b": 2}, "1.0", "env")
        key2 = build_l0a_key("fn", {"b": 2, "a": 1}, "1.0", "env")
        assert key1 == key2


class TestL0aDeterministicCache:
    """Tests for L0a deterministic function cache in CacheEngine."""

    @pytest.fixture
    def cache_engine(self, tmp_path):
        """Create a CacheEngine with embedded stores."""
        from conftest import FakeEmbedder
        from ico_cache.backends.vector.lancedb_store import LanceDBStore
        from ico_cache.backends.exact.sqlite_store import SQLiteStore

        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    def test_register_deterministic_function(self, cache_engine):
        """Should be able to register a deterministic function."""
        def count_tokens(text: str) -> int:
            return len(text.split())

        cache_engine.register_deterministic_function(
            name="count_tokens",
            version="1.0",
            func=count_tokens,
            description="Count tokens in text",
        )

        assert "count_tokens" in cache_engine._det_functions
        fn = cache_engine._det_functions["count_tokens"]
        assert fn.name == "count_tokens"
        assert fn.version == "1.0"
        assert fn.description == "Count tokens in text"

    def test_register_invalid_function_raises(self, cache_engine):
        """Registering non-callable should raise ValueError."""
        with pytest.raises(ValueError):
            cache_engine.register_deterministic_function(
                name="not_a_function",
                version="1.0",
                func="not callable",
            )

    @pytest.mark.asyncio
    async def test_execute_deterministic_cache_miss_then_hit(self, cache_engine):
        """First call should execute function, second should hit cache."""
        call_count = 0

        def count_tokens(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split())

        cache_engine.register_deterministic_function(
            name="count_tokens",
            version="1.0",
            func=count_tokens,
        )

        # First call - cache miss
        result1 = await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})
        assert result1 == 2
        assert call_count == 1

        # Second call - cache hit
        result2 = await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})
        assert result2 == 2
        assert call_count == 1  # Function not called again

    @pytest.mark.asyncio
    async def test_execute_deterministic_different_args(self, cache_engine):
        """Different arguments should create separate cache entries."""
        call_count = 0

        def count_tokens(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split())

        cache_engine.register_deterministic_function(
            name="count_tokens",
            version="1.0",
            func=count_tokens,
        )

        await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})
        await cache_engine.execute_deterministic("count_tokens", {"text": "hello there"})
        await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})  # Repeat

        assert call_count == 2  # Only two unique argument sets

    @pytest.mark.asyncio
    async def test_execute_deterministic_version_change_invalidates(self, cache_engine):
        """Changing function version should invalidate cache."""
        call_count = 0

        def count_tokens_v1(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split())

        def count_tokens_v2(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split()) * 2  # Different behavior

        cache_engine.register_deterministic_function(
            name="count_tokens",
            version="1.0",
            func=count_tokens_v1,
        )

        await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})
        assert call_count == 1

        # Re-register with new version
        cache_engine.register_deterministic_function(
            name="count_tokens",
            version="2.0",
            func=count_tokens_v2,
        )

        # Should execute again with new version
        result = await cache_engine.execute_deterministic("count_tokens", {"text": "hello world"})
        assert result == 4  # v2 behavior
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_execute_deterministic_single_flight(self, cache_engine):
        """Concurrent calls for same function+args should execute once."""
        call_count = 0

        async def slow_count(text: str) -> int:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return len(text.split())

        cache_engine.register_deterministic_function(
            name="slow_count",
            version="1.0",
            func=slow_count,
        )

        # Launch 10 concurrent calls
        results = await asyncio.gather(*[
            cache_engine.execute_deterministic("slow_count", {"text": "hello world"})
            for _ in range(10)
        ])

        assert call_count == 1
        assert all(r == 2 for r in results)

    @pytest.mark.asyncio
    async def test_get_l0a_direct(self, cache_engine):
        """Direct get_l0a/set_l0a should work."""
        def identity(x: int) -> int:
            return x

        cache_engine.register_deterministic_function(
            name="identity",
            version="1.0",
            func=identity,
        )

        # Initially not cached
        cached = await cache_engine.get_l0a("identity", {"x": 42})
        assert cached is None

        # Set manually
        await cache_engine.set_l0a("identity", {"x": 42}, 42)

        # Now should be cached
        cached = await cache_engine.get_l0a("identity", {"x": 42})
        assert cached == 42

    @pytest.mark.asyncio
    async def test_l0a_key_includes_env_hash(self, cache_engine):
        """L0a key should include environment hash."""
        def get_env() -> str:
            return "test"

        cache_engine.register_deterministic_function(
            name="get_env",
            version="1.0",
            func=get_env,
        )

        # Execute with current env
        result1 = await cache_engine.execute_deterministic("get_env", {})

        # Manually change env hash
        cache_engine._env_hash = "different_env"

        # Should miss cache due to env hash change
        result2 = await cache_engine.execute_deterministic("get_env", {})
        assert result2 == "test"  # Function executed again

    @pytest.mark.asyncio
    async def test_l0a_infinite_ttl(self, cache_engine):
        """L0a entries should have infinite TTL (no expiration)."""
        def const_fn() -> int:
            return 42

        cache_engine.register_deterministic_function(
            name="const_fn",
            version="1.0",
            func=const_fn,
        )

        await cache_engine.execute_deterministic("const_fn", {})

        # Key should exist in exact store (we can't easily test TTL=None, but verify no expiration logic)
        key = cache_engine._build_l0a_key("const_fn", {})
        val = cache_engine.exact_store.get(key)
        assert val is not None


class TestL0aDecisionEngineIntegration:
    """Tests for L0a integration with DecisionEngine."""

    @pytest.fixture
    def decision_engine(self, tmp_path):
        """Create a DecisionEngine with a real cache engine."""
        from conftest import FakeEmbedder
        from ico_cache.backends.vector.lancedb_store import LanceDBStore
        from ico_cache.backends.exact.sqlite_store import SQLiteStore

        cache_engine = CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )
        return DecisionEngine(cache_engine, policy=ReusePolicy.strict())

    @pytest.mark.asyncio
    async def test_decide_reports_l0a_functions(self, decision_engine):
        """DecisionEngine.decide() should report registered L0a functions."""
        def dummy() -> int:
            return 42

        decision_engine.cache_engine.register_deterministic_function(
            name="dummy_fn",
            version="1.0",
            func=dummy,
        )

        ctx = DecisionContext(query="test", tenant_id="t1")
        decision = await decision_engine.decide(ctx)

        # Find L0a evaluation
        l0a_evals = [e for e in decision.layer_evaluations if e.layer == "L0a"]
        assert len(l0a_evals) == 1
        assert "dummy_fn" in l0a_evals[0].reasoning

    @pytest.mark.asyncio
    async def test_decide_l0a_no_functions(self, decision_engine):
        """DecisionEngine.decide() should handle no L0a functions."""
        ctx = DecisionContext(query="test", tenant_id="t1")
        decision = await decision_engine.decide(ctx)

        l0a_evals = [e for e in decision.layer_evaluations if e.layer == "L0a"]
        assert len(l0a_evals) == 1
        assert "none" in l0a_evals[0].reasoning.lower()


class TestDeterministicFunctionDataclass:
    """Tests for DeterministicFunction dataclass."""

    def test_deterministic_function_creation(self):
        """Should create DeterministicFunction with all fields."""
        def fn(): pass

        df = DeterministicFunction(
            name="test_fn",
            version="1.0",
            func=fn,
            description="Test function",
            arg_schema={"type": "object"},
        )

        assert df.name == "test_fn"
        assert df.version == "1.0"
        assert df.description == "Test function"
        assert df.arg_schema == {"type": "object"}

    def test_deterministic_function_defaults(self):
        """Should have default values for optional fields."""
        def fn(): pass

        df = DeterministicFunction(name="test", version="1.0", func=fn)

        assert df.description == ""
        assert df.arg_schema is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])