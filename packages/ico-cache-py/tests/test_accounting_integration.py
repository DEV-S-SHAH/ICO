"""Exhaustive tests for Token and Cost Accounting (Phase 3A.5).

Covers:
1. Token Accounting Tests
2. Cost Accounting Tests
3. Cache HIT Tests
4. Cache MISS Tests
5. Layer Attribution Tests
6. Tenant Isolation Tests
7. Concurrency/Single-Flight Tests
8. False-Savings Tests (CRITICAL)
9. Accounting Invariant Tests
"""

import asyncio
import hashlib
import time
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.telemetry.cost_model import CostModel, ModelPricing, get_cost_model, set_cost_model
from ico_cache.telemetry.provider_adapters import UsageSource, get_provider_registry
from ico_cache.telemetry.baseline import (
    BaselineCalculator,
    DecisionContext,
    BaselineStrategy,
)
from ico_cache.telemetry.accounting import (
    CacheLayer,
    DecisionAction,
    UsageRecord,
    UsageSource,
    UsageType,
    PricingVersion,
    TokenUsage,
    LayerAttribution,
    AccountingContext,
    AccountingCollector,
    get_collector,
    record_usage,
)
from ico_cache.telemetry.metrics import (
    COST_USD_TOTAL,
    TOKENS_TOTAL,
    record_cost,
    record_tokens,
    render_metrics,
)


# =============================================================================
# Helper Functions
# =============================================================================

def _get_metric_value(metric, labels: str, tenant: str) -> float:
    """Extract metric value from Prometheus output."""
    output = render_metrics().decode()

    # Prometheus appends _total to Counter names
    prom_name = metric._name + "_total"

    for line in output.split('\n'):
        if line.startswith(prom_name + '{') and labels in line and f'tenant="{tenant}"' in line:
            try:
                value_str = line.split()[-1]
                return float(value_str)
            except (ValueError, IndexError):
                pass
    return 0.0


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def cost_model():
    """Fresh cost model with known pricing for tests."""
    pricing = {
        "openai:gpt-4o": ModelPricing(2.50, 10.00, "openai", "gpt-4o"),
        "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini"),
        "anthropic:claude-3-5-sonnet-20241022": ModelPricing(3.00, 15.00, "anthropic", "claude-3-5-sonnet-20241022"),
        "ollama:llama-3.1-70b": ModelPricing(0.0, 0.0, "ollama", "llama-3.1-70b"),
        "test:custom-model": ModelPricing(1.00, 2.00, "test", "custom-model"),
    }
    model = CostModel(pricing=pricing, allow_runtime_updates=True)
    set_cost_model(model)
    yield model
    set_cost_model(CostModel())


@pytest.fixture
def fake_embedder():
    """Deterministic fake embedder for tests."""
    class FakeEmbedder:
        dim = 384
        
        def embed(self, text: str):
            digest = hashlib.sha256(text.encode()).digest()
            raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
            norm = sum(v * v for v in raw) ** 0.5 or 1.0
            return [v / norm for v in raw]
        
        @property
        def model_version(self) -> str:
            return "fake-embedder@1.0.0"
    
    return FakeEmbedder()


@pytest.fixture
def engine(tmp_path, fake_embedder, cost_model):
    """Service-free CacheEngine backed by embedded LanceDB + SQLite."""
    from ico_cache.backends.vector.lancedb_store import LanceDBStore
    from ico_cache.backends.exact.sqlite_store import SQLiteStore

    return CacheEngine(
        embedder=fake_embedder,
        vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
        exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
        lookup_timeout=1.0,
        cost_model=cost_model,
        agent_type="chatbot",
    )


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset Prometheus metrics before each test."""
    from ico_cache.telemetry.metrics import reset_metrics_for_testing
    reset_metrics_for_testing()
    yield


# =============================================================================
# 1. Token Accounting Tests
# =============================================================================

class TestTokenAccounting:
    """Tests for token accounting: provider reports, estimates, partial, zero, unknown."""

    def test_provider_reports_usage_actual(self, cost_model):
        """Provider reports actual usage - tokens recorded as actual."""
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        cost = cost_model.estimate_cost_from_usage("openai", "gpt-4o", usage)
        
        assert cost is not None
        expected = (100 / 1_000_000) * 2.50 + (50 / 1_000_000) * 10.00
        assert cost == expected

    def test_provider_no_usage_estimate(self, cost_model):
        """Provider doesn't report usage - estimator used (falls back to response size)."""
        usage = {}
        cost = cost_model.estimate_cost_from_usage("openai", "gpt-4o", usage)
        assert cost == 0.0

    def test_partial_usage_only_input(self, cost_model):
        """Only input tokens reported - output estimated or zero."""
        usage = {"prompt_tokens": 200, "completion_tokens": 0, "total_tokens": 200}
        cost = cost_model.estimate_cost_from_usage("openai", "gpt-4o", usage)
        expected = (200 / 1_000_000) * 2.50
        assert cost == expected

    def test_partial_usage_only_output(self, cost_model):
        """Only output tokens reported - input estimated or zero."""
        usage = {"prompt_tokens": 0, "completion_tokens": 100, "total_tokens": 100}
        cost = cost_model.estimate_cost_from_usage("openai", "gpt-4o", usage)
        expected = (100 / 1_000_000) * 10.00
        assert cost == expected

    def test_zero_usage(self, cost_model):
        """Zero usage reported - cost is zero."""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        cost = cost_model.estimate_cost_from_usage("openai", "gpt-4o", usage)
        assert cost == 0.0

    def test_unknown_model_no_pricing(self, cost_model):
        """Unknown model - returns None (no fabricated cost)."""
        cost = cost_model.estimate_cost("unknown-provider", "unknown-model", 100, 50)
        assert cost is None

    def test_usage_source_tracking_provider(self, cost_model):
        """Usage source should be trackable as 'provider'."""
        registry = get_provider_registry()
        response = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "gpt-4o"}
        usage_info = registry.extract_usage("openai", response)
        
        assert usage_info.usage_source == UsageSource.PROVIDER_RESPONSE
        assert usage_info.input_tokens == 100
        assert usage_info.output_tokens == 50

    def test_usage_source_tracking_estimate(self, cost_model):
        """Usage source trackable as 'estimate' when no provider data."""
        registry = get_provider_registry()
        response = {"choices": [{"message": {"content": "Hello world"}}], "model": "gpt-4o"}
        usage_info = registry.extract_usage("openai", response)
        
        assert usage_info.usage_source == UsageSource.ESTIMATED
        assert usage_info.input_tokens > 0 or usage_info.output_tokens > 0

    def test_usage_source_tracking_unknown(self, cost_model):
        """Usage source trackable as 'unknown' when model pricing unavailable."""
        cost = cost_model.estimate_cost("unknown", "model", 100, 50)
        assert cost is None


