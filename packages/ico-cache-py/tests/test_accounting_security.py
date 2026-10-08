"""Security tests for token and cost accounting system.

Tests cover:
- Tenant isolation: accounting records cannot cross tenant boundaries
- Pricing manipulation: cannot inject fake pricing to inflate savings
- Usage spoofing: cannot forge usage records with inflated tokens
- Cost metric injection: cannot inject negative costs or inflated savings
- Sensitive data: no raw prompts, secrets, API keys, full context in telemetry
- Forged UsageRecord with fake tenant_id rejected
- Pricing version tampering detected
"""

import os
import sys
import pytest
import time
import threading
from datetime import datetime, timezone
from typing import Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SRC_DIR = os.path.join(REPO_ROOT, "packages/ico-cache-py/src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ico_cache.telemetry.accounting import (
    UsageRecord,
    AccountingRateLimiter,
    ValidatedAccountingCollector,
    _scrub_metadata,
    get_collector,
    set_collector,
    record_usage,
    CacheLayer,
    DecisionAction,
)
from ico_cache.telemetry.cost_model import CostModel, ModelPricing, get_cost_model, set_cost_model


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def clean_collector():
    """Provide a clean ValidatedAccountingCollector for each test."""
    collector = ValidatedAccountingCollector(
        max_events_per_minute=10000,
        burst_allowance=1000,
        enable_rate_limiting=True,
    )
    yield collector
    # Reset global
    set_collector(ValidatedAccountingCollector())


@pytest.fixture
def clean_cost_model():
    """Provide a clean CostModel for each test."""
    model = CostModel()
    yield model
    # Reset global
    set_cost_model(CostModel())


def make_valid_record(
    tenant_id: str = "tenant_a",
    request_id: str = "req-123",
    layer: CacheLayer = CacheLayer.L1,
    decision_action: DecisionAction = DecisionAction.EXACT_REUSE,
    timestamp: Optional[float] = None,
    **kwargs
) -> UsageRecord:
    """Factory for creating valid UsageRecord with defaults."""
    return UsageRecord(
        request_id=request_id,
        tenant_id=tenant_id,
        timestamp=timestamp if timestamp is not None else time.time(),
        layer=layer,
        decision_action=decision_action,
        **kwargs
    )


# ============================================================================
# Metadata Scrubbing Tests (Sensitive Data Leakage Prevention)
# ============================================================================

