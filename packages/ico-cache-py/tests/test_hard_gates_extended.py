"""
test_hard_gates_extended.py — P0 tests for extended hard gate logic.

Tests cover:
- CRITICAL_FIELDS always block regardless of GateMode
- STRICT mode blocks on any field mismatch
- BALANCED mode allows fuzzy fields with confidence penalty
- MetadataSchema fuzzy field declaration
- Backward compatibility with simple hard_gate
"""

from ico_cache.core.metadata_guard import (
    MetadataField,
    MetadataSchema,
    GateMode,
    hard_gate,
    hard_gate_simple,
    CRITICAL_FIELDS,
)
from ico_cache.core.decision_engine import ReusePolicy


class TestHardGateExtended:
    """Tests for extended hard_gate function."""

    def test_critical_fields_always_block_strict(self):
        """CRITICAL_FIELDS should block even in STRICT mode (which is default)."""
        incoming = {"tenant_id": "tenant_a", "entity": "MSFT", "topic": "revenue"}
        cached = {"tenant_id": "tenant_b", "entity": "MSFT", "topic": "revenue"}  # Different tenant

        # tenant_id is CRITICAL for L1
        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.STRICT
        )
        assert allowed is False
        assert "tenant_id" in failed

    def test_critical_fields_always_block_balanced(self):
        """CRITICAL_FIELDS should block even in BALANCED mode."""
        incoming = {"tenant_id": "tenant_a", "entity": "MSFT", "topic": "revenue"}
        cached = {"tenant_id": "tenant_b", "entity": "MSFT", "topic": "revenue"}

        # tenant_id is CRITICAL for L1
        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.BALANCED
        )
        assert allowed is False
        assert "tenant_id" in failed

    def test_strict_mode_blocks_on_any_mismatch(self):
        """STRICT mode should block on any field mismatch."""
        incoming = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}
        cached = {"entity": "MSFT", "quarter": "Q1", "topic": "margins"}  # Different topic

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.STRICT
        )
        assert allowed is False
        assert "topic" in failed

    def test_balanced_mode_allows_fuzzy_fields(self):
        """BALANCED mode should allow mismatches on fuzzy fields (non-critical)."""
        # Use a layer where topic is not critical, or no layer
        incoming = {"entity": "MSFT", "topic": "revenue", "custom_field": "value1"}
        cached = {"entity": "MSFT", "topic": "margins", "custom_field": "value2"}

        # topic is fuzzy in BALANCED mode, entity is same
        allowed, passed, failed = hard_gate(
            incoming,
            cached,
            layer="L4",  # L4 doesn't have topic as critical
            mode=GateMode.BALANCED,
            fuzzy_fields=["topic", "custom_field"],
        )
        assert allowed is True
        assert any("topic" in p and "(fuzzy)" in p for p in passed)
        assert any("custom_field" in p and "(fuzzy)" in p for p in passed)

    def test_balanced_mode_blocks_non_fuzzy(self):
        """BALANCED mode should block on non-fuzzy field mismatches."""
        incoming = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}
        cached = {"entity": "MSFT", "quarter": "Q2", "topic": "revenue"}  # Different quarter

        allowed, passed, failed = hard_gate(
            incoming,
            cached,
            layer="L1",
            mode=GateMode.BALANCED,
            fuzzy_fields=["topic"],  # quarter not fuzzy
        )
        assert allowed is False
        assert "quarter" in failed

    def test_schema_fuzzy_fields_respected(self):
        """MetadataSchema fuzzy fields should be respected in BALANCED mode."""
        schema = MetadataSchema(
            fields=[
                MetadataField(name="entity", required_in_gate=True),
                MetadataField(name="custom_field", required_in_gate=True, fuzzy=True),
            ]
        )

        incoming = {"entity": "MSFT", "custom_field": "value1"}
        cached = {"entity": "MSFT", "custom_field": "value2"}

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L4", mode=GateMode.BALANCED, schema=schema
        )
        assert allowed is True
        assert any("custom_field" in p and "(fuzzy)" in p for p in passed)

    def test_schema_non_fuzzy_blocks_in_balanced(self):
        """Non-fuzzy fields in schema should block in BALANCED mode."""
        schema = MetadataSchema(
            fields=[
                MetadataField(name="entity", required_in_gate=True),
                MetadataField(name="quarter", required_in_gate=True),
                MetadataField(name="topic", required_in_gate=True, fuzzy=True),
            ]
        )

        incoming = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}
        cached = {"entity": "AAPL", "quarter": "Q1", "topic": "revenue"}  # Different entity

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.BALANCED, schema=schema
        )
        assert allowed is False
        assert "entity" in failed

    def test_none_values_always_pass(self):
        """None values should always pass the gate."""
        incoming = {"entity": "MSFT", "quarter": "Q1"}
        cached = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}  # topic only in cached

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.STRICT
        )
        assert allowed is True
        assert "topic" in passed

    def test_empty_vs_none_context_hash(self):
        """Empty context hash vs None should be handled correctly."""
        incoming = {"context_hash": "empty"}
        cached = {"context_hash": "abc123"}

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.STRICT
        )
        assert allowed is False
        assert "context_hash" in failed


