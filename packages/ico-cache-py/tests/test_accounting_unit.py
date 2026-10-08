"""Unit tests for accounting and usage tracking (Phase 3A.5)."""
import pytest
import threading
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from ico_cache.telemetry.accounting import (
    DecisionAction,
    UsageSource,
    PricingVersion,
    UsageRecord,
    UsageTracker,
    CostCalculator,
    SavingsCalculator,
    PricingModel,
    get_usage_tracker,
    set_usage_tracker,
    get_cost_calculator,
    set_cost_calculator,
    get_savings_calculator,
    set_savings_calculator,
    get_pricing_model,
    set_pricing_model,
    record_usage,
    TokenUsage,
    LayerAttribution,
)
from ico_cache.telemetry.cost_model import CostModel, ModelPricing, PricingVersion as CostPricingVersion
from ico_cache.telemetry.metrics import (
    TOKENS_TOTAL,
    LLM_CALLS_TOTAL,
    LLM_CALLS_AVOIDED_TOTAL,
    EMBEDDING_CALLS_TOTAL,
    EMBEDDING_CALLS_AVOIDED_TOTAL,
    RETRIEVAL_CALLS_TOTAL,
    RETRIEVAL_CALLS_AVOIDED_TOTAL,
    COST_USD_TOTAL,
    COST_SAVED_USD_TOTAL,
    LATENCY_SAVED_SECONDS,
)


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_create_minimal(self):
        """Test creating a minimal UsageRecord."""
        record = UsageRecord.create(
            tenant_id="tenant_a",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
        )
        assert record.tenant_id == "tenant_a"
        assert record.layer == "L1"
        assert record.decision_action == DecisionAction.EXACT_REUSE
        assert record.request_id is not None
        assert record.trace_id is not None
        assert record.timestamp is not None

    def test_create_with_all_fields(self):
        """Test creating a UsageRecord with all fields."""
        record = UsageRecord(
            request_id="req-123",
            trace_id="trace-456",
            tenant_id="tenant_b",
            timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
            layer="L2",
            decision_action=DecisionAction.SEMANTIC_REUSE,
            cache_hit=1,
            cache_miss=0,
            llm_called=0,
            embedding_called=1,
            retrieval_called=0,
            reranker_called=0,
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            cached_input_tokens=50,
            avoided_input_tokens=50,
            avoided_output_tokens=100,
            avoided_total_tokens=150,
            embedding_tokens=100,
            retrieval_units=0,
            estimated_cost=0.001,
            actual_cost=0.0005,
            tokens_saved=150,
            cost_saved=0.0005,
            latency_saved=1.5,
            latency_ms=50.0,
            model="gpt-4o-mini",
            model_fingerprint="fp-abc123",
            provider="openai",
            currency="USD",
            pricing_version="2024-10",
            success=True,
            error="",
            metadata={"key": "value"},
            usage_source=UsageSource.PROVIDER_RESPONSE,
        )
        assert record.input_tokens == 100
        assert record.output_tokens == 200
        assert record.avoided_total_tokens == 150
        assert record.cost_saved == 0.0005
        assert record.usage_source == UsageSource.PROVIDER_RESPONSE

    def test_to_dict(self):
        """Test UsageRecord serialization to dict."""
        record = UsageRecord(
            request_id="req-789",
            trace_id="trace-789",
            tenant_id="tenant_c",
            timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
            layer="L3",
            decision_action=DecisionAction.FULL_LLM_CALL,
            input_tokens=500,
            output_tokens=1000,
            actual_cost=0.01,
        )
        d = record.to_dict()
        assert d["request_id"] == "req-789"
        assert d["tenant_id"] == "tenant_c"
        assert d["layer"] == "L3"
        assert d["decision_action"] == "FULL_LLM_CALL"
        assert d["input_tokens"] == 500
        assert d["output_tokens"] == 1000
        assert d["actual_cost"] == 0.01
        assert "timestamp" in d
        assert d["usage_source"] == "unknown"

    def test_validation_negative_tokens_raises(self):
        """Test that negative token counts raise ValueError."""
        with pytest.raises(ValueError):
            UsageRecord(
                request_id="req-1",
                trace_id="trace-1",
                tenant_id="tenant_1",
                timestamp=datetime.now(timezone.utc),
                layer="L1",
                decision_action=DecisionAction.EXACT_REUSE,
                input_tokens=-1,
            )

    def test_validation_negative_cost_raises(self):
        """Test that negative cost raises ValueError."""
        with pytest.raises(ValueError):
            UsageRecord(
                request_id="req-1",
                trace_id="trace-1",
                tenant_id="tenant_1",
                timestamp=datetime.now(timezone.utc),
                layer="L1",
                decision_action=DecisionAction.EXACT_REUSE,
                actual_cost=-0.01,
            )