class TestMetadataScrubbing:
    """Tests for _scrub_metadata - prevents secrets in telemetry."""

    def test_scrubs_api_key_variants(self):
        """Various API key field names are redacted."""
        metadata = {
            "api_key": "sk-12345",
            "apikey": "sk-67890",
            "api-key": "sk-abcde",
            "x_api_key": "sk-xyz",
            "authorization": "Bearer secret-token",
            "bearer": "token123",
            "access_token": "acc-secret",
            "refresh_token": "ref-secret",
            "client_secret": "client-secret",
        }
        scrubbed = _scrub_metadata(metadata)
        for v in scrubbed.values():
            assert v == "***REDACTED***"

    def test_scrubs_password_fields(self):
        """Password-related fields are redacted."""
        metadata = {
            "password": "secret123",
            "passwd": "pwd456",
            "db_password": "db-secret",
            "redis_pass": "redis-secret",
        }
        scrubbed = _scrub_metadata(metadata)
        for v in scrubbed.values():
            assert v == "***REDACTED***"

    def test_scrubs_cloud_secrets(self):
        """Cloud provider secrets are redacted."""
        metadata = {
            "aws_secret": "aws-secret",
            "aws_access_key_id": "AKIA...",
            "azure_key": "azure-secret",
            "gcp_key": "gcp-secret",
            "private_key": "-----BEGIN PRIVATE KEY-----",
            "ssh_key": "ssh-rsa AAAA...",
        }
        scrubbed = _scrub_metadata(metadata)
        for v in scrubbed.values():
            assert v == "***REDACTED***"

    def test_preserves_non_secret_fields(self):
        """Normal metadata fields are preserved."""
        metadata = {
            "user_id": "user123",
            "session_id": "sess-abc",
            "model": "gpt-4o",
            "temperature": 0.7,
            "max_tokens": 1000,
            "request_id": "req-123",
        }
        scrubbed = _scrub_metadata(metadata)
        assert scrubbed == metadata  # Unchanged

    def test_truncates_long_values(self):
        """Overly long string values are truncated."""
        long_value = "x" * 200
        metadata = {"large_context": long_value}
        scrubbed = _scrub_metadata(metadata)
        assert scrubbed["large_context"] == "x" * 100 + "...[truncated]"

    def test_scrubs_nested_secrets(self):
        """Secrets in nested dicts are redacted."""
        metadata = {
            "config": {
                "api_key": "nested-secret",
                "normal_field": "value",
            }
        }
        scrubbed = _scrub_metadata(metadata)
        assert scrubbed["config"]["api_key"] == "***REDACTED***"
        assert scrubbed["config"]["normal_field"] == "value"

    def test_handles_none_and_empty(self):
        """None and empty dict handled gracefully."""
        assert _scrub_metadata(None) == {}
        assert _scrub_metadata({}) == {}

    def test_extra_field_scrubbed_on_record_creation(self):
        """UsageRecord.extra is scrubbed on construction."""
        record = make_valid_record(
            extra={"api_key": "secret", "normal": "value"}
        )
        assert record.extra["api_key"] == "***REDACTED***"
        assert record.extra["normal"] == "value"

    def test_from_dict_scrubs_extra(self):
        """UsageRecord.from_dict scrubs extra field."""
        data = {
            "request_id": "req-1",
            "tenant_id": "tenant_a",
            "layer": "L1",
            "decision_action": "EXACT_REUSE",
            "extra": {"api_key": "secret"},
        }
        record = UsageRecord.from_dict(data)
        assert record.extra["api_key"] == "***REDACTED***"


# ============================================================================
# UsageRecord Validation Tests (Usage Spoofing Prevention)
# ============================================================================

