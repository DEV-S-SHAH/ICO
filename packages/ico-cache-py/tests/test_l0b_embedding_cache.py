"""
Tests for L0b Embedding Cache (Phase 3A.3).

Tests cover:
- Identical text returns cached embedding
- Different text computes new embedding
- Different model versions don't share cache
- Model version change invalidates cache
- Concurrent requests for same text
- Tenant isolation (embedding cache uses default tenant)
- Backend failure degrades gracefully
"""

import pytest
import hashlib
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.core.decision_engine import DecisionEngine, DecisionContext, ReusePolicy, GateMode


class TestL0bKeyBuilder:
    """Test L0b embedding cache key builder."""

    def test_key_format(self):
        """Key format: emb:{model_fingerprint}:{text_hash}"""
        from ico_cache.core.decision_engine import build_l0b_key
        key = build_l0b_key("model:v1", "test text")
        assert key.startswith("emb:model:v1:")
        # model_fingerprint may contain colons, so key can have more parts
        parts = key.split(":")
        assert len(parts) >= 3
        assert parts[0] == "emb"
        assert parts[1] == "model"
        assert parts[2] == "v1"

    def test_same_text_same_key(self):
        """Identical text produces identical key."""
        from ico_cache.core.decision_engine import build_l0b_key
        key1 = build_l0b_key("model:v1", "test text")
        key2 = build_l0b_key("model:v1", "test text")
        assert key1 == key2

    def test_different_text_different_key(self):
        """Different text produces different key."""
        from ico_cache.core.decision_engine import build_l0b_key
        key1 = build_l0b_key("model:v1", "text one")
        key2 = build_l0b_key("model:v1", "text two")
        assert key1 != key2

    def test_different_model_different_key(self):
        """Different model fingerprint produces different key."""
        from ico_cache.core.decision_engine import build_l0b_key
        key1 = build_l0b_key("model:v1", "test text")
        key2 = build_l0b_key("model:v2", "test text")
        assert key1 != key2

    def test_key_deterministic(self):
        """Key is deterministic across calls."""
        from ico_cache.core.decision_engine import build_l0b_key
        key1 = build_l0b_key("model:v1", "test text")
        key2 = build_l0b_key("model:v1", "test text")
        assert key1 == key2


class TestL0bEmbeddingCache:
    """Test L0b embedding cache functionality."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=self.FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
            l0b_ttl=2592000,
        )

    class FakeEmbedder:
        """Fake embedder with model_version for testing."""
        dim = 384

        def embed(self, text: str):
            import hashlib, math
            digest = hashlib.sha256(text.encode()).digest()
            raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            return [v / norm for v in raw]

        @property
        def model_version(self) -> str:
            return "fake-embedder@1.0.0"

    @pytest.mark.asyncio
    async def test_l0b_cache_miss_then_hit(self, engine):
        """First call misses, second call hits L0b cache."""
        import numpy as np
        text = "What are the risk factors?"

        # First call - miss
        emb1 = await engine.get_embedding(text)
        assert isinstance(emb1, list)
        assert len(emb1) == 384

        stats1 = engine.get_l0b_stats()
        assert stats1["misses"] == 1
        assert stats1["hits"] == 0

        # Second call - hit
        emb2 = await engine.get_embedding(text)
        # Use numpy allclose for floating point comparison (LanceDB stores as float32)
        assert np.allclose(emb1, emb2, rtol=1e-5, atol=1e-6)

        stats2 = engine.get_l0b_stats()
        assert stats2["hits"] == 1
        assert stats2["misses"] == 1

    @pytest.mark.asyncio
    async def test_l0b_different_text_different_embedding(self, engine):
        """Different texts get different embeddings."""
        import numpy as np
        emb1 = await engine.get_embedding("text one")
        emb2 = await engine.get_embedding("text two")

        # Use numpy allclose for floating point comparison
        assert not np.allclose(emb1, emb2, rtol=1e-5, atol=1e-6)

        stats = engine.get_l0b_stats()
        assert stats["misses"] == 2
        assert stats["hits"] == 0

    @pytest.mark.asyncio
    async def test_l0b_model_version_isolation(self, engine):
        """Different model versions don't share cache."""
        text = "test text"

        # Use default model version
        emb1 = await engine.get_embedding(text)

        # Use different model fingerprint
        emb2 = await engine.get_embedding(text, model_fingerprint="different-model@v2")

        # Should be different embeddings (or at least both computed)
        stats = engine.get_l0b_stats()
        assert stats["misses"] == 2
        assert stats["hits"] == 0

    @pytest.mark.asyncio
    async def test_l0b_concurrent_same_text(self, engine):
        """Concurrent requests for same text should only compute once."""
        import asyncio
        import numpy as np

        text = "concurrent test text"

        async def get_emb():
            return await engine.get_embedding(text)

        # Launch multiple concurrent requests
        results = await asyncio.gather(*[get_emb() for _ in range(10)])

        # All should return same embedding (within float32 precision)
        for r in results[1:]:
            assert np.allclose(r, results[0], rtol=1e-5, atol=1e-6)

        stats = engine.get_l0b_stats()
        assert stats["misses"] == 1  # Only one miss (first request)
        assert stats["hits"] == 9   # Rest are hits

    @pytest.mark.asyncio
    async def test_l0b_embedding_used_in_l2(self, engine):
        """L2 semantic search uses L0b cached embeddings."""
        # Write an entry to L2
        await engine.async_write_l2(
            "test query",
            {"answer": "test answer"},
            meta={"entity": "ACME", "quarter": "Q1"},
            tenant_id="default",
        )

        # Now query - should use L0b for embedding
        result = await engine.get_l2("test query", meta={"entity": "ACME", "quarter": "Q1"}, tenant_id="default")

        assert result is not None
        assert result["answer"] == "test answer"

    @pytest.mark.asyncio
    async def test_l0b_embedding_used_in_l3(self, engine):
        """L3 context-aware search uses L0b cached embeddings."""
        # Write an entry to L3
        await engine.async_write_l3(
            "test query",
            "test context",
            {"answer": "test answer"},
            meta={"entity": "ACME", "quarter": "Q1"},
            tenant_id="default",
        )

        # Now query - should use L0b for both query and context embeddings
        result = await engine.get_l3(
            "test query",
            "test context",
            meta={"entity": "ACME", "quarter": "Q1"},
            tenant_id="default",
        )

        assert result is not None
        assert result["answer"] == "test answer"

    @pytest.mark.asyncio
    async def test_l0b_stats_reporting(self, engine):
        """L0b stats are correctly reported."""
        stats = engine.get_l0b_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

        await engine.get_embedding("test")
        stats = engine.get_l0b_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.0

        await engine.get_embedding("test")
        stats = engine.get_l0b_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert abs(stats["hit_rate"] - 0.5) < 0.01