class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_defaults(self):
        """Test default values."""
        tu = TokenUsage()
        assert tu.input_tokens == 0
        assert tu.output_tokens == 0
        assert tu.total_tokens == 0
        assert tu.cached_input_tokens == 0
        assert tu.reasoning_tokens == 0

    def test_with_values(self):
        """Test with custom values."""
        tu = TokenUsage(input_tokens=100, output_tokens=200, total_tokens=300, cached_input_tokens=50, reasoning_tokens=10)
        assert tu.input_tokens == 100
        assert tu.output_tokens == 200
        assert tu.total_tokens == 300
        assert tu.cached_input_tokens == 50
        assert tu.reasoning_tokens == 10
        assert tu.total == 300

    def test_frozen(self):
        """Test that TokenUsage is frozen."""
        tu = TokenUsage()
        with pytest.raises(Exception):
            tu.input_tokens = 100


class TestLayerAttribution:
    """Tests for LayerAttribution dataclass."""

    def test_defaults(self):
        """Test default values."""
        la = LayerAttribution()
        assert la.L1 == 0
        assert la.L2 == 0
        assert la.L3 == 0

    def test_with_values(self):
        """Test with custom values."""
        la = LayerAttribution(L1=10, L2=20, L3=30)
        assert la.L1 == 10
        assert la.L2 == 20
        assert la.L3 == 30


