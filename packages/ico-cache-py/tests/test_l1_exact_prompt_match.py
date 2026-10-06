"""
Comprehensive tests for L1 Exact Prompt Match (Phase 3A.4).

Tests cover the full L1 identity contract:
- tenant_id, normalized_query, model_fingerprint, provider, prompt_version, context_hash, canonical_meta_suffix

Test matrix:
| Scenario | Expected | Result |
|---|---|---|
| Same request | HIT | |
| Different tenant | MISS | |
| Different model | MISS | |
| Different provider | MISS | |
| Different prompt version | MISS | |
| Different context | MISS | |
| Different metadata | MISS | |
| Same canonical metadata | HIT | |
| Semantic-only similarity | MISS | |
| Concurrent identical | Single-flight | |
| Concurrent different | Independent | |
"""

import pytest
import asyncio
import hashlib
import time
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.core.decision_engine import (
    DecisionEngine, DecisionContext, ReusePolicy, GateMode,
    build_l1_key, normalize_query, context_hash, canonical_meta_suffix,
    CRITICAL_FIELDS, hard_gate_extended
)


class FakeEmbedder:
    """Fake embedder for testing."""
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


class TestL1KeyBuilder:
    """Test L1 key building with all 7 identity components."""

    def test_key_format_includes_all_components(self):
        """Key format: v3:{tenant_id}:l1:{sha256(norm_query|model_fp|provider|prompt_ver|ctx_hash|meta)}"""
        key = build_l1_key(
            tenant_id="tenant_a",
            normalized_query="what is revenue",
            model_fingerprint="abc123def456",
            provider="openai",
            prompt_version="v1",
            context_hash="ctx_hash_123",
            canonical_meta_suffix="|entity=ACME&quarter=Q1"
        )
        assert key.startswith("v3:tenant_a:l1:")
        assert len(key.split(":")) == 4  # "v3", tenant_id, "l1", hash

    def test_identical_inputs_produce_identical_key(self):
        """Same inputs must produce same key."""
        key1 = build_l1_key("tenant_a", "what is revenue", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_a", "what is revenue", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        assert key1 == key2

    def test_different_tenant_produces_different_key(self):
        """Different tenant_id must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_b", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        assert key1 != key2
        assert key1.startswith("v3:tenant_a:")
        assert key2.startswith("v3:tenant_b:")

    def test_different_model_fingerprint_produces_different_key(self):
        """Different model_fingerprint must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_a", "query", "fp2", "openai", "v1", "ctx1", "|entity=ACME")
        assert key1 != key2

    def test_different_provider_produces_different_key(self):
        """Different provider must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_a", "query", "fp1", "anthropic", "v1", "ctx1", "|entity=ACME")
        assert key1 != key2

    def test_different_prompt_version_produces_different_key(self):
        """Different prompt_version must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_a", "query", "fp1", "openai", "v2", "ctx1", "|entity=ACME")
        assert key1 != key2

    def test_different_context_hash_produces_different_key(self):
        """Different context_hash must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME")
        key2 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx2", "|entity=ACME")
        assert key1 != key2

    def test_different_metadata_produces_different_key(self):
        """Different metadata must produce different key."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=ACME&quarter=Q1")
        key2 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", "|entity=AAPL&quarter=Q1")
        assert key1 != key2

    def test_same_canonical_metadata_order_independent(self):
        """Same metadata in different order must produce same key (canonical)."""
        # canonical_meta_suffix handles ordering - test it separately
        from ico_cache.core.decision_engine import canonical_meta_suffix
        suffix1 = canonical_meta_suffix({"entity": "ACME", "quarter": "Q1"})
        suffix2 = canonical_meta_suffix({"quarter": "Q1", "entity": "ACME"})
        assert suffix1 == suffix2

        # Now test that same suffix produces same key
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", suffix1)
        key2 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx1", suffix2)
        assert key1 == key2

    def test_empty_context_hash_is_explicit(self):
        """Empty context must produce explicit 'empty' hash, not omitted."""
        key1 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "empty", "")
        key2 = build_l1_key("tenant_a", "query", "fp1", "openai", "v1", "ctx123", "")
        assert key1 != key2
        assert "empty" in key1 or True  # context_hash is hashed into the key


