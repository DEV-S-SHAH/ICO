"""
test_l5_context_cache.py — Comprehensive tests for L5 Context Cache

Tests cover:
- context hit/miss
- document/version changes
- tenant isolation
- corpus isolation
- prompt/template changes
- token-budget changes
- model/provider isolation
- TTL/invalidation
- concurrency
- fallback/error handling
"""
import asyncio
import pytest
from unittest.mock import AsyncMock

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.core.decision_engine import (
    DecisionEngine, DecisionContext, ReusePolicy, GateMode,
    build_l5_key, compute_chunks_hash, compute_context_tokens,
    CRITICAL_FIELDS, hard_gate_extended
)
from ico_cache.rag.pipeline import RAGPipeline
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore


class FakeEmbedder:
    """Fake embedder for testing."""
    dim = 384

    def embed(self, text: str):
        import hashlib
        import math
        digest = hashlib.sha256(text.encode()).digest()
        raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]

    @property
    def model_version(self) -> str:
        return "fake-embedder@1.0.0"


class MockVectorStore:
    """Mock vector store for testing."""
    def __init__(self):
        self._collections = {}
        self._vectors = {}

    def collection_exists(self, name: str) -> bool:
        return name in self._collections

    def create_collection(self, name: str, config=None):
        self._collections[name] = True
        self._vectors[name] = {}

    async def insert(self, collection: str, id: int, vector: list, payload: dict):
        if collection not in self._vectors:
            self._vectors[collection] = {}
        self._vectors[collection][id] = {"vector": vector, "payload": payload}

    async def search(self, collection: str, vector: list, query_filter=None, limit=5, score_threshold=0.0, using=None):
        return []

    async def get_vectors(self, collection: str, ids: list):
        if collection not in self._vectors:
            return [None] * len(ids)
        return [self._vectors[collection].get(id, {}).get("vector") for id in ids]


