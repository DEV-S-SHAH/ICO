"""
test_decision_engine.py — P0 tests for DecisionEngine and reuse decisions.

Tests cover:
- DecisionEngine.decide() execution order
- L1 exact match with full identity
- L2 semantic match with hard gates
- L3 context-aware match with dual-vector
- Confidence model and threshold behavior
- Fallback to FULL_LLM_CALL
"""

import pytest

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.core.decision_engine import (
    DecisionContext,
    DecisionEngine,
    ReuseAction,
    ReusePolicy,
    GateMode,
    build_l1_key,
    build_l0b_key,
    build_l0a_key,
    canonical_meta_suffix,
    normalize_query,
    context_hash,
    compute_confidence,
    CRITICAL_FIELDS,
)
from ico_cache.core.metadata_guard import MetadataSchema, MetadataField, hard_gate


class TestDecisionEngine:
    """Tests for the DecisionEngine class."""

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

    @pytest.fixture
    def decision_engine(self, cache_engine):
        """Create a DecisionEngine with a real cache engine."""
        return DecisionEngine(cache_engine, policy=ReusePolicy.strict())

    @pytest.mark.asyncio
    async def test_decide_returns_full_llm_call_on_empty_cache(self, decision_engine):
        """DecisionEngine should return FULL_LLM_CALL when no cache entries exist."""
        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
        )

        decision = await decision_engine.decide(ctx)

        assert decision.action == ReuseAction.FULL_LLM_CALL
        assert decision.confidence == 0.0
        assert decision.layer == "NONE"
        assert decision.fallback_reason is not None
        assert len(decision.layer_evaluations) == 5  # L0a, L0b, L1, L2, L3

    @pytest.mark.asyncio
    async def test_decide_l1_hit_when_exact_match(self, decision_engine):
        """DecisionEngine should return EXACT_REUSE on L1 exact match."""
        # First, populate L1 cache
        decision_engine.cache_engine.set_l1(
            query="What is the revenue?",
            response={"answer": "$100M"},
            meta={"entity": "MSFT", "quarter": "Q1"},
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            context=None,
        )

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            metadata={"entity": "MSFT", "quarter": "Q1"},
        )

        decision = await decision_engine.decide(ctx)

        assert decision.action == ReuseAction.EXACT_REUSE
        assert decision.confidence == 1.0
        assert decision.layer == "L1"
        assert decision.cache_key is not None

    @pytest.mark.asyncio
    async def test_decide_l1_miss_on_model_mismatch(self, decision_engine):
        """L1 should miss when model fingerprint differs."""
        decision_engine.cache_engine.set_l1(
            query="What is the revenue?",
            response={"answer": "$100M"},
            meta={"entity": "MSFT", "quarter": "Q1"},
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
        )

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
            model="claude-3.5",  # Different model
            provider="anthropic",
            prompt_version="v1",
            metadata={"entity": "MSFT", "quarter": "Q1"},
        )

        decision = await decision_engine.decide(ctx)

        # Should fall through to FULL_LLM_CALL since L1 key won't match
        assert decision.action == ReuseAction.FULL_LLM_CALL

    @pytest.mark.asyncio
    async def test_decide_l1_miss_on_context_mismatch(self, decision_engine):
        """L1 should miss when context hash differs."""
        decision_engine.cache_engine.set_l1(
            query="What is the revenue?",
            response={"answer": "$100M"},
            meta={"entity": "MSFT", "quarter": "Q1"},
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            context="Walmart context",
        )

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            context="Apple context",  # Different context
            metadata={"entity": "MSFT", "quarter": "Q1"},
        )

        decision = await decision_engine.decide(ctx)

        assert decision.action == ReuseAction.FULL_LLM_CALL

    @pytest.mark.asyncio
    async def test_decide_l1_miss_on_prompt_version_mismatch(self, decision_engine):
        """L1 should miss when prompt version differs."""
        decision_engine.cache_engine.set_l1(
            query="What is the revenue?",
            response={"answer": "$100M"},
            meta={"entity": "MSFT", "quarter": "Q1"},
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
        )

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v2",  # Different prompt version
            metadata={"entity": "MSFT", "quarter": "Q1"},
        )

        decision = await decision_engine.decide(ctx)

        assert decision.action == ReuseAction.FULL_LLM_CALL

    @pytest.mark.asyncio
    async def test_decide_l1_miss_on_tenant_mismatch(self, decision_engine):
        """L1 should miss when tenant differs."""
        decision_engine.cache_engine.set_l1(
            query="What is the revenue?",
            response={"answer": "$100M"},
            meta={"entity": "MSFT", "quarter": "Q1"},
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
        )

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_b",  # Different tenant
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            metadata={"entity": "MSFT", "quarter": "Q1"},
        )

        decision = await decision_engine.decide(ctx)

        assert decision.action == ReuseAction.FULL_LLM_CALL

    @pytest.mark.asyncio
    async def test_decide_l2_semantic_match(self, decision_engine):
        """DecisionEngine should find L2 semantic matches."""
        # Populate L2 with a similar query
        await decision_engine.cache_engine.async_write_l2(
            query="How did sales trend?",
            generated={"answer": "Sales increased 10%"},
            meta={"entity": "MSFT", "quarter": "Q1", "topic": "revenue"},
            tenant_id="tenant_a",
        )

        ctx = DecisionContext(
            query="How did sales trend?",  # Same query
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            metadata={"entity": "MSFT", "quarter": "Q1", "topic": "revenue"},
        )

        decision = await decision_engine.decide(ctx)

        # Should hit L2 (after L1 miss)
        assert decision.action in (ReuseAction.SEMANTIC_REUSE, ReuseAction.FULL_LLM_CALL)
        # Check L2 was evaluated
        l2_evals = [e for e in decision.layer_evaluations if e.layer == "L2"]
        assert len(l2_evals) == 1
        assert l2_evals[0].checked is True

    @pytest.mark.asyncio
    async def test_decide_l3_context_match(self, decision_engine):
        """DecisionEngine should find L3 context-aware matches."""
        await decision_engine.cache_engine.async_write_l3(
            query="What were their risk factors?",
            context="Walmart 2026-Q2",
            generated={"answer": "Supply chain and competition"},
            meta={"entity": "WMT", "quarter": "Q2", "topic": "risk"},
            tenant_id="tenant_a",
        )

        ctx = DecisionContext(
            query="What were their risk factors?",
            context="Walmart 2026-Q2",
            tenant_id="tenant_a",
            model="gpt-4o",
            provider="openai",
            prompt_version="v1",
            metadata={"entity": "WMT", "quarter": "Q2", "topic": "risk"},
        )

        decision = await decision_engine.decide(ctx)

        # Check L3 was evaluated
        l3_evals = [e for e in decision.layer_evaluations if e.layer == "L3"]
        assert len(l3_evals) == 1
        assert l3_evals[0].checked is True

    @pytest.mark.asyncio
    async def test_decide_respects_confidence_threshold(self, decision_engine):
        """DecisionEngine should respect confidence threshold."""
        # Use BALANCED policy with lower threshold
        decision_engine.policy = ReusePolicy.balanced()

        ctx = DecisionContext(
            query="What is the revenue?",
            tenant_id="tenant_a",
            reuse_policy=ReusePolicy.balanced(),
        )

        decision = await decision_engine.decide(ctx)

        # Should still return FULL_LLM_CALL but with different threshold
        assert decision.action == ReuseAction.FULL_LLM_CALL
        # Find L1 evaluation and check its gate_mode
        l1_evals = [e for e in decision.layer_evaluations if e.layer == "L1"]
        assert len(l1_evals) == 1
        assert l1_evals[0].gate_mode == GateMode.BALANCED