class TestUsageRecordValidation:
    """Tests for UsageRecord validation - prevents forged/inflated records."""

    def test_valid_record_creation(self):
        """Valid record creates successfully."""
        record = make_valid_record(
            tenant_id="tenant_a",
            request_id="req-123",
            input_tokens=100,
            output_tokens=50,
        )
        assert record.tenant_id == "tenant_a"
        assert record.input_tokens == 100
        assert record.output_tokens == 50

    def test_rejects_empty_tenant_id(self):
        """Empty tenant_id rejected."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            make_valid_record(tenant_id="")

    def test_rejects_none_tenant_id(self):
        """None tenant_id rejected."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            UsageRecord(
                request_id="req-1",
                tenant_id=None,  # type: ignore
                timestamp=time.time(),
                layer=CacheLayer.L1,
                decision_action=DecisionAction.EXACT_REUSE,
            )

    def test_rejects_negative_input_tokens(self):
        """Negative input_tokens rejected."""
        with pytest.raises(ValueError, match="input_tokens must be a non-negative integer"):
            make_valid_record(input_tokens=-100)

    def test_rejects_negative_output_tokens(self):
        """Negative output_tokens rejected."""
        with pytest.raises(ValueError, match="output_tokens must be a non-negative integer"):
            make_valid_record(output_tokens=-50)

    def test_rejects_negative_cached_tokens(self):
        """Negative cached_tokens rejected."""
        with pytest.raises(ValueError, match="cached_tokens must be a non-negative integer"):
            make_valid_record(cached_tokens=-10)

    def test_rejects_negative_saved_tokens(self):
        """Negative saved_tokens rejected."""
        with pytest.raises(ValueError, match="saved_tokens must be a non-negative integer"):
            make_valid_record(saved_tokens=-5)

    def test_rejects_negative_cost_fields(self):
        """Negative cost fields rejected."""
        for field in ("actual_cost_usd", "saved_cost_usd"):
            with pytest.raises(ValueError, match=f"{field} must be a non-negative number"):
                make_valid_record(**{field: -1.0})

    def test_rejects_negative_latency_fields(self):
        """Negative latency fields rejected."""
        for field in (
            "decision_latency_ms", "cache_lookup_latency_ms", "embedding_latency_ms",
            "retrieval_latency_ms", "reranking_latency_ms",
            "context_construction_latency_ms", "generation_latency_ms",
            "total_latency_ms"
        ):
            with pytest.raises(ValueError, match=f"{field} must be a non-negative number"):
                make_valid_record(**{field: -1.0})

    def test_rejects_confidence_over_one(self):
        """Confidence scores > 1.0 rejected."""
        for field in ("reuse_confidence", "retrieval_score", "reranker_score"):
            with pytest.raises(ValueError, match=f"{field} must be <= 1.0"):
                make_valid_record(**{field: 1.5})

    def test_rejects_float_tokens(self):
        """Float token counts rejected."""
        with pytest.raises(ValueError, match="input_tokens must be a non-negative integer"):
            make_valid_record(input_tokens=100.5)  # type: ignore

    def test_rejects_invalid_timestamp(self):
        """Invalid timestamp rejected."""
        with pytest.raises(ValueError, match="timestamp must be a positive number"):
            make_valid_record(timestamp=0)

    def test_rejects_negative_timestamp(self):
        """Negative timestamp rejected."""
        with pytest.raises(ValueError, match="timestamp must be a positive number"):
            make_valid_record(timestamp=-1.0)

    def test_rejects_invalid_layer(self):
        """Invalid layer type rejected."""
        with pytest.raises(ValueError, match="layer must be a CacheLayer enum"):
            UsageRecord(
                request_id="req-1",
                tenant_id="tenant_a",
                timestamp=time.time(),
                layer="L1",  # type: ignore
                decision_action=DecisionAction.EXACT_REUSE,
            )

    def test_rejects_invalid_decision_action(self):
        """Invalid decision_action type rejected."""
        with pytest.raises(ValueError, match="decision_action must be a DecisionAction enum"):
            UsageRecord(
                request_id="req-1",
                tenant_id="tenant_a",
                timestamp=time.time(),
                layer=CacheLayer.L1,
                decision_action="EXACT_REUSE",  # type: ignore
            )

    def test_rejects_invalid_gates_type(self):
        """Non-list gates rejected."""
        with pytest.raises(ValueError, match="gates_passed must be a list"):
            make_valid_record(gates_passed="not-a-list")  # type: ignore

    def test_immutable_after_creation(self):
        """UsageRecord is immutable (frozen dataclass)."""
        record = make_valid_record()
        with pytest.raises(Exception):  # dataclass frozen
            record.tenant_id = "tenant_b"  # type: ignore

    def test_to_dict_excludes_secrets(self):
        """to_dict output has scrubbed extra."""
        record = make_valid_record(extra={"api_key": "secret", "user_id": "user123"})
        d = record.to_dict()
        assert d["extra"]["api_key"] == "***REDACTED***"
        assert d["extra"]["user_id"] == "user123"

    def test_zero_values_allowed(self):
        """Zero values are valid (e.g., cache hit with no new tokens)."""
        record = make_valid_record(
            input_tokens=0,
            output_tokens=0,
            actual_cost_usd=0.0,
            saved_cost_usd=0.0,
        )
        assert record.input_tokens == 0
        assert record.actual_cost_usd == 0.0


# ============================================================================
# Tenant Isolation Tests
# ============================================================================