class TestHardGateSimple:
    """Tests for backward-compatible hard_gate_simple."""

    def test_simple_gate_allows_match(self):
        """Simple gate should allow when all fields match."""
        meta1 = {"entity": "MSFT", "quarter": "Q1"}
        meta2 = {"entity": "MSFT", "quarter": "Q1"}

        assert hard_gate_simple(meta1, meta2, filter_keys=["entity", "quarter"]) is True

    def test_simple_gate_blocks_mismatch(self):
        """Simple gate should block when fields differ."""
        meta1 = {"entity": "MSFT", "quarter": "Q1"}
        meta2 = {"entity": "MSFT", "quarter": "Q2"}

        assert hard_gate_simple(meta1, meta2, filter_keys=["entity", "quarter"]) is False

    def test_simple_gate_allows_none(self):
        """Simple gate should allow when one side is None."""
        meta1 = {"entity": "MSFT"}
        meta2 = {"entity": "MSFT", "quarter": "Q1"}

        assert hard_gate_simple(meta1, meta2, filter_keys=["entity", "quarter"]) is True

    def test_simple_gate_default_filter_keys(self):
        """Simple gate should use all keys when filter_keys not provided."""
        meta1 = {"entity": "MSFT", "quarter": "Q1", "topic": "revenue"}
        meta2 = {"entity": "MSFT", "quarter": "Q1"}

        assert hard_gate_simple(meta1, meta2) is True


class TestReusePolicyIntegration:
    """Tests for ReusePolicy integration with hard gates."""

    def test_strict_policy_gate_mode(self):
        """STRICT policy should use STRICT gate mode."""
        policy = ReusePolicy.strict()
        assert policy.mode == GateMode.STRICT

    def test_balanced_policy_gate_mode(self):
        """BALANCED policy should use BALANCED gate mode."""
        policy = ReusePolicy.balanced()
        assert policy.mode == GateMode.BALANCED

    def test_policy_fuzzy_fields_used_in_gate(self):
        """Policy fuzzy fields should be passed to hard_gate."""
        policy = ReusePolicy.balanced(fuzzy_fields=["topic", "custom"])

        incoming = {"entity": "MSFT", "topic": "revenue", "custom": "value1"}
        cached = {"entity": "MSFT", "topic": "margins", "custom": "value2"}

        allowed, passed, failed = hard_gate(
            incoming,
            cached,
            layer="L4",  # L4 doesn't have topic as critical
            mode=policy.mode,
            fuzzy_fields=policy.fuzzy_fields,
        )
        assert allowed is True
        assert any("topic" in p and "(fuzzy)" in p for p in passed)
        assert any("custom" in p and "(fuzzy)" in p for p in passed)

    def test_policy_thresholds(self):
        """Policy should have correct thresholds."""
        strict = ReusePolicy.strict()
        balanced = ReusePolicy.balanced()

        assert strict.threshold == 0.95
        assert balanced.threshold == 0.80