class TestUsageTracker:
    """Tests for UsageTracker thread-safe recording with tenant isolation."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh tracker for each test."""
        tracker = UsageTracker()
        yield tracker
        tracker.clear_all()

    def test_record_basic(self, tracker):
        """Test basic record recording."""
        record = UsageRecord.create(
            tenant_id="tenant_1",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
        )
        tracker.record(record)

        records = tracker.get_records("tenant_1")
        assert len(records) == 1
        assert records[0].tenant_id == "tenant_1"

    def test_tenant_isolation(self, tracker):
        """Test that tenant A records cannot appear in tenant B queries."""
        record_a = UsageRecord.create(
            tenant_id="tenant_a",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
        )
        record_b = UsageRecord.create(
            tenant_id="tenant_b",
            layer="L2",
            decision_action=DecisionAction.SEMANTIC_REUSE,
        )
        tracker.record(record_a)
        tracker.record(record_b)

        a_records = tracker.get_records("tenant_a")
        b_records = tracker.get_records("tenant_b")

        assert len(a_records) == 1
        assert len(b_records) == 1
        assert a_records[0].tenant_id == "tenant_a"
        assert b_records[0].tenant_id == "tenant_b"

        # Tenant A should not see Tenant B's records
        assert all(r.tenant_id == "tenant_a" for r in a_records)
        assert all(r.tenant_id == "tenant_b" for r in b_records)

    def test_get_all_tenants(self, tracker):
        """Test getting list of all tenants."""
        tracker.record(UsageRecord.create("tenant_x", "L1", DecisionAction.EXACT_REUSE))
        tracker.record(UsageRecord.create("tenant_y", "L2", DecisionAction.SEMANTIC_REUSE))
        tracker.record(UsageRecord.create("tenant_x", "L3", DecisionAction.FULL_LLM_CALL))

        tenants = tracker.get_all_tenants()
        assert set(tenants) == {"tenant_x", "tenant_y"}

    def test_clear_tenant(self, tracker):
        """Test clearing records for a specific tenant."""
        tracker.record(UsageRecord.create("tenant_a", "L1", DecisionAction.EXACT_REUSE))
        tracker.record(UsageRecord.create("tenant_b", "L2", DecisionAction.SEMANTIC_REUSE))

        cleared = tracker.clear_tenant("tenant_a")
        assert cleared == 1
        assert len(tracker.get_records("tenant_a")) == 0
        assert len(tracker.get_records("tenant_b")) == 1

    def test_clear_all(self, tracker):
        """Test clearing all records."""
        tracker.record(UsageRecord.create("tenant_a", "L1", DecisionAction.EXACT_REUSE))
        tracker.record(UsageRecord.create("tenant_b", "L2", DecisionAction.SEMANTIC_REUSE))

        cleared = tracker.clear_all()
        assert cleared == 2
        assert len(tracker.get_all_tenants()) == 0

    def test_since_filter(self, tracker):
        """Test filtering records by timestamp."""
        now = datetime.now(timezone.utc)
        old_record = UsageRecord.create(
            tenant_id="tenant_1",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        new_record = UsageRecord.create(
            tenant_id="tenant_1",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            timestamp=now,
        )
        tracker.record(old_record)
        tracker.record(new_record)

        records = tracker.get_records("tenant_1", since=datetime(2023, 1, 1, tzinfo=timezone.utc))
        assert len(records) == 1
        assert records[0].timestamp == now

    def test_limit(self, tracker):
        """Test limiting returned records."""
        for i in range(1500):
            tracker.record(UsageRecord.create(f"tenant_{i % 3}", "L1", DecisionAction.EXACT_REUSE))

        records = tracker.get_records("tenant_0", limit=100)
        assert len(records) == 100

    def test_thread_safety(self, tracker):
        """Test concurrent recording from multiple threads."""
        def record_for_tenant(tenant_id, count):
            for _ in range(count):
                tracker.record(UsageRecord.create(tenant_id, "L1", DecisionAction.EXACT_REUSE))

        threads = [
            threading.Thread(target=record_for_tenant, args=(f"tenant_{i}", 100))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All tenants should have their records
        for i in range(5):
            assert len(tracker.get_records(f"tenant_{i}")) == 100

    def test_max_records_trim(self, tracker):
        """Test that old records are trimmed when exceeding max."""
        tracker._max_records_per_tenant = 100
        for i in range(150):
            tracker.record(UsageRecord.create("tenant_1", "L1", DecisionAction.EXACT_REUSE))

        records = tracker.get_records("tenant_1")
        # Should have trimmed (kept last 90)
        assert len(records) <= 100


class TestCostCalculator:
    """Tests for CostCalculator centralized cost calculation."""

    @pytest.fixture
    def calculator(self):
        """Create a cost calculator with test pricing."""
        pricing = {
            "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini"),
            "anthropic:claude-3-haiku": ModelPricing(0.25, 1.25, "anthropic", "claude-3-haiku"),
        }
        cost_model = CostModel(pricing)
        return CostCalculator(cost_model)

    def test_calculate_known_model(self, calculator):
        """Test cost calculation for known model."""
        cost = calculator.calculate("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75)  # 0.15 + 0.60

    def test_calculate_unknown_model_returns_none(self, calculator):
        """Test cost calculation returns None for unknown model."""
        cost = calculator.calculate("openai", "unknown-model", 1000, 1000)
        assert cost is None

    def test_calculate_from_usage_dict(self, calculator):
        """Test cost calculation from usage dict."""
        usage = {"prompt_tokens": 500_000, "completion_tokens": 500_000}
        cost = calculator.calculate_from_usage("openai", "gpt-4o-mini", usage)
        assert cost == pytest.approx(0.375)  # (0.15 * 0.5) + (0.60 * 0.5)

    def test_calculate_with_fallback(self, calculator):
        """Test cost calculation with fallback."""
        cost = calculator.calculate_with_fallback(
            "openai", "unknown-model", 1000, 1000, fallback_cost=0.01
        )
        assert cost == 0.01

    def test_different_providers(self, calculator):
        """Test cost calculation for different providers."""
        openai_cost = calculator.calculate("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        anthropic_cost = calculator.calculate("anthropic", "claude-3-haiku", 1_000_000, 1_000_000)

        assert openai_cost == pytest.approx(0.75)
        assert anthropic_cost == pytest.approx(1.50)


class TestSavingsCalculator:
    """Tests for SavingsCalculator avoided usage computation."""

    @pytest.fixture
    def calculator(self):
        """Create a savings calculator."""
        cost_calc = CostCalculator()
        return SavingsCalculator(cost_calc, baseline_latency_ms=2000.0)

    def test_full_cache_hit_savings(self, calculator):
        """Test savings calculation for full cache hit (no LLM call)."""
        savings = calculator.calculate_savings(
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            provider="openai",
            model="gpt-4o-mini",
            baseline_input_tokens=1000,
            baseline_output_tokens=500,
            actual_input_tokens=0,
            actual_output_tokens=0,
            actual_latency_ms=5.0,
        )

        assert savings["avoided_input_tokens"] == 1000
        assert savings["avoided_output_tokens"] == 500
        assert savings["avoided_total_tokens"] == 1500
        assert savings["cost_saved"] > 0
        assert savings["latency_saved"] == pytest.approx(1.995, rel=0.01)  # ~2s saved

    def test_partial_reuse_savings(self, calculator):
        """Test savings for partial cache reuse (some tokens still used)."""
        savings = calculator.calculate_savings(
            layer="L3",
            decision_action=DecisionAction.CONTEXT_REUSE,
            provider="openai",
            model="gpt-4o-mini",
            baseline_input_tokens=1000,
            baseline_output_tokens=500,
            actual_input_tokens=200,  # Only need to send context + query
            actual_output_tokens=500,
            actual_latency_ms=500.0,
        )

        assert savings["avoided_input_tokens"] == 800
        assert savings["avoided_output_tokens"] == 0
        assert savings["avoided_total_tokens"] == 800
        assert savings["cost_saved"] > 0
        assert savings["latency_saved"] == pytest.approx(1.5, rel=0.01)

    def test_no_savings_for_full_call(self, calculator):
        """Test that full LLM call shows no savings."""
        savings = calculator.calculate_savings(
            layer="MISS",
            decision_action=DecisionAction.FULL_LLM_CALL,
            provider="openai",
            model="gpt-4o-mini",
            baseline_input_tokens=1000,
            baseline_output_tokens=500,
            actual_input_tokens=1000,
            actual_output_tokens=500,
            actual_latency_ms=2000.0,
        )

        assert savings["avoided_input_tokens"] == 0
        assert savings["avoided_output_tokens"] == 0
        assert savings["cost_saved"] == 0.0
        assert savings["latency_saved"] == 0.0

    def test_estimate_baseline_tokens(self, calculator):
        """Test baseline token estimation heuristic."""
        input_tokens, output_tokens = calculator.estimate_baseline_tokens(
            query="What is the revenue?",
            context="Q2 revenue was $4.5B...",
        )
        assert input_tokens >= 100  # Minimum prompt overhead
        assert output_tokens == 500  # Default response estimate


class TestPricingModel:
    """Tests for PricingModel with versioning support."""

    @pytest.fixture
    def pricing_model(self):
        """Create a pricing model with test versions."""
        cost_model = CostModel({
            "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini"),
        })
        pm = PricingModel(cost_model, default_version="2024-10")
        pm.register_version(PricingVersion(
            version="2024-01",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="openai:2024-01",
            description="January 2024 pricing",
        ))
        return pm

    def test_get_current_version(self, pricing_model):
        """Test getting current default version."""
        assert pricing_model.get_current_version() == "2024-10"

    def test_set_default_version(self, pricing_model):
        """Test setting default version."""
        pricing_model.set_default_version("2024-01")
        assert pricing_model.get_current_version() == "2024-01"

    def test_set_invalid_version_raises(self, pricing_model):
        """Test setting invalid version raises error."""
        with pytest.raises(ValueError):
            pricing_model.set_default_version("2023-01")

    def test_estimate_cost_with_version(self, pricing_model):
        """Test cost estimation with version tagging."""
        cost = pricing_model.estimate_cost_with_version(
            "openai", "gpt-4o-mini", 1_000_000, 1_000_000, version="2024-10"
        )
        assert cost == pytest.approx(0.75)

    def test_estimate_cost_unknown_version_warns(self, pricing_model, caplog):
        """Test that unknown version logs warning but continues."""
        # The PricingModel doesn't log a warning for unknown versions in current impl
        # It just uses the current pricing. This test verifies that behavior.
        cost = pricing_model.estimate_cost_with_version(
            "openai", "gpt-4o-mini", 1_000_000, 1_000_000, version="2023-01"
        )
        assert cost == pytest.approx(0.75)


class TestGlobalInstances:
    """Tests for global singleton instances."""

    def test_get_usage_tracker_singleton(self):
        """Test global usage tracker is singleton."""
        tracker1 = get_usage_tracker()
        tracker2 = get_usage_tracker()
        assert tracker1 is tracker2

    def test_set_usage_tracker(self):
        """Test setting custom global tracker."""
        custom = UsageTracker()
        set_usage_tracker(custom)
        assert get_usage_tracker() is custom
        # Reset for other tests
        set_usage_tracker(UsageTracker())

    def test_get_cost_calculator_singleton(self):
        """Test global cost calculator is singleton."""
        calc1 = get_cost_calculator()
        calc2 = get_cost_calculator()
        assert calc1 is calc2

    def test_get_savings_calculator_singleton(self):
        """Test global savings calculator is singleton."""
        calc1 = get_savings_calculator()
        calc2 = get_savings_calculator()
        assert calc1 is calc2

    def test_get_pricing_model_singleton(self):
        """Test global pricing model is singleton."""
        pm1 = get_pricing_model()
        pm2 = get_pricing_model()
        assert pm1 is pm2


class TestRecordUsageConvenience:
    """Tests for record_usage convenience function."""

    @pytest.fixture(autouse=True)
    def reset_tracker(self):
        """Reset global tracker before each test."""
        set_usage_tracker(UsageTracker())
        yield
        set_usage_tracker(UsageTracker())

    def test_record_usage_creates_and_records(self):
        """Test record_usage creates record and adds to tracker."""
        record = record_usage(
            tenant_id="tenant_test",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            input_tokens=100,
            output_tokens=200,
        )

        assert record.tenant_id == "tenant_test"
        assert record.input_tokens == 100
        assert record.output_tokens == 200

        tracker = get_usage_tracker()
        records = tracker.get_records("tenant_test")
        assert len(records) == 1
        assert records[0] is record

    def test_record_usage_generates_ids(self):
        """Test record_usage generates request_id and trace_id if not provided."""
        record = record_usage(
            tenant_id="tenant_test",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
        )
        assert record.request_id is not None
        assert record.trace_id is not None
        assert len(record.request_id) > 0
        assert len(record.trace_id) > 0

    def test_record_usage_sets_pricing_version(self):
        """Test record_usage sets pricing_version from global model."""
        pm = get_pricing_model()
        pm.register_version(PricingVersion(
            version="2024-01",
            effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="openai:2024-01",
        ))
        pm.set_default_version("2024-01")

        record = record_usage(
            tenant_id="tenant_test",
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
        )
        assert record.pricing_version == "2024-01"


class TestMetricsIntegration:
    """Tests that accounting records emit correct Prometheus metrics."""

    @pytest.fixture(autouse=True)
    def reset_metrics(self):
        """Reset metrics by creating new tracker."""
        yield

    def test_record_emits_token_metrics(self):
        """Test that recording emits token metrics."""
        tracker = UsageTracker()
        record = UsageRecord(
            request_id="req-1",
            trace_id="trace-1",
            tenant_id="tenant_metrics",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            input_tokens=100,
            output_tokens=200,
            cached_input_tokens=50,
            avoided_input_tokens=50,
            avoided_output_tokens=100,
        )

        tracker.record(record)

        # Check metrics were incremented (using internal _value for testing)
        input_metric = TOKENS_TOTAL.labels(type="input", tenant="tenant_metrics")
        output_metric = TOKENS_TOTAL.labels(type="output", tenant="tenant_metrics")
        cached_metric = TOKENS_TOTAL.labels(type="cached", tenant="tenant_metrics")
        saved_metric = TOKENS_TOTAL.labels(type="saved", tenant="tenant_metrics")

        assert input_metric._value.get() >= 100
        assert output_metric._value.get() >= 200
        assert cached_metric._value.get() >= 50
        assert saved_metric._value.get() >= 150

    def test_record_emits_cost_metrics(self):
        """Test that recording emits cost metrics."""
        tracker = UsageTracker()
        record = UsageRecord(
            request_id="req-2",
            trace_id="trace-2",
            tenant_id="tenant_cost",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            actual_cost=0.01,
            cost_saved=0.005,
        )

        tracker.record(record)

        actual_metric = COST_USD_TOTAL.labels(type="actual", tenant="tenant_cost")
        saved_metric = COST_USD_TOTAL.labels(type="saved", tenant="tenant_cost")

        assert actual_metric._value.get() >= 0.01
        assert saved_metric._value.get() >= 0.005

    def test_record_emits_llm_call_metrics(self):
        """Test that recording emits LLM call metrics."""
        tracker = UsageTracker()

        # Full LLM call
        record_miss = UsageRecord(
            request_id="req-3",
            trace_id="trace-3",
            tenant_id="tenant_llm",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            llm_called=1,
        )
        tracker.record(record_miss)

        # Cache hit (avoided)
        record_hit = UsageRecord(
            request_id="req-4",
            trace_id="trace-4",
            tenant_id="tenant_llm",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            llm_called=0,
        )
        tracker.record(record_hit)

        calls_metric = LLM_CALLS_TOTAL.labels(layer="L1", tenant="tenant_llm")
        avoided_metric = LLM_CALLS_AVOIDED_TOTAL.labels(layer="L1", tenant="tenant_llm")

        assert calls_metric._value.get() >= 1
        assert avoided_metric._value.get() >= 1

    def test_record_emits_embedding_metrics(self):
        """Test that recording emits embedding call metrics."""
        tracker = UsageTracker()

        record = UsageRecord(
            request_id="req-5",
            trace_id="trace-5",
            tenant_id="tenant_emb",
            timestamp=datetime.now(timezone.utc),
            layer="L2",
            decision_action=DecisionAction.SEMANTIC_REUSE,
            embedding_called=1,
        )
        tracker.record(record)

        metric = EMBEDDING_CALLS_TOTAL.labels(layer="L2", tenant="tenant_emb")
        assert metric._value.get() >= 1

    def test_record_emits_retrieval_metrics(self):
        """Test that recording emits retrieval call metrics."""
        tracker = UsageTracker()

        record = UsageRecord(
            request_id="req-6",
            trace_id="trace-6",
            tenant_id="tenant_ret",
            timestamp=datetime.now(timezone.utc),
            layer="L3",
            decision_action=DecisionAction.CONTEXT_REUSE,
            retrieval_called=1,
        )
        tracker.record(record)

        metric = RETRIEVAL_CALLS_TOTAL.labels(layer="L3", tenant="tenant_ret")
        assert metric._value.get() >= 1

    def test_record_emits_latency_saved(self):
        """Test that recording emits latency saved metric."""
        tracker = UsageTracker()

        record = UsageRecord(
            request_id="req-7",
            trace_id="trace-7",
            tenant_id="tenant_lat",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            latency_saved=1.5,
        )
        tracker.record(record)

        # LATENCY_SAVED_SECONDS is a Histogram, check via _sum or observe count
        metric = LATENCY_SAVED_SECONDS.labels(layer="L1", tenant="tenant_lat")
        # Check that observation was recorded by checking the sum
        assert metric._sum.get() >= 1.5


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_usage_record(self):
        """Test recording with zero usage values."""
        tracker = UsageTracker()
        record = UsageRecord.create("tenant_zero", "L1", DecisionAction.EXACT_REUSE)
        # All fields default to 0
        tracker.record(record)

        records = tracker.get_records("tenant_zero")
        assert len(records) == 1

    def test_unknown_usage_source(self):
        """Test recording with unknown usage source."""
        tracker = UsageTracker()
        record = UsageRecord(
            request_id="req-unk",
            trace_id="trace-unk",
            tenant_id="tenant_unk",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            usage_source=UsageSource.UNKNOWN,
            input_tokens=100,
        )
        tracker.record(record)

        records = tracker.get_records("tenant_unk")
        assert records[0].usage_source == UsageSource.UNKNOWN

    def test_partial_provider_usage(self):
        """Test recording when provider only reports partial usage."""
        tracker = UsageTracker()
        record = UsageRecord(
            request_id="req-partial",
            trace_id="trace-partial",
            tenant_id="tenant_partial",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            input_tokens=100,
            output_tokens=0,  # Provider didn't report output
            total_tokens=100,
        )
        tracker.record(record)

        records = tracker.get_records("tenant_partial")
        assert records[0].input_tokens == 100
        assert records[0].output_tokens == 0

    def test_estimate_usage_source(self):
        """Test recording with estimated usage."""
        tracker = UsageTracker()
        record = UsageRecord(
            request_id="req-est",
            trace_id="trace-est",
            tenant_id="tenant_est",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            usage_source=UsageSource.ESTIMATED,
            input_tokens=500,
            output_tokens=500,
            actual_cost=0.001,  # Estimated cost
        )
        tracker.record(record)

        records = tracker.get_records("tenant_est")
        assert records[0].usage_source == UsageSource.ESTIMATED

    def test_different_pricing_versions(self):
        """Test records with different pricing versions."""
        tracker = UsageTracker()

        record_v1 = UsageRecord(
            request_id="req-v1",
            trace_id="trace-v1",
            tenant_id="tenant_ver",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            pricing_version="2024-01",
            actual_cost=0.01,
        )
        tracker.record(record_v1)

        record_v2 = UsageRecord(
            request_id="req-v2",
            trace_id="trace-v2",
            tenant_id="tenant_ver",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            pricing_version="2024-10",
            actual_cost=0.008,
        )
        tracker.record(record_v2)

        records = tracker.get_records("tenant_ver")
        assert len(records) == 2
        assert records[0].pricing_version == "2024-01"
        assert records[1].pricing_version == "2024-10"

    def test_metrics_never_raise(self):
        """Test that metrics recording never raises exceptions."""
        tracker = UsageTracker()

        # Even with empty tenant, should not raise
        record = UsageRecord(
            request_id="req-empty",
            trace_id="trace-empty",
            tenant_id="",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.EXACT_REUSE,
            input_tokens=100,
        )
        tracker.record(record)  # Should not raise

        # Even with large values, should not raise
        record2 = UsageRecord(
            request_id="req-large",
            trace_id="trace-large",
            tenant_id="tenant_large",
            timestamp=datetime.now(timezone.utc),
            layer="L1",
            decision_action=DecisionAction.FULL_LLM_CALL,
            input_tokens=10_000_000,
            output_tokens=10_000_000,
            actual_cost=1000.0,
        )
        tracker.record(record2)  # Should not raise


class TestCostModelPricingVersion:
    """Tests for CostModel pricing version support."""

    def test_add_historical_version(self):
        """Test adding a historical pricing version."""
        cost_model = CostModel(allow_runtime_updates=True)
        version = CostPricingVersion(
            version="2024.01",
            effective_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="openai:2024.01",
        )
        pricing = ModelPricing(0.10, 0.50, "openai", "gpt-4o-mini", version=version)
        cost_model.add_historical_version(pricing)
        
        history = cost_model.get_version_history("openai", "gpt-4o-mini")
        assert len(history) >= 1
        assert any(p.version and p.version.version == "2024.01" for p in history)

    def test_estimate_cost_with_version_valid(self):
        """Test estimate_cost_with_version with valid version."""
        version = CostPricingVersion(
            version="2024.10",
            effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
            source="openai:2024.10",
        )
        cost_model = CostModel({
            "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini", version=version),
        })
        cost = cost_model.estimate_cost_with_version(
            "openai", "gpt-4o-mini", 1_000_000, 1_000_000, version="2024.10"
        )
        assert cost == pytest.approx(0.75)

    def test_estimate_cost_with_version_unknown_logs_warning(self, caplog):
        """Test estimate_cost_with_version returns None for unknown version."""
        version = CostPricingVersion(
            version="2024.10",
            effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
            source="openai:2024.10",
        )
        cost_model = CostModel({
            "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini", version=version),
        })
        cost = cost_model.estimate_cost_with_version(
            "openai", "gpt-4o-mini", 1_000_000, 1_000_000, version="2023.01"
        )
        # Returns None when version not found
        assert cost is None

    def test_global_estimate_cost_with_version(self):
        """Test global convenience function via CostModel."""
        version = CostPricingVersion(
            version="2024.10",
            effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
            source="openai:2024.10",
        )
        cost_model = CostModel({
            "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini", version=version),
        })
        cost = cost_model.estimate_cost_with_version("openai", "gpt-4o-mini", 1_000_000, 1_000_000, "2024.10")
        assert cost == pytest.approx(0.75)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])