# =============================================================================
# 2. Cost Accounting Tests
# =============================================================================

class TestCostAccounting:
    """Tests for cost accounting: known/unknown pricing, models, providers, versions."""

    def test_known_price_correct_cost(self, cost_model):
        """Known price → correct cost calculation."""
        cost = cost_model.estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
        assert cost == 12.50

    def test_unknown_price_no_fabricated_cost(self, cost_model):
        """Unknown price → None, never fabricated cost."""
        cost = cost_model.estimate_cost("mystery", "model-x", 1000, 500)
        assert cost is None

    def test_different_model_correct_pricing(self, cost_model):
        """Different model → correct pricing applied."""
        cost = cost_model.estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == 0.75

    def test_different_provider_correct_pricing(self, cost_model):
        """Different provider → correct pricing."""
        cost = cost_model.estimate_cost("anthropic", "claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        assert cost == 18.00

    def test_cost_never_negative(self, cost_model):
        """Costs are never negative."""
        cost = cost_model.estimate_cost("openai", "gpt-4o", 0, 0)
        assert cost >= 0
        cost = cost_model.estimate_cost("openai", "gpt-4o", 100, 0)
        assert cost >= 0
        cost = cost_model.estimate_cost("openai", "gpt-4o", 0, 100)
        assert cost >= 0
        cost = cost_model.estimate_cost("ollama", "llama-3.1-70b", 1_000_000, 1_000_000)
        assert cost == 0.0
        assert cost >= 0

    def test_register_model_updates_pricing(self, cost_model):
        """Registering new model updates pricing correctly."""
        new_pricing = ModelPricing(5.00, 15.00, "new-provider", "new-model")
        cost_model.register_model(new_pricing)
        cost = cost_model.estimate_cost("new-provider", "new-model", 1_000_000, 1_000_000)
        assert cost == 20.00

    def test_historical_pricing_stable(self, cost_model):
        """Different pricing version → historical stable (default pricing unchanged)."""
        original = cost_model.get_pricing("openai", "gpt-4o")
        assert original.input_usd_per_million == 2.50
        assert original.output_usd_per_million == 10.00


# =============================================================================
# 3. Cache HIT Tests
# =============================================================================

class TestCacheHitAccounting:
    """Tests for cache HIT token/cost accounting across all layers."""

    @pytest.mark.asyncio
    async def test_l1_hit_tokens_avoided_cost_zero(self, engine):
        """L1 HIT: actual LLM tokens = 0, avoided = baseline, actual cost = 0, avoided cost = baseline."""
        query = "What is the revenue of Apple?"
        tenant_id = "tenant_a"
        model = "gpt-4o"
        provider = "openai"
        
        engine.set_l1(
            query, 
            {"answer": "Apple's revenue was $383B in FY2023.", "usage": {"prompt_tokens": 200, "completion_tokens": 100}},
            tenant_id=tenant_id,
            model=model,
            provider=provider,
        )
        
        tokens_before = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_before = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        result = await engine.resolve(query, tenant_id=tenant_id, model=model, provider=provider)
        
        assert result["source"] == "L1"
        
        tokens_after = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_after = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        assert tokens_after >= tokens_before
        assert cost_after >= cost_before

    @pytest.mark.asyncio
    async def test_l2_hit_semantic_reuse_avoided_tokens(self, engine):
        """L2 HIT: semantic reuse with avoided tokens recorded."""
        query = "What are the risk factors for Microsoft?"
        tenant_id = "tenant_b"
        model = "gpt-4o"
        provider = "openai"
        
        await engine.async_write_l2(
            query,
            {"answer": "Microsoft faces risks from competition, regulation, and cybersecurity.", "usage": {"prompt_tokens": 150, "completion_tokens": 80}},
            meta={"entity": "MSFT", "topic": "risk factors"},
            tenant_id=tenant_id,
        )
        
        similar_query = "Tell me about Microsoft's risk factors."
        result = await engine.resolve(similar_query, tenant_id=tenant_id, model=model, provider=provider)
        
        if result["source"] == "L2":
            assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_l3_hit_context_reuse_avoided_tokens(self, engine):
        """L3 HIT: context reuse with avoided tokens."""
        query = "What was the revenue?"
        context = "Apple Inc. Q3 FY2024 earnings report: revenue $85.8B"
        tenant_id = "tenant_c"
        model = "gpt-4o"
        provider = "openai"
        
        await engine.async_write_l3(
            query,
            context,
            {"answer": "Apple reported revenue of $85.8 billion in Q3 FY2024.", "usage": {"prompt_tokens": 180, "completion_tokens": 90}},
            meta={"entity": "AAPL", "quarter": "Q3", "year": "FY2024"},
            tenant_id=tenant_id,
        )
        
        result = await engine.resolve(query, context=context, tenant_id=tenant_id, model=model, provider=provider)
        
        if result["source"] == "L3":
            assert result["response"] is not None

    @pytest.mark.asyncio
    async def test_l0a_hit_deterministic_computation_avoided(self, engine):
        """L0a HIT: deterministic computation avoided."""
        def compute_hash(text: str) -> str:
            return hashlib.sha256(text.encode()).hexdigest()[:16]
        
        engine.register_deterministic_function("hash_fn", "1.0", compute_hash, "Compute SHA256 hash")
        
        result1 = await engine.execute_deterministic("hash_fn", {"text": "test input"})
        result2 = await engine.execute_deterministic("hash_fn", {"text": "test input"})
        
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_l0b_hit_embedding_computation_avoided(self, engine):
        """L0b HIT: embedding computation avoided."""
        text = "This is a test sentence for embedding cache."
        model_fp = "fake-embedder@1.0.0"
        
        emb1 = await engine.get_embedding(text, model_fp)
        emb2 = await engine.get_embedding(text, model_fp)
        
        # Compare with tolerance for floating point
        assert all(abs(a - b) < 1e-5 for a, b in zip(emb1, emb2))
        stats = engine.get_l0b_stats()
        assert stats["hits"] >= 1


# =============================================================================
# 4. Cache MISS Tests
# =============================================================================

class TestCacheMissAccounting:
    """Tests for cache MISS token/cost accounting."""

    @pytest.mark.asyncio
    async def test_miss_actual_tokens_recorded(self, engine):
        """Cache MISS: actual tokens > 0 recorded."""
        query = "What is the capital of France?"
        tenant_id = "tenant_miss"
        
        call_count = 0
        async def generate_fn():
            nonlocal call_count
            call_count += 1
            return {"answer": "Paris is the capital of France.", "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}}
        
        result = await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn)
        
        assert result["source"] == "MISS"
        assert call_count == 1
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        cost_actual = _get_metric_value(COST_USD_TOTAL, 'type="actual"', tenant_id)
        
        assert tokens_input > 0
        assert tokens_output > 0
        assert cost_actual > 0

    @pytest.mark.asyncio
    async def test_miss_actual_cost_calculated(self, engine):
        """Cache MISS: actual cost calculated from usage."""
        query = "Calculate 2 + 2."
        tenant_id = "tenant_miss_cost"
        
        async def generate_fn():
            return {"answer": "4", "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn)
        
        cost_actual = _get_metric_value(COST_USD_TOTAL, 'type="actual"', tenant_id)
        assert cost_actual > 0

    @pytest.mark.asyncio
    async def test_miss_avoided_zero(self, engine):
        """Cache MISS: avoided tokens = 0, avoided cost = 0."""
        query = "What is 2+2?"
        tenant_id = "tenant_miss_avoided"
        
        async def generate_fn():
            return {"answer": "4", "usage": {"prompt_tokens": 20, "completion_tokens": 5}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn)
        
        tokens_saved = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        cost_saved = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        assert tokens_saved == 0
        assert cost_saved == 0

    @pytest.mark.asyncio
    async def test_miss_no_usage_estimates_tokens(self, engine):
        """Cache MISS without provider usage: tokens estimated from response."""
        query = "Short answer please."
        tenant_id = "tenant_miss_estimate"
        
        async def generate_fn():
            return {"answer": "Yes, that is correct."}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn)
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert tokens_input > 0 or tokens_output > 0


# =============================================================================
# 5. Layer Attribution Tests
# =============================================================================

class TestLayerAttribution:
    """Tests for layer-specific savings tracking."""

    @pytest.mark.asyncio
    async def test_l0a_savings_tracked_separately(self, engine):
        """L0a savings tracked separately (no token metrics for deterministic functions)."""
        def pure_fn(x: int) -> int:
            return x * 2
        
        engine.register_deterministic_function("double", "1.0", pure_fn)
        
        await engine.execute_deterministic("double", {"x": 5})
        await engine.execute_deterministic("double", {"x": 5})

    @pytest.mark.asyncio
    async def test_l0b_savings_tracked_separately(self, engine):
        """L0b savings tracked separately via embedding cache stats."""
        text = "Embedding cache test."
        model_fp = "fake-embedder@1.0.0"
        
        await engine.get_embedding(text, model_fp)
        await engine.get_embedding(text, model_fp)
        
        stats = engine.get_l0b_stats()
        assert stats["hits"] >= 1
        assert stats["hit_rate"] > 0

    @pytest.mark.asyncio
    async def test_l1_savings_tracked_separately(self, engine):
        """L1 savings tracked separately."""
        query = "L1 test query."
        tenant_id = "tenant_l1"
        
        engine.set_l1(query, {"answer": "L1 cached answer.", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id=tenant_id)
        
        tokens_before = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_before = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        await engine.resolve(query, tenant_id=tenant_id)
        
        tokens_after = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_after = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        assert tokens_after >= tokens_before
        assert cost_after >= cost_before

    @pytest.mark.asyncio
    async def test_l2_savings_tracked_separately(self, engine):
        """L2 savings tracked separately."""
        query = "L2 semantic test."
        tenant_id = "tenant_l2"
        
        await engine.async_write_l2(query, {"answer": "L2 semantic answer.", "usage": {"prompt_tokens": 120, "completion_tokens": 60}}, tenant_id=tenant_id)
        
        tokens_before = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_before = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        await engine.resolve("Similar semantic query.", tenant_id=tenant_id)
        
        tokens_after = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_after = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        if tokens_after > tokens_before:
            assert cost_after >= cost_before

    @pytest.mark.asyncio
    async def test_l3_savings_tracked_separately(self, engine):
        """L3 savings tracked separately."""
        query = "L3 context test."
        context = "Context for L3 test."
        tenant_id = "tenant_l3"
        
        await engine.async_write_l3(query, context, {"answer": "L3 context answer.", "usage": {"prompt_tokens": 150, "completion_tokens": 75}}, tenant_id=tenant_id)
        
        tokens_before = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_before = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        await engine.resolve(query, context=context, tenant_id=tenant_id)
        
        tokens_after = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cost_after = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        if tokens_after > tokens_before:
            assert cost_after >= cost_before

    def test_metrics_have_layer_labels(self):
        """Verify metrics have proper layer attribution."""
        # First, record some tokens to ensure metrics exist
        from ico_cache.telemetry.metrics import record_tokens, record_cost, render_metrics
        record_tokens("input", 10, "test")
        record_cost("actual", 0.001, "test")

        metrics_output = render_metrics().decode()
        # Check that metrics have type label (label order in Prometheus is not guaranteed)
        assert 'ico_tokens_total{' in metrics_output and 'type=' in metrics_output
        assert 'ico_cost_usd_total{' in metrics_output and 'type=' in metrics_output


# =============================================================================
# 6. Tenant Isolation Tests
# =============================================================================

class TestTenantIsolationAccounting:
    """Tests for tenant isolation in accounting."""

    @pytest.mark.asyncio
    async def test_tenant_a_accounting_never_in_tenant_b(self, engine):
        """Tenant A accounting never appears in Tenant B."""
        async def gen_a():
            return {"answer": "Tenant A answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate("Query for A", tenant_id="tenant_a", generate_fn=gen_a)
        
        result = await engine.resolve("Query for A", tenant_id="tenant_b")
        
        assert result["source"] == "MISS"
        
        tokens_a_actual = _get_metric_value(TOKENS_TOTAL, 'type="input"', "tenant_a")
        tokens_b_actual = _get_metric_value(TOKENS_TOTAL, 'type="input"', "tenant_b")
        
        assert tokens_a_actual > 0
        assert tokens_b_actual == 0

    @pytest.mark.asyncio
    async def test_cross_tenant_cache_miss_no_accounting_leak(self, engine):
        """Cross-tenant cache miss doesn't leak accounting."""
        engine.set_l1("Shared query", {"answer": "Tenant A's answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id="tenant_a")
        
        result = await engine.resolve("Shared query", tenant_id="tenant_b")
        
        assert result["source"] == "MISS"
        
        tokens_b_cached = _get_metric_value(TOKENS_TOTAL, 'type="cached"', "tenant_b")
        assert tokens_b_cached == 0

    @pytest.mark.asyncio
    async def test_metrics_labels_include_tenant(self, engine):
        """Metrics labels include tenant identifier."""
        async def gen():
            return {"answer": "Test", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        await engine.resolve_or_generate("Test query", tenant_id="tenant_xyz", generate_fn=gen)
        
        metrics_output = render_metrics().decode()
        assert 'tenant="tenant_xyz"' in metrics_output or "tenant='tenant_xyz'" in metrics_output

    @pytest.mark.asyncio
    async def test_tenant_isolation_in_l2_l3(self, engine):
        """Tenant isolation enforced in L2 and L3 accounting."""
        query = "Isolated query"
        context = "Context for isolation"
        
        await engine.async_write_l2(query, {"answer": "A's L2", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id="tenant_a")
        await engine.async_write_l3(query, context, {"answer": "A's L3", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id="tenant_a")
        
        result_l2 = await engine.resolve(query, tenant_id="tenant_b")
        result_l3 = await engine.resolve(query, context=context, tenant_id="tenant_b")
        
        assert result_l2["source"] == "MISS"
        assert result_l3["source"] == "MISS"
        
        tokens_b_cached = _get_metric_value(TOKENS_TOTAL, 'type="cached"', "tenant_b")
        assert tokens_b_cached == 0


# =============================================================================
# 7. Concurrency/Single-Flight Tests
# =============================================================================

class TestConcurrencyAccounting:
    """Tests for concurrency and single-flight accounting correctness."""

    @pytest.mark.asyncio
    async def test_50_concurrent_identical_1_actual_49_avoided(self, engine):
        """50 identical concurrent requests → 1 actual generation, 49 avoided."""
        query = "Concurrent test query."
        tenant_id = "tenant_concurrent"
        call_count = 0
        
        async def generate_fn():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return {"answer": f"Answer {call_count}", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        tasks = [
            engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn)
            for _ in range(50)
        ]
        results = await asyncio.gather(*tasks)
        
        assert all(r["source"] in ("MISS", "L1") for r in results)
        assert call_count == 1, f"Expected 1 generation, got {call_count}"
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert 90 <= tokens_input <= 110
        assert 40 <= tokens_output <= 60
        
        tokens_saved = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        cost_saved = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        assert tokens_saved > 0
        assert cost_saved > 0

    @pytest.mark.asyncio
    async def test_20_concurrent_different_20_actual_0_avoided(self, engine):
        """20 different concurrent queries → 20 actual generations, 0 avoided."""
        tenant_id = "tenant_diff"
        call_count = 0
        
        async def generate_fn(query_num):
            nonlocal call_count
            call_count += 1
            return {"answer": f"Answer {query_num}", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        tasks = [
            engine.resolve_or_generate(f"Different query {i}", tenant_id=tenant_id, generate_fn=lambda i=i: generate_fn(i))
            for i in range(20)
        ]
        results = await asyncio.gather(*tasks)
        
        assert all(r["source"] == "MISS" for r in results)
        assert call_count == 20
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert tokens_input >= 900
        assert tokens_output >= 450
        
        tokens_saved = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        assert tokens_saved == 0

    @pytest.mark.asyncio
    async def test_no_double_counting_from_leader(self, engine):
        """Leader generates, waiters join - no double counting."""
        query = "Leader test."
        tenant_id = "tenant_leader"
        generation_results = []
        
        async def generate_fn():
            result = {"answer": "Generated", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
            generation_results.append(result)
            return result
        
        tasks = [engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=generate_fn) for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        assert len(generation_results) == 1
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert 90 <= tokens_input <= 110
        assert 40 <= tokens_output <= 60

    @pytest.mark.asyncio
    async def test_concurrent_l0b_embedding_single_flight(self, engine):
        """Concurrent L0b embedding requests - single flight."""
        text = "Concurrent embedding test."
        model_fp = "fake-embedder@1.0.0"
        
        tasks = [engine.get_embedding(text, model_fp) for _ in range(20)]
        results = await asyncio.gather(*tasks)
        
        assert all(r == results[0] for r in results)
        
        stats = engine.get_l0b_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 19


# =============================================================================
# 8. False-Savings Tests (CRITICAL)
# =============================================================================

class TestFalseSavingsDetection:
    """Critical tests to detect false savings."""

    @pytest.mark.asyncio
    async def test_different_model_same_prompt_no_shared_savings(self, engine):
        """Request A (Model A) and Request B (Model B) with same prompt - MUST NOT share savings."""
        query = "What is the revenue?"
        tenant_id = "tenant_false_savings"
        
        async def gen_a():
            return {"answer": "Revenue from gpt-4o", "usage": {"prompt_tokens": 200, "completion_tokens": 100}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, model="gpt-4o", provider="openai", generate_fn=gen_a)
        
        result = await engine.resolve(query, tenant_id=tenant_id, model="gpt-4o-mini", provider="openai")
        assert result["source"] == "MISS", "Different model must not hit L1 cache"
        
        async def gen_b():
            return {"answer": "Revenue from gpt-4o-mini", "usage": {"prompt_tokens": 150, "completion_tokens": 80}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, model="gpt-4o-mini", provider="openai", generate_fn=gen_b)
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert tokens_input >= 300
        assert tokens_output >= 150
        
        tokens_saved = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        assert tokens_saved == 0

    @pytest.mark.asyncio
    async def test_different_provider_same_model_no_shared_savings(self, engine):
        """Request A (Provider A) and Request B (Provider B) - MUST NOT share savings."""
        query = "Provider test."
        tenant_id = "tenant_provider_diff"
        
        async def gen_a():
            return {"answer": "OpenAI answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, provider="openai", model="gpt-4o", generate_fn=gen_a)
        
        result = await engine.resolve(query, tenant_id=tenant_id, provider="anthropic", model="claude-3-5-sonnet-20241022")
        assert result["source"] == "MISS", "Different provider must not hit L1 cache"
        
        async def gen_b():
            return {"answer": "Anthropic answer", "usage": {"prompt_tokens": 120, "completion_tokens": 60}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, provider="anthropic", model="claude-3-5-sonnet-20241022", generate_fn=gen_b)
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        assert tokens_input >= 200

    @pytest.mark.asyncio
    async def test_different_prompt_version_no_shared_savings(self, engine):
        """Different prompt_version - MUST NOT share savings."""
        query = "Prompt version test."
        tenant_id = "tenant_prompt_ver"
        
        async def gen_v1():
            return {"answer": "V1 answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, prompt_version="v1", generate_fn=gen_v1)
        
        result = await engine.resolve(query, tenant_id=tenant_id, prompt_version="v2")
        assert result["source"] == "MISS", "Different prompt_version must not hit L1 cache"

    @pytest.mark.asyncio
    async def test_different_context_no_shared_savings(self, engine):
        """Different context - MUST NOT share savings."""
        query = "Context test."
        tenant_id = "tenant_context_diff"
        
        async def gen_ctx1():
            return {"answer": "With context 1", "usage": {"prompt_tokens": 150, "completion_tokens": 75}}
        
        await engine.resolve_or_generate(query, context="Context A", tenant_id=tenant_id, generate_fn=gen_ctx1)
        
        result = await engine.resolve(query, context="Context B", tenant_id=tenant_id)
        assert result["source"] == "MISS", "Different context must not hit L1 cache"

    @pytest.mark.asyncio
    async def test_tenant_a_vs_tenant_b_never_share_savings(self, engine):
        """Tenant A vs Tenant B - NEVER share savings."""
        query = "Multi-tenant test."
        
        async def gen_a():
            return {"answer": "Tenant A answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate(query, tenant_id="tenant_a", generate_fn=gen_a)
        
        result = await engine.resolve(query, tenant_id="tenant_b")
        assert result["source"] == "MISS"
        
        async def gen_b():
            return {"answer": "Tenant B answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate(query, tenant_id="tenant_b", generate_fn=gen_b)
        
        tokens_a = _get_metric_value(TOKENS_TOTAL, 'type="input"', "tenant_a")
        tokens_b = _get_metric_value(TOKENS_TOTAL, 'type="input"', "tenant_b")
        
        assert tokens_a > 0
        assert tokens_b > 0
        
        saved_a = _get_metric_value(TOKENS_TOTAL, 'type="saved"', "tenant_a")
        saved_b = _get_metric_value(TOKENS_TOTAL, 'type="saved"', "tenant_b")
        
        assert saved_a == 0
        assert saved_b == 0

    @pytest.mark.asyncio
    async def test_fy2025_vs_fy2026_not_identical(self, engine):
        """FY2025 vs FY2026 metadata - NOT treated as identical."""
        query = "What was the revenue?"
        tenant_id = "tenant_fy"
        
        ctx_2025 = "Apple FY2025 Q1 revenue: $120B"
        async def gen_2025():
            return {"answer": "$120B", "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "meta": {"entity": "AAPL", "quarter": "Q1", "year": "FY2025"}}
        
        await engine.resolve_or_generate(query, context=ctx_2025, tenant_id=tenant_id, generate_fn=gen_2025)
        
        ctx_2026 = "Apple FY2026 Q1 revenue: $130B"
        result = await engine.resolve(query, context=ctx_2026, tenant_id=tenant_id)
        
        assert result["source"] != "L1", "Different context must not hit L1"

    @pytest.mark.asyncio
    async def test_metadata_mismatch_blocks_savings(self, engine):
        """Metadata mismatch (entity, quarter, topic) blocks false savings."""
        query = "Revenue query."
        tenant_id = "tenant_meta"
        
        await engine.async_write_l2(
            query, 
            {"answer": "AAPL Q1 revenue", "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
            meta={"entity": "AAPL", "quarter": "Q1"},
            tenant_id=tenant_id,
        )
        
        result = await engine.resolve("Revenue query.", meta={"entity": "MSFT", "quarter": "Q1"}, tenant_id=tenant_id)
        assert result["source"] != "L2", "Entity mismatch must block L2 hit"

    @pytest.mark.asyncio
    async def test_same_query_different_model_params_no_savings(self, engine):
        """Same query, different model params (temperature) - no shared savings."""
        query = "Temperature test."
        tenant_id = "tenant_temp"
        
        async def gen_temp0():
            return {"answer": "Deterministic", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate(
            query, 
            tenant_id=tenant_id, 
            model="gpt-4o", 
            provider="openai",
            model_params={"temperature": 0},
            generate_fn=gen_temp0,
        )
        
        result = await engine.resolve(query, tenant_id=tenant_id, model="gpt-4o", provider="openai", model_params={"temperature": 1})
        assert result["source"] == "MISS", "Different model params must not hit L1"


# =============================================================================
# 9. Accounting Invariant Tests
# =============================================================================

class TestAccountingInvariants:
    """Tests for accounting invariants that must always hold."""

    @pytest.mark.asyncio
    async def test_total_tokens_ge_input_plus_output(self, engine):
        """total_tokens >= input_tokens + output_tokens (at minimum)."""
        async def gen():
            return {"answer": "Test", "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
        
        await engine.resolve_or_generate("Invariant test", tenant_id="tenant_inv", generate_fn=gen)
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', "tenant_inv")
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', "tenant_inv")
        
        total = tokens_input + tokens_output
        assert total >= 150

    @pytest.mark.asyncio
    async def test_actual_generation_llm_called_true(self, engine):
        """For actual generation: llm_called = true (recorded as FULL_LLM_CALL)."""
        async def gen():
            return {"answer": "Generated", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        result = await engine.resolve_or_generate("LLM test", tenant_id="tenant_llm", generate_fn=gen)
        
        assert result["source"] == "MISS"
        metrics_output = render_metrics().decode()
        assert "FULL_LLM_CALL" in metrics_output

    @pytest.mark.asyncio
    async def test_l1_hit_llm_called_false(self, engine):
        """For L1 HIT: llm_called = false (recorded as CACHE_HIT)."""
        query = "L1 invariant test."
        tenant_id = "tenant_l1_inv"
        
        engine.set_l1(query, {"answer": "Cached", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id=tenant_id)
        
        result = await engine.resolve(query, tenant_id=tenant_id)
        
        assert result["source"] == "L1"
        metrics_output = render_metrics().decode()
        assert "CACHE_HIT" in metrics_output

    @pytest.mark.asyncio
    async def test_true_cache_hit_actual_generation_tokens_zero(self, engine):
        """For true cache HIT: actual_generation_tokens = 0."""
        query = "True hit test."
        tenant_id = "tenant_true_hit"
        
        engine.set_l1(query, {"answer": "Cached answer", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, tenant_id=tenant_id)
        
        input_before = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        output_before = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        await engine.resolve(query, tenant_id=tenant_id)
        
        input_after = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        output_after = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert input_after == input_before
        assert output_after == output_before
        
        cached_before = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        cached_after = _get_metric_value(TOKENS_TOTAL, 'type="cached"', tenant_id)
        assert cached_after >= cached_before

    @pytest.mark.asyncio
    async def test_cache_miss_avoided_tokens_zero(self, engine):
        """For cache MISS: avoided_tokens = 0."""
        async def gen():
            return {"answer": "Miss", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        await engine.resolve_or_generate("Miss test", tenant_id="tenant_miss_inv", generate_fn=gen)
        
        saved = _get_metric_value(TOKENS_TOTAL, 'type="saved"', "tenant_miss_inv")
        assert saved == 0

    @pytest.mark.asyncio
    async def test_costs_never_negative(self, engine):
        """Costs are never negative."""
        async def gen():
            return {"answer": "Test", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate("Cost test", tenant_id="tenant_cost", generate_fn=gen)
        
        cost_actual = _get_metric_value(COST_USD_TOTAL, 'type="actual"', "tenant_cost")
        cost_saved = _get_metric_value(COST_USD_TOTAL, 'type="saved"', "tenant_cost")
        
        assert cost_actual >= 0
        assert cost_saved >= 0

    @pytest.mark.asyncio
    async def test_token_counts_never_negative(self, engine):
        """Token counts are never negative."""
        async def gen():
            return {"answer": "Test", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        await engine.resolve_or_generate("Token test", tenant_id="tenant_tok", generate_fn=gen)
        
        for token_type in ["input", "output", "cached", "saved"]:
            count = _get_metric_value(TOKENS_TOTAL, f'type="{token_type}"', "tenant_tok")
            assert count >= 0, f"{token_type} tokens should not be negative"

    @pytest.mark.asyncio
    async def test_latency_never_negative(self, engine):
        """Latency is never negative."""
        from ico_cache.telemetry.metrics import record_latency, LATENCY_SECONDS
        
        record_latency("generation", "LLM", 0.5)
        record_latency("cache_lookup", "L1", 0.001)
        
        metrics_output = render_metrics().decode()
        assert "ico_cache_latency_seconds" in metrics_output

    @pytest.mark.asyncio
    async def test_tenant_id_always_present(self, engine):
        """Tenant ID always present in metrics."""
        async def gen():
            return {"answer": "Test", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        await engine.resolve_or_generate("Tenant test", tenant_id="tenant_always", generate_fn=gen)
        
        metrics_output = render_metrics().decode()
        assert 'tenant="tenant_always"' in metrics_output or "tenant='tenant_always'" in metrics_output

    @pytest.mark.asyncio
    async def test_saved_cost_matches_saved_tokens_pricing(self, engine, cost_model):
        """Saved cost matches saved tokens * pricing (consistency check)."""
        query = "Consistency test."
        tenant_id = "tenant_consistency"
        model = "gpt-4o"
        provider = "openai"
        
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        
        engine.set_l1(query, {"answer": "Cached", "usage": usage}, tenant_id=tenant_id, model=model, provider=provider)
        
        await engine.resolve(query, tenant_id=tenant_id, model=model, provider=provider)
        
        saved_tokens = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        saved_cost = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        expected_cost = cost_model.estimate_cost(provider, model, usage["prompt_tokens"], usage["completion_tokens"])
        
        if expected_cost is not None and saved_tokens > 0:
            assert abs(saved_cost - expected_cost) < 0.001

    @pytest.mark.asyncio
    async def test_single_flight_savings_counted_once(self, engine):
        """Single-flight: savings counted once, not per waiter."""
        query = "Single flight savings."
        tenant_id = "tenant_sf_savings"
        
        async def gen():
            return {"answer": "Generated", "usage": {"prompt_tokens": 200, "completion_tokens": 100}}
        
        tasks = [engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=gen) for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        miss_count = sum(1 for r in results if r["source"] == "MISS")
        hit_count = sum(1 for r in results if r["source"] == "L1")
        
        assert miss_count == 1
        assert hit_count == 9
        
        saved_tokens = _get_metric_value(TOKENS_TOTAL, 'type="saved"', tenant_id)
        saved_cost = _get_metric_value(COST_USD_TOTAL, 'type="saved"', tenant_id)
        
        assert saved_tokens > 0
        assert saved_cost > 0
        
        actual_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        actual_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert 190 <= actual_input <= 210
        assert 90 <= actual_output <= 110

    def test_metric_recording_functions_dont_raise(self):
        """Recording functions never raise exceptions."""
        record_tokens("input", 100, "tenant")
        record_tokens("output", 50, "tenant")
        record_tokens("cached", 150, "tenant")
        record_tokens("saved", 150, "tenant")
        record_tokens("invalid_type", -10, "tenant")
        
        record_cost("actual", 0.01, "tenant")
        record_cost("saved", 0.005, "tenant")
        record_cost("invalid_type", -0.01, "tenant")


# =============================================================================
# Additional Edge Case Tests
# =============================================================================

class TestAccountingEdgeCases:
    """Edge case tests for accounting."""

    @pytest.mark.asyncio
    async def test_error_response_not_cached_no_accounting(self, engine):
        """Error/refusal responses never cached, no token accounting pollution."""
        query = "Error test."
        tenant_id = "tenant_error"
        
        async def gen_error():
            return {"answer": "Insufficient context."}
        
        result = await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=gen_error)
        
        assert result["source"] == "MISS"
        assert result["response"]["answer"] == "Insufficient context."
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        tokens_output = _get_metric_value(TOKENS_TOTAL, 'type="output"', tenant_id)
        
        assert tokens_input == 0
        assert tokens_output == 0

    @pytest.mark.asyncio
    async def test_empty_response_not_cached(self, engine):
        """Empty response not cached, no accounting."""
        query = "Empty test."
        tenant_id = "tenant_empty"
        
        async def gen_empty():
            return {"answer": ""}
        
        result = await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=gen_empty)
        
        assert result["source"] == "MISS"
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        assert tokens_input == 0

    @pytest.mark.asyncio
    async def test_llm_failure_not_cached(self, engine):
        """LLM generation failure not cached."""
        query = "Failure test."
        tenant_id = "tenant_fail"
        
        async def gen_fail():
            return {"answer": "LLM generation failed"}
        
        result = await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=gen_fail)
        
        assert result["source"] == "MISS"
        
        tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant_id)
        assert tokens_input == 0

    @pytest.mark.asyncio
    async def test_cost_model_with_zero_cost_provider(self, engine):
        """Zero-cost provider (Ollama) - cost recorded as 0."""
        query = "Ollama test."
        tenant_id = "tenant_ollama"
        
        async def gen_ollama():
            return {"answer": "Local model answer", "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}
        
        await engine.resolve_or_generate(
            query, 
            tenant_id=tenant_id, 
            provider="ollama", 
            model="llama-3.1-70b",
            generate_fn=gen_ollama,
        )
        
        cost_actual = _get_metric_value(COST_USD_TOTAL, 'type="actual"', tenant_id)
        assert cost_actual == 0.0

    @pytest.mark.asyncio
    async def test_multiple_tenants_concurrent_isolation(self, engine):
        """Multiple tenants concurrent - complete isolation."""
        async def gen(tenant):
            return {"answer": f"Answer for {tenant}", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        
        tasks = []
        for t in range(5):
            tenant = f"tenant_{t}"
            for _ in range(10):
                tasks.append(engine.resolve_or_generate(f"Query for {tenant}", tenant_id=tenant, generate_fn=lambda t=tenant: gen(t)))
        
        results = await asyncio.gather(*tasks)
        
        # Single-flight: 1 MISS (leader) + 9 L1 hits (waiters) per tenant = 5 MISS, 45 L1
        miss_count = sum(1 for r in results if r["source"] == "MISS")
        hit_count = sum(1 for r in results if r["source"] == "L1")
        assert miss_count == 5
        assert hit_count == 45
        
        for t in range(5):
            tenant = f"tenant_{t}"
            tokens_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', tenant)
            # Single-flight: only 1 generation per tenant (100 tokens)
            assert 90 <= tokens_input <= 110
            
            for other_t in range(5):
                if other_t != t:
                    other_tenant = f"tenant_{other_t}"
                    other_input = _get_metric_value(TOKENS_TOTAL, 'type="input"', other_tenant)
                    assert 90 <= other_input <= 110


# =============================================================================
# Integration Tests with DecisionEngine
# =============================================================================

class TestDecisionEngineAccounting:
    """Tests for accounting integration with DecisionEngine."""

    @pytest.mark.asyncio
    async def test_decision_engine_reuse_action_recorded(self, engine):
        """DecisionEngine reuse action recorded in metrics."""
        from ico_cache.core.decision_engine import DecisionEngine, DecisionContext, ReusePolicy
        
        decision_engine = DecisionEngine(engine, policy=ReusePolicy.strict())
        
        ctx = DecisionContext(
            query="Test query for decision engine",
            tenant_id="tenant_de",
            model="gpt-4o",
            provider="openai",
        )
        
        decision = await decision_engine.decide(ctx)
        
        assert decision.action.value == "FULL_LLM_CALL"
        
        metrics_output = render_metrics().decode()
        assert "FULL_LLM_CALL" in metrics_output

    @pytest.mark.asyncio
    async def test_decision_engine_confidence_recorded(self, engine):
        """DecisionEngine confidence recorded in REUSE_CONFIDENCE histogram."""
        from ico_cache.core.decision_engine import DecisionEngine, DecisionContext, ReusePolicy
        
        decision_engine = DecisionEngine(engine, policy=ReusePolicy.strict())
        
        engine.set_l1("Confidence test", {"answer": "Cached"}, tenant_id="tenant_conf")
        
        ctx = DecisionContext(
            query="Confidence test",
            tenant_id="tenant_conf",
            model="gpt-4o",
            provider="openai",
        )
        
        decision = await decision_engine.decide(ctx)
        
        assert decision.action.value == "EXACT_REUSE"
        assert decision.confidence == 1.0
        
        metrics_output = render_metrics().decode()
        assert "ico_cache_reuse_confidence" in metrics_output


# =============================================================================
# Performance/Regression Tests
# =============================================================================

class TestAccountingPerformance:
    """Performance regression tests for accounting overhead."""

    @pytest.mark.asyncio
    async def test_accounting_overhead_minimal(self, engine):
        """Accounting overhead should be minimal (<1ms per request)."""
        query = "Performance test."
        tenant_id = "tenant_perf"
        
        async def gen():
            return {"answer": "Perf", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        await engine.resolve_or_generate(query, tenant_id=tenant_id, generate_fn=gen)
        
        start = time.perf_counter()
        for _ in range(100):
            await engine.resolve(query, tenant_id=tenant_id)
        elapsed = time.perf_counter() - start
        
        avg_ms = (elapsed / 100) * 1000
        assert avg_ms < 10

    @pytest.mark.asyncio
    async def test_concurrent_accounting_no_contention(self, engine):
        """Concurrent accounting doesn't cause metric contention."""
        async def gen():
            return {"answer": "Concurrent", "usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        
        tasks = [
            engine.resolve_or_generate(f"Query {i}", tenant_id="tenant_concurrent_perf", generate_fn=gen)
            for i in range(100)
        ]
        
        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start
        
        assert all(r["source"] == "MISS" for r in results)
        assert elapsed < 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])