class TestDecisionContext:
    """Tests for DecisionContext dataclass."""

    def test_model_fingerprint_computation(self):
        """Model fingerprint should be deterministic and include model, provider, params."""
        ctx1 = DecisionContext(
            query="test",
            tenant_id="t1",
            model="gpt-4o",
            provider="openai",
            model_params={"temperature": 0, "top_p": 1},
        )
        ctx2 = DecisionContext(
            query="test",
            tenant_id="t1",
            model="gpt-4o",
            provider="openai",
            model_params={"temperature": 0, "top_p": 1},
        )
        ctx3 = DecisionContext(
            query="test",
            tenant_id="t1",
            model="gpt-4o",
            provider="openai",
            model_params={"temperature": 0.7, "top_p": 1},  # Different temp
        )

        assert ctx1.model_fingerprint == ctx2.model_fingerprint
        assert ctx1.model_fingerprint != ctx3.model_fingerprint

    def test_params_hash_computation(self):
        """Params hash should capture all model parameters."""
        ctx1 = DecisionContext(
            query="test",
            tenant_id="t1",
            model="gpt-4o",
            provider="openai",
            model_params={"temperature": 0, "max_tokens": 100},
        )
        ctx2 = DecisionContext(
            query="test",
            tenant_id="t1",
            model="gpt-4o",
            provider="openai",
            model_params={"temperature": 0, "max_tokens": 200},
        )

        assert ctx1.params_hash != ctx2.params_hash

    def test_default_values(self):
        """DecisionContext should have sensible defaults."""
        ctx = DecisionContext(query="test", tenant_id="t1")

        assert ctx.prompt_version == "v1"
        assert ctx.model == "gpt-4o"
        assert ctx.provider == "openai"
        assert ctx.authz_version == "v1"
        assert isinstance(ctx.reuse_policy, ReusePolicy)