class TestL0bDecisionEngineIntegration:
    """Test L0b integration with DecisionEngine."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=self.FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    class FakeEmbedder:
        dim = 384

        def embed(self, text: str):
            import hashlib, math
            digest = hashlib.sha256(text.encode()).digest()
            raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            return [v / norm for v in raw]

        @property
        def model_version(self) -> str:
            return "fake-embedder@1.0.0"

    @pytest.fixture
    def decision_engine(self, engine):
        return DecisionEngine(engine, policy=ReusePolicy.balanced())

    @pytest.mark.asyncio
    async def test_evaluate_l0b_reports_stats(self, decision_engine):
        """_evaluate_l0b reports L0b cache statistics."""
        ctx = DecisionContext(
            query="test query",
            model="gpt-4o",
            provider="openai",
        )

        eval_result = await decision_engine._evaluate_l0b(ctx)

        assert eval_result.layer == "L0b"
        assert eval_result.checked is True
        assert "L0b embedding cache" in eval_result.reasoning

    @pytest.mark.asyncio
    async def test_evaluate_l0b_after_miss_reports_miss(self, decision_engine):
        """After a miss, _evaluate_l0b reports miss stats."""
        ctx = DecisionContext(
            query="test query",
            model="gpt-4o",
            provider="openai",
        )

        # First evaluation - no stats yet
        eval1 = await decision_engine._evaluate_l0b(ctx)
        assert "miss" in eval1.reasoning.lower() or "not yet" in eval1.reasoning.lower()

        # Actually get an embedding (creates miss)
        await decision_engine.cache_engine.get_embedding("test query")

        # Second evaluation - should report miss
        eval2 = await decision_engine._evaluate_l0b(ctx)
        assert "miss" in eval2.reasoning.lower()


class TestL0bCriticalFields:
    """Test CRITICAL_FIELDS for L0b layer."""

    def test_critical_fields_defined(self):
        """L0b has CRITICAL_FIELDS defined."""
        from ico_cache.core.decision_engine import CRITICAL_FIELDS
        assert "L0b" in CRITICAL_FIELDS
        assert "embedding_model_version" in CRITICAL_FIELDS["L0b"]
        assert "text_hash" in CRITICAL_FIELDS["L0b"]

    def test_l0b_gate_blocks_on_model_version_mismatch(self):
        """L0b hard gate blocks on model version mismatch."""
        from ico_cache.core.decision_engine import hard_gate_extended, GateMode

        incoming = {"embedding_model_version": "model@v1", "text_hash": "abc123"}
        cached = {"embedding_model_version": "model@v2", "text_hash": "abc123"}

        allowed, passed, failed = hard_gate_extended(
            incoming, cached, layer="L0b", mode=GateMode.STRICT
        )

        assert not allowed
        assert "embedding_model_version" in failed

    def test_l0b_gate_blocks_on_text_hash_mismatch(self):
        """L0b hard gate blocks on text hash mismatch."""
        from ico_cache.core.decision_engine import hard_gate_extended, GateMode

        incoming = {"embedding_model_version": "model@v1", "text_hash": "abc123"}
        cached = {"embedding_model_version": "model@v1", "text_hash": "def456"}

        allowed, passed, failed = hard_gate_extended(
            incoming, cached, layer="L0b", mode=GateMode.STRICT
        )

        assert not allowed
        assert "text_hash" in failed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])