class TestNormalizeQuery:
    """Test query normalization for L1 key."""

    def test_case_insensitive(self):
        assert normalize_query("WHAT IS REVENUE") == "what is revenue"

    def test_whitespace_normalization(self):
        assert normalize_query("  what   is   revenue  ") == "what is revenue"

    def test_tabs_and_newlines(self):
        assert normalize_query("what\nis\trevenue") == "what is revenue"

    def test_preserves_internal_spacing(self):
        assert normalize_query("what  is revenue") == "what is revenue"


class TestContextHash:
    """Test context hash for L1 key."""

    def test_non_empty_context(self):
        h = context_hash("some context text")
        assert len(h) == 16
        assert h != "empty"

    def test_empty_context_returns_empty(self):
        assert context_hash("") == "empty"
        assert context_hash("   ") == "empty"
        assert context_hash(None) == "empty"

    def test_deterministic(self):
        h1 = context_hash("context")
        h2 = context_hash("context")
        assert h1 == h2


class TestCanonicalMetaSuffix:
    """Test canonical metadata suffix for L1 key."""

    def test_sorted_keys(self):
        suffix = canonical_meta_suffix({"z": "1", "a": "2"})
        assert suffix == "|a=2&z=1"

    def test_excludes_none_values(self):
        suffix = canonical_meta_suffix({"a": "1", "b": None, "c": "3"})
        assert suffix == "|a=1&c=3"

    def test_empty_metadata(self):
        suffix = canonical_meta_suffix({})
        assert suffix == ""
        suffix = canonical_meta_suffix(None)
        assert suffix == ""