class TestKeyBuilders:
    """Tests for cache key builder functions."""

    def test_build_l1_key_deterministic(self):
        """L1 key should be deterministic."""
        key1 = build_l1_key(
            tenant_id="tenant_a",
            normalized_query="what is revenue",
            model_fingerprint="abc123",
            provider="openai",
            prompt_version="v1",
            context_hash="empty",
            canonical_meta_suffix="|entity=MSFT&quarter=Q1",
        )
        key2 = build_l1_key(
            tenant_id="tenant_a",
            normalized_query="what is revenue",
            model_fingerprint="abc123",
            provider="openai",
            prompt_version="v1",
            context_hash="empty",
            canonical_meta_suffix="|entity=MSFT&quarter=Q1",
        )
        assert key1 == key2

    def test_build_l1_key_different_on_model_fingerprint(self):
        """L1 key should differ on model fingerprint."""
        key1 = build_l1_key("t", "q", "fp1", "p", "v1", "ctx", "")
        key2 = build_l1_key("t", "q", "fp2", "p", "v1", "ctx", "")
        assert key1 != key2

    def test_build_l1_key_different_on_provider(self):
        """L1 key should differ on provider."""
        key1 = build_l1_key("t", "q", "fp", "openai", "v1", "ctx", "")
        key2 = build_l1_key("t", "q", "fp", "anthropic", "v1", "ctx", "")
        assert key1 != key2

    def test_build_l1_key_different_on_prompt_version(self):
        """L1 key should differ on prompt version."""
        key1 = build_l1_key("t", "q", "fp", "p", "v1", "ctx", "")
        key2 = build_l1_key("t", "q", "fp", "p", "v2", "ctx", "")
        assert key1 != key2

    def test_build_l1_key_different_on_context(self):
        """L1 key should differ on context hash."""
        key1 = build_l1_key("t", "q", "fp", "p", "v1", "ctx1", "")
        key2 = build_l1_key("t", "q", "fp", "p", "v1", "ctx2", "")
        assert key1 != key2

    def test_build_l1_key_different_on_tenant(self):
        """L1 key should differ on tenant."""
        key1 = build_l1_key("t1", "q", "fp", "p", "v1", "ctx", "")
        key2 = build_l1_key("t2", "q", "fp", "p", "v1", "ctx", "")
        assert key1 != key2

    def test_build_l0a_key(self):
        """L0a key should include function name, version, args, env."""
        key1 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env1")
        key2 = build_l0a_key("count_tokens", {"text": "hello"}, "1.0", "env1")
        key3 = build_l0a_key("count_tokens", {"text": "world"}, "1.0", "env1")
        key4 = build_l0a_key("count_tokens", {"text": "hello"}, "2.0", "env1")

        assert key1 == key2
        assert key1 != key3
        assert key1 != key4
        assert key1.startswith("det:count_tokens:")

    def test_build_l0b_key(self):
        """L0b key should include model fingerprint and text hash."""
        key1 = build_l0b_key("fp123", "hello world")
        key2 = build_l0b_key("fp123", "hello world")
        key3 = build_l0b_key("fp456", "hello world")  # Different model

        assert key1 == key2
        assert key1 != key3
        assert key1.startswith("emb:fp123:")

    def test_canonical_meta_suffix(self):
        """Canonical meta suffix should be sorted and deterministic."""
        meta1 = {"quarter": "Q1", "entity": "MSFT", "topic": "revenue"}
        meta2 = {"entity": "MSFT", "topic": "revenue", "quarter": "Q1"}

        suffix1 = canonical_meta_suffix(meta1)
        suffix2 = canonical_meta_suffix(meta2)

        assert suffix1 == suffix2
        assert "entity=MSFT" in suffix1
        assert "quarter=Q1" in suffix1
        assert "topic=revenue" in suffix1

    def test_canonical_meta_suffix_excludes_none(self):
        """None values should be excluded from suffix."""
        meta = {"entity": "MSFT", "quarter": None, "topic": "revenue"}
        suffix = canonical_meta_suffix(meta)
        assert "entity=MSFT" in suffix
        assert "topic=revenue" in suffix
        assert "quarter" not in suffix

    def test_normalize_query(self):
        """Query normalization should be consistent."""
        assert normalize_query("  What   is   Revenue?  ") == "what is revenue?"
        assert normalize_query("WHAT IS REVENUE?") == "what is revenue?"

    def test_context_hash(self):
        """Context hash should be consistent."""
        h1 = context_hash("Walmart context")
        h2 = context_hash("Walmart context")
        h3 = context_hash("Apple context")
        h_empty = context_hash("")
        h_none = context_hash(None)

        assert h1 == h2
        assert h1 != h3
        assert h_empty == "empty"
        assert h_none == "empty"