class TestCriticalFieldsPerLayer:
    """Tests for CRITICAL_FIELDS configuration per layer."""

    def test_l1_has_required_fields(self):
        """L1 should have all required critical fields."""
        l1_critical = CRITICAL_FIELDS["L1"]
        required = ["tenant_id", "model_fingerprint", "provider", "prompt_version", "entity", "quarter", "topic"]
        for field in required:
            assert field in l1_critical

    def test_l2_has_required_fields(self):
        """L2 should have all required critical fields."""
        l2_critical = CRITICAL_FIELDS["L2"]
        required = ["tenant_id", "model_fingerprint", "embedding_version", "entity", "quarter", "topic", "collection_version"]
        for field in required:
            assert field in l2_critical

    def test_l3_has_context_hash(self):
        """L3 should have context_hash as critical field."""
        assert "context_hash" in CRITICAL_FIELDS["L3"]

    def test_l7_has_tenant_id(self):
        """L7 should have tenant_id as critical field (security fix)."""
        assert "tenant_id" in CRITICAL_FIELDS["L7"]
        assert "project_id" in CRITICAL_FIELDS["L7"]
        assert "commit_sha" in CRITICAL_FIELDS["L7"]

    def test_l8_has_tenant_and_user(self):
        """L8 should have tenant_id and user_id as critical fields."""
        assert "tenant_id" in CRITICAL_FIELDS["L8"]
        assert "user_id" in CRITICAL_FIELDS["L8"]
        assert "session_id" in CRITICAL_FIELDS["L8"]
        assert "consent_version" in CRITICAL_FIELDS["L8"]

    def test_l9_has_tenant_and_user(self):
        """L9 should have tenant_id and user_id as critical fields."""
        assert "tenant_id" in CRITICAL_FIELDS["L9"]
        assert "user_id" in CRITICAL_FIELDS["L9"]
        assert "injected_context_hash" in CRITICAL_FIELDS["L9"]


class TestGateMode:
    """Tests for GateMode enum."""

    def test_gate_mode_values(self):
        """GateMode should only have STRICT and BALANCED (no AGGRESSIVE)."""
        assert GateMode.STRICT == "strict"
        assert GateMode.BALANCED == "balanced"
        assert not hasattr(GateMode, "AGGRESSIVE")

    def test_gate_mode_in_policy(self):
        """GateMode should be used in ReusePolicy."""
        strict_policy = ReusePolicy.strict()
        balanced_policy = ReusePolicy.balanced()

        assert strict_policy.mode == GateMode.STRICT
        assert balanced_policy.mode == GateMode.BALANCED


class TestMultipleFieldMismatches:
    """Tests for multiple field mismatches."""

    def test_multiple_critical_fields_block(self):
        """Multiple critical field mismatches should all be reported."""
        incoming = {"tenant_id": "t1", "entity": "MSFT", "quarter": "Q1"}
        cached = {"tenant_id": "t2", "entity": "AAPL", "quarter": "Q1"}

        allowed, passed, failed = hard_gate(
            incoming, cached, layer="L1", mode=GateMode.STRICT
        )
        assert allowed is False
        assert "tenant_id" in failed
        assert "entity" in failed
        assert "quarter" not in failed  # Same value

    def test_mixed_critical_and_fuzzy_in_balanced(self):
        """Mixed critical and fuzzy mismatches in BALANCED: critical blocks, fuzzy passes."""
        incoming = {"tenant_id": "t1", "entity": "MSFT", "topic": "revenue"}
        cached = {"tenant_id": "t2", "entity": "MSFT", "topic": "margins"}

        allowed, passed, failed = hard_gate(
            incoming,
            cached,
            layer="L1",
            mode=GateMode.BALANCED,
            fuzzy_fields=["topic"],
        )
        assert allowed is False  # Blocked by critical tenant_id
        assert "tenant_id" in failed
        # topic is critical for L1, so it also blocks even though fuzzy
        assert "topic" in failed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])