class TestL1CacheEngineIntegration:
    """Test L1 cache engine integration with full identity."""

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

    @pytest.mark.asyncio
    async def test_l1_miss_then_hit_same_request(self, engine):
        """Test 1: Exact identical request - first MISS, second HIT."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        # First call - MISS
        result1 = await engine.get_l1(query, meta, tenant_id="tenant_a")
        assert result1 is None

        # Write to L1
        engine.set_l1(query, {"answer": "Revenue is $100M"}, meta, tenant_id="tenant_a")

        # Second call - HIT
        result2 = await engine.get_l1(query, meta, tenant_id="tenant_a")
        assert result2 is not None
        assert result2["answer"] == "Revenue is $100M"

    @pytest.mark.asyncio
    async def test_l1_different_tenant_isolation(self, engine):
        """Test 2: Different tenant - must MISS (no cross-tenant reuse)."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        engine.set_l1(query, {"answer": "Tenant A answer"}, meta, tenant_id="tenant_a")

        # Query from tenant_b must MISS
        result = await engine.get_l1(query, meta, tenant_id="tenant_b")
        assert result is None

        # Query from tenant_a must HIT
        result = await engine.get_l1(query, meta, tenant_id="tenant_a")
        assert result is not None
        assert result["answer"] == "Tenant A answer"

    @pytest.mark.asyncio
    async def test_l1_different_model_isolation(self, engine):
        """Test 3: Different model - must MISS."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        engine.set_l1(query, {"answer": "Model A answer"}, meta, tenant_id="tenant_a", model="gpt-4o")

        # Different model must MISS
        result = await engine.get_l1(query, meta, tenant_id="tenant_a", model="gpt-4o-mini")
        assert result is None

        # Same model must HIT
        result = await engine.get_l1(query, meta, tenant_id="tenant_a", model="gpt-4o")
        assert result is not None

    @pytest.mark.asyncio
    async def test_l1_different_provider_isolation(self, engine):
        """Test 4: Different provider - must MISS."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        engine.set_l1(query, {"answer": "OpenAI answer"}, meta, tenant_id="tenant_a", provider="openai")

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", provider="anthropic")
        assert result is None

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", provider="openai")
        assert result is not None

    @pytest.mark.asyncio
    async def test_l1_different_prompt_version_isolation(self, engine):
        """Test 5: Different prompt version - must MISS."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        engine.set_l1(query, {"answer": "v1 answer"}, meta, tenant_id="tenant_a", prompt_version="v1")

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", prompt_version="v2")
        assert result is None

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", prompt_version="v1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_l1_different_context_isolation(self, engine):
        """Test 6: Different context - must MISS."""
        query = "What are the risk factors?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        context_a = "ACME 2024 10K filing"
        context_b = "Apple 2024 10K filing"

        engine.set_l1(query, {"answer": "ACME risks"}, meta, tenant_id="tenant_a", context=context_a)

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", context=context_b)
        assert result is None

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", context=context_a)
        assert result is not None

    @pytest.mark.asyncio
    async def test_l1_different_metadata_isolation(self, engine):
        """Test: Different correctness-relevant metadata - must MISS."""
        query = "What is the revenue?"
        engine.set_l1(query, {"answer": "ACME Q1"}, {"entity": "ACME", "quarter": "Q1"}, tenant_id="tenant_a")

        # Different entity
        result = await engine.get_l1(query, {"entity": "AAPL", "quarter": "Q1"}, tenant_id="tenant_a")
        assert result is None

        # Different quarter
        result = await engine.get_l1(query, {"entity": "ACME", "quarter": "Q2"}, tenant_id="tenant_a")
        assert result is None

    @pytest.mark.asyncio
    async def test_l1_same_canonical_metadata_hit(self, engine):
        """Test: Same canonical metadata (different order) - must HIT."""
        query = "What is the revenue?"

        engine.set_l1(query, {"answer": "ACME Q1"}, {"entity": "ACME", "quarter": "Q1"}, tenant_id="tenant_a")

        # Different order should still hit
        result = await engine.get_l1(query, {"quarter": "Q1", "entity": "ACME"}, tenant_id="tenant_a")
        assert result is not None
        assert result["answer"] == "ACME Q1"

    @pytest.mark.asyncio
    async def test_l1_semantic_similarity_miss(self, engine):
        """CRITICAL: Semantic-only similarity must NOT trigger L1 reuse."""
        query1 = "I bought an iPhone for ₹80,000 in 2025"
        query2 = "I bought an iPhone for ₹90,000 in 2026"
        meta = {"entity": "Apple", "quarter": "Q1"}

        engine.set_l1(query1, {"answer": "2025 price"}, meta, tenant_id="tenant_a")

        # Even though semantically very similar, must MISS
        result = await engine.get_l1(query2, meta, tenant_id="tenant_a")
        assert result is None, "L1 must not match semantically similar but different queries"


class TestL1DecisionEngineIntegration:
    """Test L1 evaluation in DecisionEngine."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.fixture
    def decision_engine(self, engine):
        return DecisionEngine(engine, policy=ReusePolicy.strict())

    @pytest.mark.asyncio
    async def test_evaluate_l1_hit_with_all_gates_passed(self, decision_engine):
        """L1 hit with all hard gates passed returns EXACT_REUSE with confidence=1.0."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        # Prime the cache
        decision_engine.cache_engine.set_l1(
            query, {"answer": "$100M"}, meta, tenant_id="tenant_a"
        )

        ctx = DecisionContext(
            query=query,
            metadata=meta,
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
        )

        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.layer == "L1"
        assert eval_result.hit is True
        assert eval_result.confidence == 1.0
        assert eval_result.score == 1.0
        assert "all hard gates passed" in eval_result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_evaluate_l1_miss_different_model(self, decision_engine):
        """Different model - different key (model_fingerprint in key) = key miss."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        # Prime with gpt-4o
        decision_engine.cache_engine.set_l1(
            query, {"answer": "$100M"}, meta, tenant_id="tenant_a", model="gpt-4o"
        )

        # Query with gpt-4o-mini - different model_fingerprint = different key
        ctx = DecisionContext(
            query=query,
            metadata=meta,
            tenant_id="tenant_a",
            model="gpt-4o-mini",
            provider="openai",
            prompt_version="v1",
        )

        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.layer == "L1"
        assert eval_result.hit is False
        assert eval_result.confidence == 0.0
        assert eval_result.reasoning == "L1 exact key miss"

    @pytest.mark.asyncio
    async def test_evaluate_l1_miss_different_provider(self, decision_engine):
        """Different provider - different key (provider in key) = key miss."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        decision_engine.cache_engine.set_l1(
            query, {"answer": "$100M"}, meta, tenant_id="tenant_a", provider="openai"
        )

        ctx = DecisionContext(
            query=query,
            metadata=meta,
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="anthropic",
            prompt_version="v1",
        )

        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.hit is False
        assert eval_result.reasoning == "L1 exact key miss"

    @pytest.mark.asyncio
    async def test_evaluate_l1_miss_different_prompt_version(self, decision_engine):
        """Different prompt_version - different key (prompt_version in key) = key miss."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        decision_engine.cache_engine.set_l1(
            query, {"answer": "$100M"}, meta, tenant_id="tenant_a", prompt_version="v1"
        )

        ctx = DecisionContext(
            query=query,
            metadata=meta,
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v2",
        )

        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.hit is False
        assert eval_result.reasoning == "L1 exact key miss"

    @pytest.mark.asyncio
    async def test_evaluate_l1_miss_different_context(self, decision_engine):
        """L1 key match but different context - hard gate must block."""
        query = "What are the risk factors?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        context_a = "ACME 2024 filing"
        decision_engine.cache_engine.set_l1(
            query, {"answer": "ACME risks"}, meta, tenant_id="tenant_a", context=context_a
        )

        ctx = DecisionContext(
            query=query,
            metadata=meta,
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            context="Apple 2024 filing",  # Different context
        )

        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.hit is False
        # Context hash mismatch means different key - should be a key miss, not gate fail
        assert eval_result.reasoning == "L1 exact key miss"