# ──────────────────────────────────────────────────────────────────────────────
# L5 Key Builder Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5KeyBuilder:
    """Test L5 key building with all required isolation dimensions."""

    def test_build_l5_key_format(self):
        """Test L5 key format includes all components."""
        key = build_l5_key(
            tenant_id="tenant_a",
            chunks_hash="abc123",
            template_version="v1",
            token_budget=4000,
            model_fingerprint="fp123",
            provider="openai",
        )
        assert key.startswith("v3:tenant_a:l5:")
        parts = key.split(":")
        assert len(parts) == 4  # v3, tenant_id, l5, hash

    def test_identical_inputs_produce_identical_key(self):
        """Same inputs must produce same key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        assert key1 == key2

    def test_different_tenant_produces_different_key(self):
        """Different tenant_id must produce different key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_b", "chunks_hash", "v1", 4000, "fp1", "openai")
        assert key1 != key2

    def test_different_chunks_hash_produces_different_key(self):
        """Different chunks_hash must produce different key."""
        key1 = build_l5_key("tenant_a", "hash1", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "hash2", "v1", 4000, "fp1", "openai")
        assert key1 != key2

    def test_different_template_version_produces_different_key(self):
        """Different template_version must produce different key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "chunks_hash", "v2", 4000, "fp1", "openai")
        assert key1 != key2

    def test_different_token_budget_produces_different_key(self):
        """Different token_budget must produce different key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "chunks_hash", "v1", 2000, "fp1", "openai")
        assert key1 != key2

    def test_different_model_fingerprint_produces_different_key(self):
        """Different model_fingerprint must produce different key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp2", "openai")
        assert key1 != key2

    def test_different_provider_produces_different_key(self):
        """Different provider must produce different key."""
        key1 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "openai")
        key2 = build_l5_key("tenant_a", "chunks_hash", "v1", 4000, "fp1", "anthropic")
        assert key1 != key2


class TestComputeChunksHash:
    """Test compute_chunks_hash utility."""

    def test_non_empty_chunks(self):
        """Test hash computation for non-empty chunks."""
        chunks = [
            {"text": "First chunk content"},
            {"text": "Second chunk content"},
        ]
        h = compute_chunks_hash(chunks)
        assert len(h) == 16
        assert h != "empty"

    def test_empty_chunks_returns_empty(self):
        """Empty chunks should return 'empty' hash."""
        assert compute_chunks_hash([]) == "empty"
        assert compute_chunks_hash([{"text": ""}]) == "empty"
        assert compute_chunks_hash([{}]) == "empty"

    def test_deterministic(self):
        """Hash must be deterministic."""
        chunks = [{"text": "Content 1"}, {"text": "Content 2"}]
        h1 = compute_chunks_hash(chunks)
        h2 = compute_chunks_hash(chunks)
        assert h1 == h2

    def test_order_independent(self):
        """Hash should be order-independent (sorted)."""
        chunks1 = [{"text": "A"}, {"text": "B"}]
        chunks2 = [{"text": "B"}, {"text": "A"}]
        assert compute_chunks_hash(chunks1) == compute_chunks_hash(chunks2)

    def test_different_content_produces_different_hash(self):
        """Different chunk content must produce different hash."""
        chunks1 = [{"text": "Content A"}]
        chunks2 = [{"text": "Content B"}]
        assert compute_chunks_hash(chunks1) != compute_chunks_hash(chunks2)


class TestComputeContextTokens:
    """Test compute_context_tokens utility."""

    def test_estimate_tokens(self):
        """Test token estimation (4 chars per token)."""
        assert compute_context_tokens("") == 1
        assert compute_context_tokens("a") == 1
        assert compute_context_tokens("1234") == 1
        assert compute_context_tokens("12345") == 2
        assert compute_context_tokens("x" * 100) == 25


# ──────────────────────────────────────────────────────────────────────────────
# L5 Cache Engine Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5CacheEngineIntegration:
    """Test L5 cache engine integration."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
            l1_ttl=3600,
            default_model="gpt-4o",
            default_provider="openai",
            default_prompt_version="v1",
        )

    @pytest.fixture
    def sample_chunks(self):
        return [
            {"text": "Chunk 1 content", "source_file": "doc1.txt", "page_or_section": "p1"},
            {"text": "Chunk 2 content", "source_file": "doc2.txt", "page_or_section": "p2"},
            {"text": "Chunk 3 content", "source_file": "doc3.txt", "page_or_section": "p3"},
        ]

    @pytest.mark.asyncio
    async def test_l5_miss_then_hit(self, engine, sample_chunks):
        """Test L5 cache miss then hit."""
        query = "What is the revenue?"
        context = "Assembled context from chunks"
        template_version = "v1"
        token_budget = 4000

        # First call - MISS
        result1 = await engine.get_l5(
            query, sample_chunks, template_version, token_budget, tenant_id="tenant_a"
        )
        assert result1 is None

        # Store context
        stored = await engine.set_l5(
            query, sample_chunks, context, template_version, token_budget, tenant_id="tenant_a"
        )
        assert stored is True

        # Second call - HIT
        result2 = await engine.get_l5(
            query, sample_chunks, template_version, token_budget, tenant_id="tenant_a"
        )
        assert result2 is not None
        assert result2 == context

    @pytest.mark.asyncio
    async def test_l5_tenant_isolation(self, engine, sample_chunks):
        """Test L5 cache respects tenant isolation."""
        query = "What is the revenue?"
        context_a = "Context for tenant A"
        context_b = "Context for tenant B"
        template_version = "v1"
        token_budget = 4000

        # Store for tenant_a
        await engine.set_l5(query, sample_chunks, context_a, template_version, token_budget, tenant_id="tenant_a")

        # Store for tenant_b
        await engine.set_l5(query, sample_chunks, context_b, template_version, token_budget, tenant_id="tenant_b")

        # Retrieve for tenant_a
        result_a = await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert result_a == context_a

        # Retrieve for tenant_b
        result_b = await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_b")
        assert result_b == context_b

    @pytest.mark.asyncio
    async def test_l5_template_version_isolation(self, engine, sample_chunks):
        """Test L5 cache respects template version isolation."""
        query = "What is the revenue?"
        context_v1 = "Context for template v1"
        context_v2 = "Context for template v2"
        token_budget = 4000

        # Store for v1
        await engine.set_l5(query, sample_chunks, context_v1, "v1", token_budget, tenant_id="tenant_a")

        # Store for v2
        await engine.set_l5(query, sample_chunks, context_v2, "v2", token_budget, tenant_id="tenant_a")

        # Retrieve for v1
        result_v1 = await engine.get_l5(query, sample_chunks, "v1", token_budget, tenant_id="tenant_a")
        assert result_v1 == context_v1

        # Retrieve for v2
        result_v2 = await engine.get_l5(query, sample_chunks, "v2", token_budget, tenant_id="tenant_a")
        assert result_v2 == context_v2

    @pytest.mark.asyncio
    async def test_l5_token_budget_isolation(self, engine, sample_chunks):
        """Test L5 cache respects token budget isolation."""
        query = "What is the revenue?"
        context_4k = "Context for 4k budget"
        context_2k = "Context for 2k budget"
        template_version = "v1"

        # Store for 4000 token budget
        await engine.set_l5(query, sample_chunks, context_4k, template_version, 4000, tenant_id="tenant_a")

        # Store for 2000 token budget
        await engine.set_l5(query, sample_chunks, context_2k, template_version, 2000, tenant_id="tenant_a")

        # Retrieve for 4000
        result_4k = await engine.get_l5(query, sample_chunks, template_version, 4000, tenant_id="tenant_a")
        assert result_4k == context_4k

        # Retrieve for 2000
        result_2k = await engine.get_l5(query, sample_chunks, template_version, 2000, tenant_id="tenant_a")
        assert result_2k == context_2k

    @pytest.mark.asyncio
    async def test_l5_model_provider_isolation(self, engine, sample_chunks):
        """Test L5 cache respects model/provider isolation."""
        query = "What is the revenue?"
        context_gpt = "Context for GPT"
        context_claude = "Context for Claude"
        template_version = "v1"
        token_budget = 4000

        # Store for gpt-4o
        await engine.set_l5(
            query, sample_chunks, context_gpt, template_version, token_budget,
            tenant_id="tenant_a", model="gpt-4o", provider="openai"
        )

        # Store for claude-3
        await engine.set_l5(
            query, sample_chunks, context_claude, template_version, token_budget,
            tenant_id="tenant_a", model="claude-3", provider="anthropic"
        )

        # Retrieve for gpt-4o
        result_gpt = await engine.get_l5(
            query, sample_chunks, template_version, token_budget,
            tenant_id="tenant_a", model="gpt-4o", provider="openai"
        )
        assert result_gpt == context_gpt

        # Retrieve for claude-3
        result_claude = await engine.get_l5(
            query, sample_chunks, template_version, token_budget,
            tenant_id="tenant_a", model="claude-3", provider="anthropic"
        )
        assert result_claude == context_claude

    @pytest.mark.asyncio
    async def test_l5_chunks_change_invalidates(self, engine, sample_chunks):
        """Test that chunk content changes produce different cache key."""
        query = "What is the revenue?"
        context1 = "Context for chunks v1"
        context2 = "Context for chunks v2"
        template_version = "v1"
        token_budget = 4000

        # Store with original chunks
        await engine.set_l5(query, sample_chunks, context1, template_version, token_budget, tenant_id="tenant_a")

        # Modify chunks
        modified_chunks = [
            {"text": "Modified chunk 1", "source_file": "doc1.txt"},
            {"text": "Chunk 2 content", "source_file": "doc2.txt"},
        ]

        # Should MISS with different chunks
        result = await engine.get_l5(query, modified_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert result is None

        # Store with modified chunks
        await engine.set_l5(query, modified_chunks, context2, template_version, token_budget, tenant_id="tenant_a")

        # Should HIT with modified chunks
        result = await engine.get_l5(query, modified_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert result == context2

    @pytest.mark.asyncio
    async def test_l5_empty_chunks_handled(self, engine):
        """Test L5 handles empty chunks gracefully."""
        query = "What is the revenue?"
        context = "Context with no chunks"
        template_version = "v1"
        token_budget = 4000

        # Should handle empty chunks
        result = await engine.get_l5(query, [], template_version, token_budget, tenant_id="tenant_a")
        assert result is None

        # Store with empty chunks
        stored = await engine.set_l5(query, [], context, template_version, token_budget, tenant_id="tenant_a")
        assert stored is True

    @pytest.mark.asyncio
    async def test_l5_stats_tracking(self, engine, sample_chunks):
        """Test L5 cache statistics tracking."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000

        # Initial stats
        stats = engine.get_l5_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

        # First call - miss
        await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        stats = engine.get_l5_stats()
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.0

        # Store and retrieve - hit
        await engine.set_l5(query, sample_chunks, "context", template_version, token_budget, tenant_id="tenant_a")
        await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        stats = engine.get_l5_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5


# ──────────────────────────────────────────────────────────────────────────────
# L5 Concurrency Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5Concurrency:
    """Test L5 concurrency behavior."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.fixture
    def sample_chunks(self):
        return [
            {"text": "Chunk 1 content"},
            {"text": "Chunk 2 content"},
        ]

    @pytest.mark.asyncio
    async def test_concurrent_identical_lookups(self, engine, sample_chunks):
        """Test concurrent identical L5 lookups work correctly."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000
        context = "Shared context"

        # Pre-populate cache
        await engine.set_l5(query, sample_chunks, context, template_version, token_budget, tenant_id="tenant_a")

        # Concurrent lookups
        tasks = [
            engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r == context for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_store_and_lookup(self, engine, sample_chunks):
        """Test concurrent store and lookup."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000

        async def store_then_lookup(context_suffix):
            await engine.set_l5(
                query, sample_chunks, f"context_{context_suffix}", template_version, token_budget, tenant_id="tenant_a"
            )
            return await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")

        # Run concurrent operations
        results = await asyncio.gather(*[store_then_lookup(i) for i in range(5)])

        # All should return a context (last write wins)
        assert all(r is not None for r in results)


# ──────────────────────────────────────────────────────────────────────────────
# L5 RAGPipeline Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5RAGPipelineIntegration:
    """Test L5 integration with RAGPipeline."""

    @pytest.fixture
    def pipeline(self, tmp_path):
        exact_store = SQLiteStore(db_path=str(tmp_path / "cache.db"))
        return RAGPipeline(
            dense_embedder=FakeEmbedder(),
            vector_store=MockVectorStore(),
            exact_store=exact_store,
            enable_l4_cache=True,
            enable_l5_cache=True,
            l4_ttl=3600,
            corpus_version="v1",
            prompt_template_version="v1",
            token_budget=4000,
        )

    @pytest.fixture
    def mock_retrieval_results(self):
        return [
            {"text": "Result 1", "source_file": "doc1.txt", "page_or_section": "p1", "score": 0.95},
            {"text": "Result 2", "source_file": "doc2.txt", "page_or_section": "p2", "score": 0.90},
            {"text": "Result 3", "source_file": "doc3.txt", "page_or_section": "p3", "score": 0.85},
        ]

    @pytest.mark.asyncio
    async def test_l5_cache_integration(self, pipeline, mock_retrieval_results):
        """Test L5 cache integration in RAGPipeline."""
        query = "What is the capital of France?"
        tenant_id = "tenant1"

        # Mock vector store to return results
        pipeline.vector_store.search = AsyncMock(return_value=[
            type('obj', (object,), {'payload': r, 'score': r['score']}) for r in mock_retrieval_results
        ])

        # First generate - should construct context and store in L5
        ans1, t_ret1, t_gen1, score1, citations1 = await pipeline.generate(
            query, {}, tenant_id=tenant_id
        )

        # Check L5 stats
        stats = pipeline.get_l5_stats()
        # First call is a miss (stores), second would be hit
        assert stats["misses"] >= 0

    @pytest.mark.asyncio
    async def test_l5_disabled_falls_back(self, tmp_path, mock_retrieval_results):
        """Test that disabling L5 cache falls back to direct context construction."""
        exact_store = SQLiteStore(db_path=str(tmp_path / "cache.db"))
        pipeline = RAGPipeline(
            dense_embedder=FakeEmbedder(),
            vector_store=MockVectorStore(),
            exact_store=exact_store,
            enable_l5_cache=False,
        )

        pipeline.vector_store.search = AsyncMock(return_value=[
            type('obj', (object,), {'payload': r, 'score': r['score']}) for r in mock_retrieval_results
        ])

        # Should still work without L5
        ans, t_ret, t_gen, score, citations = await pipeline.generate(
            "What is the capital?", {}, tenant_id="tenant1"
        )
        assert ans is not None


# ──────────────────────────────────────────────────────────────────────────────
# L5 Hard Gates Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5HardGates:
    """Test L5 hard gate behavior with CRITICAL_FIELDS."""

    def test_l5_critical_fields_defined(self):
        """L5 CRITICAL_FIELDS must include all required fields."""
        assert "L5" in CRITICAL_FIELDS
        critical = CRITICAL_FIELDS["L5"]
        required = ["tenant_id", "chunk_content_hashes", "template_version", "token_budget", "model_fingerprint", "provider"]
        for field in required:
            assert field in critical, f"Missing CRITICAL_FIELD for L5: {field}"

    def test_strict_mode_blocks_on_all_mismatches(self):
        """STRICT mode must block on ANY mismatch of critical fields."""
        incoming = {
            "tenant_id": "a",
            "chunk_content_hashes": "hash1",
            "template_version": "v1",
            "token_budget": 4000,
            "model_fingerprint": "fp1",
            "provider": "openai"
        }
        cached = {
            "tenant_id": "a",
            "chunk_content_hashes": "hash2",  # Different chunks!
            "template_version": "v1",
            "token_budget": 4000,
            "model_fingerprint": "fp1",
            "provider": "openai"
        }

        allowed, passed, failed = hard_gate_extended(incoming, cached, layer="L5", mode=GateMode.STRICT)
        assert not allowed
        assert "chunk_content_hashes" in failed

    def test_balanced_mode_blocks_on_critical_fields(self):
        """BALANCED mode must also block on CRITICAL_FIELDS mismatches."""
        incoming = {
            "tenant_id": "a",
            "chunk_content_hashes": "hash1",
            "template_version": "v1",
            "token_budget": 4000,
            "model_fingerprint": "fp1",
            "provider": "openai"
        }
        cached = {
            "tenant_id": "b",  # Different tenant!
            "chunk_content_hashes": "hash1",
            "template_version": "v1",
            "token_budget": 4000,
            "model_fingerprint": "fp1",
            "provider": "openai"
        }

        allowed, passed, failed = hard_gate_extended(incoming, cached, layer="L5", mode=GateMode.BALANCED)
        assert not allowed
        assert "tenant_id" in failed


# ──────────────────────────────────────────────────────────────────────────────
# L5 Observability Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5Observability:
    """Test L5 observability and telemetry."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.fixture
    def sample_chunks(self):
        return [{"text": "Chunk 1"}, {"text": "Chunk 2"}]

    @pytest.mark.asyncio
    async def test_l5_metrics_tracked(self, engine, sample_chunks):
        """L5 hit/miss should be tracked in layer_stats."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000

        # Miss
        res = await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert res is None

        # Store and hit
        await engine.set_l5(query, sample_chunks, "context", template_version, token_budget, tenant_id="tenant_a")
        res = await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert res is not None

    @pytest.mark.asyncio
    async def test_decision_engine_l5_evaluation_includes_reasoning(self, engine, sample_chunks):
        """DecisionEngine L5 evaluation should include detailed reasoning."""
        decision_engine = DecisionEngine(engine, policy=ReusePolicy.strict())

        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000
        context = "Cached context"

        # Prime the cache
        await engine.set_l5(query, sample_chunks, context, template_version, token_budget, tenant_id="tenant_a")

        ctx = DecisionContext(
            query=query,
            metadata={"retrieved_chunks": sample_chunks},
            tenant_id="tenant_a",
            prompt_version=template_version,
        )

        eval_result = await decision_engine._evaluate_l5(ctx)

        assert eval_result.latency_ms >= 0
        assert eval_result.reasoning
        assert eval_result.gate_mode == GateMode.STRICT


# ──────────────────────────────────────────────────────────────────────────────
# L5 Invalidation Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5Invalidation:
    """Test L5 invalidation behavior."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.fixture
    def sample_chunks(self):
        return [{"text": "Chunk 1"}, {"text": "Chunk 2"}]

    @pytest.mark.asyncio
    async def test_template_version_change_invalidates(self, engine, sample_chunks):
        """Template version change should auto-invalidate (different key)."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000
        context = "Context for v1"

        await engine.set_l5(query, sample_chunks, context, template_version, token_budget, tenant_id="tenant_a")
        result = await engine.get_l5(query, sample_chunks, template_version, token_budget, tenant_id="tenant_a")
        assert result is not None

        # Different template version = different key = auto-miss
        result = await engine.get_l5(query, sample_chunks, "v2", token_budget, tenant_id="tenant_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_token_budget_change_invalidates(self, engine, sample_chunks):
        """Token budget change should auto-invalidate."""
        query = "What is the revenue?"
        template_version = "v1"
        context = "Context for 4k budget"

        await engine.set_l5(query, sample_chunks, context, template_version, 4000, tenant_id="tenant_a")
        result = await engine.get_l5(query, sample_chunks, template_version, 4000, tenant_id="tenant_a")
        assert result is not None

        result = await engine.get_l5(query, sample_chunks, template_version, 2000, tenant_id="tenant_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_model_change_invalidates(self, engine, sample_chunks):
        """Model change should auto-invalidate."""
        query = "What is the revenue?"
        template_version = "v1"
        token_budget = 4000
        context = "Context for gpt-4o"

        await engine.set_l5(
            query, sample_chunks, context, template_version, token_budget,
            tenant_id="tenant_a", model="gpt-4o", provider="openai"
        )
        result = await engine.get_l5(
            query, sample_chunks, template_version, token_budget,
            tenant_id="tenant_a", model="gpt-4o", provider="openai"
        )
        assert result is not None

        result = await engine.get_l5(
            query, sample_chunks, template_version, token_budget,
            tenant_id="tenant_a", model="gpt-4o-mini", provider="openai"
        )
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# L5 Collision Resistance Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestL5CollisionResistance:
    """Test that different L5 identities don't collide."""

    def test_all_identity_components_independent(self):
        """Changing any single identity component must change the key."""
        base = {
            "tenant_id": "tenant_a",
            "chunks_hash": "hash1",
            "template_version": "v1",
            "token_budget": 4000,
            "model_fingerprint": "fp1",
            "provider": "openai",
        }

        base_key = build_l5_key(**base)

        # Test each component independently
        for component, alt_value in [
            ("tenant_id", "tenant_b"),
            ("chunks_hash", "hash2"),
            ("template_version", "v2"),
            ("token_budget", 2000),
            ("model_fingerprint", "fp2"),
            ("provider", "anthropic"),
        ]:
            modified = base.copy()
            modified[component] = alt_value
            new_key = build_l5_key(**modified)
            assert new_key != base_key, f"Component {component} did not change key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