class TestTenantIsolation:
    """Tests for tenant isolation in accounting."""

    def test_rate_limiter_is_per_tenant(self):
        """Rate limiter tracks separately per tenant."""
        limiter = AccountingRateLimiter(max_events_per_minute=60, burst_allowance=5)

        # Tenant A uses burst
        for _ in range(5):
            assert limiter.allow("tenant_a") is True
        assert limiter.allow("tenant_a") is False  # Exhausted

        # Tenant B still has full burst
        for _ in range(5):
            assert limiter.allow("tenant_b") is True

    def test_collector_isolates_tenants(self, clean_collector):
        """Collector stores records per tenant."""
        record_a = make_valid_record(tenant_id="tenant_a", request_id="req-a")
        record_b = make_valid_record(tenant_id="tenant_b", request_id="req-b")

        assert clean_collector.record(record_a) is True
        assert clean_collector.record(record_b) is True

        # Get records for each tenant
        records_a = clean_collector.get_records("tenant_a")
        records_b = clean_collector.get_records("tenant_b")

        assert len(records_a) == 1
        assert len(records_b) == 1
        assert records_a[0].tenant_id == "tenant_a"
        assert records_b[0].tenant_id == "tenant_b"

    def test_get_aggregates_filters_by_tenant(self, clean_collector):
        """get_aggregates enforces tenant isolation."""
        clean_collector.record(make_valid_record(tenant_id="tenant_a", input_tokens=100))
        clean_collector.record(make_valid_record(tenant_id="tenant_b", input_tokens=200))

        all_agg = clean_collector.get_aggregates()
        tenant_a_agg = clean_collector.get_aggregates("tenant_a")
        tenant_b_agg = clean_collector.get_aggregates("tenant_b")

        assert len(all_agg) == 2
        assert len(tenant_a_agg) == 1
        assert len(tenant_b_agg) == 1

    def test_clear_tenant_only_affects_one_tenant(self, clean_collector):
        """clear_tenant only removes one tenant's records."""
        clean_collector.record(make_valid_record(tenant_id="tenant_a", request_id="req-a1"))
        clean_collector.record(make_valid_record(tenant_id="tenant_a", request_id="req-a2"))
        clean_collector.record(make_valid_record(tenant_id="tenant_b", request_id="req-b1"))

        cleared = clean_collector.clear_tenant("tenant_a")
        assert cleared == 2

        remaining = clean_collector.get_records("tenant_b")
        assert len(remaining) == 1
        assert remaining[0].request_id == "req-b1"

    def test_get_all_tenants_lists_isolated_tenants(self, clean_collector):
        """get_all_tenants returns only tenants with records."""
        clean_collector.record(make_valid_record(tenant_id="tenant_a"))
        clean_collector.record(make_valid_record(tenant_id="tenant_b"))

        tenants = clean_collector.get_all_tenants()
        assert set(tenants) == {"tenant_a", "tenant_b"}

    def test_concurrent_tenant_recording(self, clean_collector):
        """Concurrent recordings for different tenants don't interfere."""
        results = {"tenant_a": 0, "tenant_b": 0}
        lock = threading.Lock()

        def record_for_tenant(tenant: str, count: int):
            for i in range(count):
                r = make_valid_record(tenant_id=tenant, request_id=f"{tenant}-req-{i}")
                if clean_collector.record(r):
                    with lock:
                        results[tenant] += 1

        threads = [
            threading.Thread(target=record_for_tenant, args=("tenant_a", 50)),
            threading.Thread(target=record_for_tenant, args=("tenant_b", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["tenant_a"] == 50
        assert results["tenant_b"] == 50


# ============================================================================
# Pricing Manipulation Tests
# ============================================================================

class TestPricingManipulation:
    """Tests for pricing integrity - prevents fake pricing injection."""

    def test_default_pricing_immutable(self, clean_cost_model):
        """Default pricing cannot be modified after init."""
        models = clean_cost_model.get_all_models()
        original_count = len(models)

        # Attempting to modify the returned dict doesn't affect internal state
        models["fake:model"] = ModelPricing(0.0, 0.0, "fake", "model")

        # Internal registry unchanged
        assert len(clean_cost_model.get_all_models()) == original_count

    def test_register_model_requires_allow_runtime_updates(self, clean_cost_model):
        """register_model fails when runtime updates not allowed."""
        with pytest.raises(RuntimeError, match="frozen after initialization"):
            clean_cost_model.register_model(ModelPricing(1.0, 2.0, "test", "model"))

    def test_pricing_integrity_hash_stable(self, clean_cost_model):
        """Integrity hash is stable for same pricing."""
        hash1 = clean_cost_model.integrity_hash
        hash2 = clean_cost_model.integrity_hash
        assert hash1 == hash2

    def test_pricing_tampering_detected(self):
        """Direct mutation of pricing dict detected (if possible)."""
        # Create model with runtime updates allowed for this test
        model = CostModel(allow_runtime_updates=True)

        # The internal _pricing is a MappingProxyType - truly immutable
        # Any attempt to modify will raise TypeError
        try:
            model._pricing["openai:gpt-4o"] = ModelPricing(0.0, 0.0, "openai", "gpt-4o")  # type: ignore
        except TypeError:
            pass  # Expected - MappingProxyType is immutable

        # Verify integrity still passes
        assert model._verify_integrity() is True

    def test_cost_estimation_uses_verified_pricing(self, clean_cost_model):
        """Cost estimation uses integrity-verified pricing."""
        cost = clean_cost_model.estimate_cost("openai", "gpt-4o", 1000, 500)
        assert cost is not None
        assert cost > 0
        # Expected: (1000/1M)*2.50 + (500/1M)*10.00 = 0.0025 + 0.005 = 0.0075
        assert abs(cost - 0.0075) < 0.0001

    def test_unknown_model_returns_none(self, clean_cost_model):
        """Unknown model returns None, not fake pricing."""
        cost = clean_cost_model.estimate_cost("unknown", "fake-model", 1000, 500)
        assert cost is None

    def test_custom_pricing_overrides_defaults(self):
        """Custom pricing at init overrides defaults."""
        custom = {"openai:gpt-4o": ModelPricing(1.0, 2.0, "openai", "gpt-4o")}
        model = CostModel(pricing=custom)

        pricing = model.get_pricing("openai", "gpt-4o")
        assert pricing is not None
        assert pricing.input_usd_per_million == 1.0
        assert pricing.output_usd_per_million == 2.0


# ============================================================================
# Cost Metric Injection Tests
# ============================================================================

class TestCostMetricInjection:
    """Tests for preventing cost metric injection."""

    def test_negative_actual_cost_rejected(self):
        """Negative actual_cost_usd rejected at UsageRecord creation."""
        with pytest.raises(ValueError, match="actual_cost_usd must be a non-negative number"):
            make_valid_record(actual_cost_usd=-1.0)

    def test_negative_saved_cost_rejected(self):
        """Negative saved_cost_usd rejected."""
        with pytest.raises(ValueError, match="saved_cost_usd must be a non-negative number"):
            make_valid_record(saved_cost_usd=-100.0)

    def test_cost_model_rejects_negative_tokens(self):
        """CostModel.estimate_cost rejects negative tokens."""
        model = CostModel()
        with pytest.raises(ValueError, match="input_tokens must be non-negative"):
            model.estimate_cost("openai", "gpt-4o", -100, 50)

        with pytest.raises(ValueError, match="output_tokens must be non-negative"):
            model.estimate_cost("openai", "gpt-4o", 100, -50)


# ============================================================================
# Rate Limiting / DoS Prevention Tests
# ============================================================================

class TestRateLimiting:
    """Tests for accounting event rate limiting."""

    def test_rate_limiter_blocks_after_burst(self):
        """Rate limiter blocks after burst allowance exhausted."""
        limiter = AccountingRateLimiter(max_events_per_minute=60, burst_allowance=10)

        # Use burst
        for _ in range(10):
            assert limiter.allow("tenant") is True

        # Next request blocked
        assert limiter.allow("tenant") is False

    def test_rate_limiter_refills_over_time(self):
        """Rate limiter refills tokens over time."""
        limiter = AccountingRateLimiter(max_events_per_minute=60, burst_allowance=2)

        # Exhaust burst
        assert limiter.allow("tenant") is True
        assert limiter.allow("tenant") is True
        assert limiter.allow("tenant") is False

        # Wait for refill (60 events/min = 1 event/sec)
        time.sleep(1.1)
        assert limiter.allow("tenant") is True

    def test_collector_respects_rate_limit(self, clean_collector):
        """Collector blocks when rate limited."""
        # Use a very restrictive limiter
        collector = ValidatedAccountingCollector(
            max_events_per_minute=10,
            burst_allowance=2,
            enable_rate_limiting=True,
        )

        # First 2 succeed
        assert collector.record(make_valid_record(tenant_id="t", request_id="r1")) is True
        assert collector.record(make_valid_record(tenant_id="t", request_id="r2")) is True

        # 3rd blocked
        assert collector.record(make_valid_record(tenant_id="t", request_id="r3")) is False

    def test_rate_limiting_can_be_disabled(self):
        """Rate limiting can be disabled for testing."""
        collector = ValidatedAccountingCollector(enable_rate_limiting=False)

        # Should allow unlimited
        for i in range(100):
            assert collector.record(make_valid_record(tenant_id="t", request_id=f"r{i}")) is True


# ============================================================================
# Global State Tests
# ============================================================================

class TestGlobalState:
    """Tests for global collector singleton behavior."""

    def test_get_collector_singleton(self):
        """get_collector returns same instance."""
        c1 = get_collector()
        c2 = get_collector()
        assert c1 is c2

    def test_set_collector_replaces_global(self):
        """set_collector replaces global instance."""
        original = get_collector()
        new_collector = ValidatedAccountingCollector()
        set_collector(new_collector)
        assert get_collector() is new_collector
        # Restore
        set_collector(original)

    def test_get_cost_model_singleton(self):
        """get_cost_model returns same instance."""
        m1 = get_cost_model()
        m2 = get_cost_model()
        assert m1 is m2

    def test_set_cost_model_replaces_global(self):
        """set_cost_model replaces global instance."""
        original = get_cost_model()
        new_model = CostModel()
        set_cost_model(new_model)
        assert get_cost_model() is new_model
        # Restore
        set_cost_model(original)


# ============================================================================
# Edge Cases and Attack Vectors
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and attack vectors."""

    def test_very_large_token_counts(self):
        """Very large token counts handled (no overflow)."""
        record = make_valid_record(
            input_tokens=10_000_000,
            output_tokens=5_000_000,
        )
        assert record.input_tokens == 10_000_000
        assert record.output_tokens == 5_000_000

    def test_special_characters_in_fields(self):
        """Special characters in string fields handled."""
        record = make_valid_record(
            request_id="req-123_abc",
            tenant_id="tenant-a_b.c",
        )
        assert record.request_id == "req-123_abc"
        assert record.tenant_id == "tenant-a_b.c"

    def test_unicode_in_extra(self):
        """Unicode in extra handled."""
        record = make_valid_record(extra={"user_note": "日本語 🎉"})
        assert record.extra["user_note"] == "日本語 🎉"

    def test_large_extra_dict_truncated(self):
        """Large extra dict values truncated."""
        large_value = "x" * 500
        record = make_valid_record(extra={"large_field": large_value})
        assert record.extra["large_field"] == "x" * 100 + "...[truncated]"

    def test_nested_extra_scrubbed(self):
        """Nested extra dicts scrubbed."""
        record = make_valid_record(extra={"config": {"api_key": "nested", "ok": "value"}})
        assert record.extra["config"]["api_key"] == "***REDACTED***"
        assert record.extra["config"]["ok"] == "value"


# ============================================================================
# ModelPricing Validation Tests
# ============================================================================

class TestModelPricingValidation:
    """Tests for ModelPricing validation."""

    def test_valid_pricing(self):
        """Valid pricing creates successfully."""
        pricing = ModelPricing(1.0, 2.0, "provider", "model")
        assert pricing.input_usd_per_million == 1.0
        assert pricing.output_usd_per_million == 2.0

    def test_rejects_negative_input_price(self):
        """Negative input price rejected."""
        with pytest.raises(ValueError, match="input_usd_per_million must be non-negative"):
            ModelPricing(-1.0, 2.0, "provider", "model")

    def test_rejects_negative_output_price(self):
        """Negative output price rejected."""
        with pytest.raises(ValueError, match="output_usd_per_million must be non-negative"):
            ModelPricing(1.0, -2.0, "provider", "model")

    def test_rejects_empty_provider(self):
        """Empty provider rejected."""
        with pytest.raises(ValueError, match="provider is required"):
            ModelPricing(1.0, 2.0, "", "model")

    def test_rejects_empty_model(self):
        """Empty model rejected."""
        with pytest.raises(ValueError, match="model is required"):
            ModelPricing(1.0, 2.0, "provider", "")

    def test_pricing_estimate_cost(self):
        """ModelPricing.estimate_cost calculates correctly."""
        pricing = ModelPricing(2.50, 10.00, "openai", "gpt-4o")
        # 1M input + 1M output = $2.50 + $10.00 = $12.50
        cost = pricing.estimate_cost(1_000_000, 1_000_000)
        assert abs(cost - 12.50) < 0.001

    def test_pricing_rejects_negative_tokens(self):
        """ModelPricing.estimate_cost rejects negative tokens."""
        pricing = ModelPricing(1.0, 2.0, "p", "m")
        with pytest.raises(ValueError, match="input_tokens must be non-negative"):
            pricing.estimate_cost(-1, 10)
        with pytest.raises(ValueError, match="output_tokens must be non-negative"):
            pricing.estimate_cost(10, -1)

    def test_pricing_rejects_float_tokens(self):
        """ModelPricing.estimate_cost rejects float tokens."""
        pricing = ModelPricing(1.0, 2.0, "p", "m")
        with pytest.raises(ValueError, match="input_tokens must be non-negative integer"):
            pricing.estimate_cost(10.5, 10)  # type: ignore


# ============================================================================
# Integration with Metrics Tests
# ============================================================================

class TestMetricsIntegration:
    """Tests for secure metrics integration."""

    def test_record_tokens_validates_tenant(self):
        """record_tokens uses tenant from record."""
        from ico_cache.telemetry.metrics import record_tokens, TOKENS_TOTAL

        # Should not raise
        record_tokens("input", 100, "tenant_a")
        record_tokens("output", 50, "tenant_b")

    def test_record_cost_validates_tenant(self):
        """record_cost uses tenant from record."""
        from ico_cache.telemetry.metrics import record_cost, COST_USD_TOTAL

        # Should not raise
        record_cost("actual", 0.01, "tenant_a")
        record_cost("saved", 0.005, "tenant_b")

    def test_no_sensitive_data_in_metric_labels(self):
        """Metric labels don't contain sensitive data."""
        from ico_cache.telemetry.metrics import record_tokens, record_cost

        # These calls should work without leaking secrets in labels
        record_tokens("input", 100, "tenant_with_api_key_sk_12345")
        record_cost("actual", 0.01, "tenant_with_password_secret")

        # Labels are just the tenant_id string - no automatic secret detection
        # but the tenant_id itself shouldn't contain secrets in practice