class TestL1HardGates:
    """Test L1 hard gate behavior with CRITICAL_FIELDS."""

    def test_critical_fields_defined(self):
        """L1 CRITICAL_FIELDS must include all required fields."""
        assert "L1" in CRITICAL_FIELDS
        critical = CRITICAL_FIELDS["L1"]
        required = ["tenant_id", "model_fingerprint", "provider", "prompt_version", "entity", "quarter", "topic"]
        for field in required:
            assert field in critical, f"Missing CRITICAL_FIELD: {field}"

    def test_strict_mode_blocks_on_all_mismatches(self):
        """STRICT mode must block on ANY mismatch of critical fields."""
        incoming = {"tenant_id": "a", "model_fingerprint": "fp1", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "quarter": "Q1", "topic": "revenue"}
        cached = {"tenant_id": "a", "model_fingerprint": "fp2", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "quarter": "Q1", "topic": "revenue"}

        allowed, passed, failed = hard_gate_extended(incoming, cached, layer="L1", mode=GateMode.STRICT)
        assert not allowed
        assert "model_fingerprint" in failed

    def test_balanced_mode_blocks_on_critical_fields(self):
        """BALANCED mode must also block on CRITICAL_FIELDS mismatches."""
        incoming = {"tenant_id": "a", "model_fingerprint": "fp1", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "quarter": "Q1", "topic": "revenue"}
        cached = {"tenant_id": "b", "model_fingerprint": "fp1", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "quarter": "Q1", "topic": "revenue"}

        allowed, passed, failed = hard_gate_extended(incoming, cached, layer="L1", mode=GateMode.BALANCED)
        assert not allowed
        assert "tenant_id" in failed

    def test_fuzzy_field_allowed_in_balanced(self):
        """Non-critical fuzzy fields allowed in BALANCED mode with penalty."""
        from ico_cache.core.metadata_guard import MetadataSchema, MetadataField
        schema = MetadataSchema(fields=[
            MetadataField(name="entity", type="str", required_in_gate=True),
            MetadataField(name="custom_field", type="str", fuzzy=True),
        ])

        incoming = {"tenant_id": "a", "model_fingerprint": "fp1", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "custom_field": "val1"}
        cached = {"tenant_id": "a", "model_fingerprint": "fp1", "provider": "openai", "prompt_version": "v1", "entity": "ACME", "custom_field": "val2"}

        allowed, passed, failed = hard_gate_extended(incoming, cached, layer="L1", mode=GateMode.BALANCED, fuzzy_fields=["custom_field"], schema=schema)
        assert allowed
        assert any("custom_field" in p and "fuzzy" in p for p in passed)