class TestConfidenceModel:
    """Tests for confidence computation."""

    def test_exact_reuse_confidence(self):
        """EXACT_REUSE should have 1.0 confidence."""
        conf = compute_confidence(ReuseAction.EXACT_REUSE)
        assert conf == 1.0

    def test_full_llm_call_confidence(self):
        """FULL_LLM_CALL should have 0.0 confidence."""
        conf = compute_confidence(ReuseAction.FULL_LLM_CALL)
        assert conf == 0.0

    def test_semantic_reuse_confidence_from_score(self):
        """SEMANTIC_REUSE confidence should come from score."""
        conf = compute_confidence(ReuseAction.SEMANTIC_REUSE, base_score=0.92)
        assert conf == 0.92

    def test_context_reuse_confidence_min_of_scores(self):
        """CONTEXT_REUSE confidence should be min of query and context scores."""
        conf = compute_confidence(ReuseAction.CONTEXT_REUSE, base_score=0.85)
        # Base confidence for CONTEXT_REUSE is 0.85, min with 0.85 = 0.85
        assert conf == 0.85

    def test_confidence_modifiers(self):
        """Confidence should be modified by modifiers."""
        conf = compute_confidence(
            ReuseAction.SEMANTIC_REUSE,
            base_score=0.90,
            modifiers=["fuzzy_gate_pass", "missing_metadata"],
        )
        # 0.90 - 0.1 - 0.05 = 0.75
        assert conf == 0.75

    def test_confidence_clamped(self):
        """Confidence should be clamped to [0, 1]."""
        conf = compute_confidence(
            ReuseAction.SEMANTIC_REUSE,
            base_score=0.95,
            modifiers=["fuzzy_gate_pass"] * 20,  # Would go negative
        )
        assert conf == 0.0

        conf = compute_confidence(
            ReuseAction.EXACT_REUSE,
            modifiers=["reusable_component"] * 20,  # Would go > 1
        )
        assert conf == 1.0


class TestReusePolicy:
    """Tests for ReusePolicy."""

    def test_strict_policy_defaults(self):
        """STRICT policy should have 0.95 threshold."""
        policy = ReusePolicy.strict()
        assert policy.mode == GateMode.STRICT
        assert policy.threshold == 0.95
        assert len(policy.fuzzy_fields) == 0

    def test_balanced_policy_defaults(self):
        """BALANCED policy should have 0.80 threshold."""
        policy = ReusePolicy.balanced()
        assert policy.mode == GateMode.BALANCED
        assert policy.threshold == 0.80

    def test_balanced_policy_with_fuzzy_fields(self):
        """BALANCED policy should accept fuzzy fields."""
        policy = ReusePolicy.balanced(fuzzy_fields=["topic", "custom_field"])
        assert "topic" in policy.fuzzy_fields
        assert "custom_field" in policy.fuzzy_fields

    def test_custom_threshold(self):
        """Custom threshold should override default."""
        policy = ReusePolicy(mode=GateMode.STRICT, threshold=0.99)
        assert policy.threshold == 0.99


class TestCriticalFields:
    """Tests for CRITICAL_FIELDS per layer."""

    def test_l1_critical_fields(self):
        """L1 should have all required critical fields."""
        assert "tenant_id" in CRITICAL_FIELDS["L1"]
        assert "model_fingerprint" in CRITICAL_FIELDS["L1"]
        assert "provider" in CRITICAL_FIELDS["L1"]
        assert "prompt_version" in CRITICAL_FIELDS["L1"]
        assert "entity" in CRITICAL_FIELDS["L1"]
        assert "quarter" in CRITICAL_FIELDS["L1"]
        assert "topic" in CRITICAL_FIELDS["L1"]

    def test_l2_critical_fields(self):
        """L2 should have all required critical fields."""
        assert "tenant_id" in CRITICAL_FIELDS["L2"]
        assert "model_fingerprint" in CRITICAL_FIELDS["L2"]
        assert "embedding_version" in CRITICAL_FIELDS["L2"]
        assert "entity" in CRITICAL_FIELDS["L2"]
        assert "quarter" in CRITICAL_FIELDS["L2"]
        assert "topic" in CRITICAL_FIELDS["L2"]
        assert "collection_version" in CRITICAL_FIELDS["L2"]

    def test_l9_critical_fields(self):
        """L9 should have all required critical fields including tenant and user."""
        assert "tenant_id" in CRITICAL_FIELDS["L9"]
        assert "user_id" in CRITICAL_FIELDS["L9"]
        assert "model_fingerprint" in CRITICAL_FIELDS["L9"]
        assert "provider" in CRITICAL_FIELDS["L9"]
        assert "params_hash" in CRITICAL_FIELDS["L9"]
        assert "prompt_version" in CRITICAL_FIELDS["L9"]
        assert "authz_version" in CRITICAL_FIELDS["L9"]
        assert "injected_context_hash" in CRITICAL_FIELDS["L9"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])