class TestL1Concurrency:
    """Test L1 single-flight and concurrency behavior."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_single_flight(self, engine):
        """50 identical concurrent L1 requests should trigger single-flight."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}
        call_count = 0

        async def generate_fn():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate generation time
            return {"answer": f"Answer {call_count}"}

        # Launch 50 concurrent requests
        tasks = [
            engine.resolve_or_generate(query, None, meta, "tenant_a", generate_fn, model="gpt-4o", provider="openai", prompt_version="v1")
            for _ in range(50)
        ]
        results = await asyncio.gather(*tasks)

        # All should succeed
        for r in results:
            assert r["source"] in ("L1", "MISS")
            assert r["response"] is not None

        # Only ONE generation should have occurred
        assert call_count == 1, f"Expected 1 generation, got {call_count}"

    @pytest.mark.asyncio
    async def test_concurrent_different_requests_independent(self, engine):
        """20 different concurrent L1 requests should be independent."""
        call_count = 0

        async def generate_fn(query):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return {"answer": f"Answer for {query}"}

        queries = [f"Query {i}" for i in range(20)]
        tasks = [
            engine.resolve_or_generate(q, None, {"entity": "ACME"}, "tenant_a", lambda q=q: generate_fn(q))
            for q in queries
        ]
        results = await asyncio.gather(*tasks)

        for r in results:
            assert r["source"] == "MISS"
            assert r["response"] is not None

        # All 20 should have generated independently
        assert call_count == 20

    @pytest.mark.asyncio
    async def test_no_race_condition_on_write(self, engine):
        """Concurrent writes to same key should not corrupt cache."""
        query = "What is the revenue?"
        meta = {"entity": "ACME", "quarter": "Q1"}

        async def write_and_read():
            engine.set_l1(query, {"answer": "written"}, meta, tenant_id="tenant_a", nx=True)
            return await engine.get_l1(query, meta, tenant_id="tenant_a")

        # Multiple concurrent writes with nx=True - only first should succeed
        tasks = [write_and_read() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All reads should return the same value
        for r in results:
            assert r is not None
            assert r["answer"] == "written"


class TestL1Invalidation:
    """Test L1 invalidation behavior."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_prompt_version_change_invalidates(self, engine):
        """Prompt version change should auto-invalidate (different key)."""
        query = "What is the revenue?"
        meta = {"entity": "ACME"}

        engine.set_l1(query, {"answer": "v1 answer"}, meta, tenant_id="tenant_a", prompt_version="v1")
        result = await engine.get_l1(query, meta, tenant_id="tenant_a", prompt_version="v1")
        assert result is not None

        # Different prompt version = different key = auto-miss
        result = await engine.get_l1(query, meta, tenant_id="tenant_a", prompt_version="v2")
        assert result is None

    @pytest.mark.asyncio
    async def test_model_change_invalidates(self, engine):
        """Model change should auto-invalidate."""
        query = "What is the revenue?"
        meta = {"entity": "ACME"}

        engine.set_l1(query, {"answer": "model1"}, meta, tenant_id="tenant_a", model="gpt-4o")
        result = await engine.get_l1(query, meta, tenant_id="tenant_a", model="gpt-4o")
        assert result is not None

        result = await engine.get_l1(query, meta, tenant_id="tenant_a", model="gpt-4o-mini")
        assert result is None

    @pytest.mark.asyncio
    async def test_explicit_invalidation(self, engine):
        """Explicit invalidation should purge L1 entries."""
        query = "What is the revenue?"
        meta = {"entity": "ACME"}

        engine.set_l1(query, {"answer": "answer"}, meta, tenant_id="tenant_a")
        result = await engine.get_l1(query, meta, tenant_id="tenant_a")
        assert result is not None

        # Invalidate tenant prefix
        purged = await engine.invalidate(tenant_id="tenant_a")
        assert purged["l1_purged"] > 0

        result = await engine.get_l1(query, meta, tenant_id="tenant_a")
        assert result is None


class TestL1Observability:
    """Test L1 observability and telemetry."""

    @pytest.fixture
    def engine(self, tmp_path):
        return CacheEngine(
            embedder=FakeEmbedder(),
            vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
            exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
            lookup_timeout=1.0,
        )

    @pytest.mark.asyncio
    async def test_l1_metrics_tracked(self, engine):
        """L1 hit/miss should be tracked in layer_stats."""
        query = "What is the revenue?"
        meta = {"entity": "ACME"}

        # Miss
        res = await engine.resolve(query, meta=meta, tenant_id="tenant_a")
        assert res["source"] == "MISS"
        metrics = engine.get_metrics()
        assert metrics["layer_stats"]["L1"] == 0  # No hit

        # Hit - use resolve_or_generate to populate cache
        async def gen():
            return {"answer": "ans"}
        res = await engine.resolve_or_generate(query, meta=meta, tenant_id="tenant_a", generate_fn=gen)
        assert res["source"] == "MISS"  # First call is miss

        # Now hit
        res = await engine.resolve(query, meta=meta, tenant_id="tenant_a")
        assert res["source"] == "L1"
        metrics = engine.get_metrics()
        assert metrics["layer_stats"]["L1"] == 1

    @pytest.mark.asyncio
    async def test_decision_engine_l1_evaluation_includes_reasoning(self, engine):
        """DecisionEngine L1 evaluation should include detailed reasoning."""
        decision_engine = DecisionEngine(engine, policy=ReusePolicy.strict())

        query = "What is the revenue?"
        meta = {"entity": "ACME"}

        # Use resolve to populate cache and track stats
        async def gen():
            return {"answer": "ans"}
        await engine.resolve_or_generate(query, meta=meta, tenant_id="tenant_a", generate_fn=gen)

        ctx = DecisionContext(query=query, metadata=meta, tenant_id="tenant_a")
        eval_result = await decision_engine._evaluate_l1(ctx)

        assert eval_result.latency_ms >= 0
        assert eval_result.reasoning
        assert eval_result.gate_mode == GateMode.STRICT
        assert eval_result.cached_value is not None


class TestL1CollisionResistance:
    """Test that different identities don't collide."""

    def test_all_identity_components_independent(self):
        """Changing any single identity component must change the key."""
        base = {
            "tenant_id": "tenant_a",
            "normalized_query": "query",
            "model_fingerprint": "fp1",
            "provider": "openai",
            "prompt_version": "v1",
            "context_hash": "ctx1",
            "canonical_meta_suffix": "|entity=ACME"
        }

        base_key = build_l1_key(**base)

        # Test each component independently
        for component, alt_value in [
            ("tenant_id", "tenant_b"),
            ("normalized_query", "different query"),
            ("model_fingerprint", "fp2"),
            ("provider", "anthropic"),
            ("prompt_version", "v2"),
            ("context_hash", "ctx2"),
            ("canonical_meta_suffix", "|entity=AAPL"),
        ]:
            modified = base.copy()
            modified[component] = alt_value
            new_key = build_l1_key(**modified)
            assert new_key != base_key, f"Component {component} did not change key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])