# Code Review: ICO-Cache Phase 3A.5 Token and Cost Accounting

**Date**: 2025-10-06  
**Reviewer**: Architect Agent  
**Scope**: Accounting architecture, component boundaries, integration

---

## Executive Summary

The accounting implementation has **significant architectural inconsistencies** between:
1. **What tests expect** (`test_accounting.py`, `test_accounting_security.py`)
2. **What decision_engine.py uses** (TokenUsage, LayerAttribution, UsageRecord with different schema)
3. **What cache_engine.py imports** (non-existent: TokenUsage, LayerAttribution, ProviderTokenAdapter, SavingsCalculator, create_usage_record, create_layer_attribution)
4. **What accounting.py implements** (UsageRecord with RAG-focused fields, AccountingContext, AccountingCollector)

**Result**: All accounting tests fail to collect; CacheEngine and DecisionEngine cannot import their dependencies.

---

## Critical Issues

### 1. Missing Types in accounting.py (Blocking)

**File**: `packages/ico-cache-py/src/ico_cache/telemetry/accounting.py`

The following types are imported but **do not exist**:

| Type | Imported By | Expected By Tests |
|------|-------------|-------------------|
| `TokenUsage` | decision_engine.py (line 18, 179, 180, 643, 644, 673, 684, 732, 819), cache_engine.py (line 31) | test_accounting.py (via UsageRecord fields) |
| `LayerAttribution` | decision_engine.py (line 18), cache_engine.py (line 31) | — |
| `ProviderTokenAdapter` | cache_engine.py (line 31, 169) | test_accounting.py (as `ProviderTokenAdapter` ABC) |
| `SavingsCalculator` | cache_engine.py (line 31, 170, 562, 580) | test_accounting.py (class) |
| `create_usage_record` | cache_engine.py (line 31) | — |
| `create_layer_attribution` | cache_engine.py (line 31) | — |
| `UsageTracker` | — | test_accounting.py (class) |
| `CostCalculator` | — | test_accounting.py (class) |
| `PricingModel` | — | test_accounting.py (class) |
| `AccountingManager` | — | test_accounting_security.py (class) |
| `AccountingRateLimiter` | — | test_accounting_security.py (class) |
| `_scrub_metadata` | — | test_accounting_security.py (function) |
| Global singletons | — | test_accounting.py (`get_usage_tracker`, etc.) |

### 2. Duplicate/Conflicting UsageRecord Schemas

**Current accounting.py** (lines 89-256):
```python
@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    tenant_id: str
    layer: CacheLayer          # Enum
    decision_action: DecisionAction  # Enum
    timestamp: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    saved_tokens: int = 0
    # ... 50+ more RAG-specific fields
```

**Expected by tests** (`test_accounting.py` lines 61-98):
```python
UsageRecord(
    request_id="req-123",
    trace_id="trace-456",           # ← MISSING
    tenant_id="tenant_b",
    timestamp=datetime(...),
    layer="L2",                     # ← STRING, not Enum
    decision_action=DecisionAction.SEMANTIC_REUSE,
    cache_hit=1,                    # ← MISSING
    cache_miss=0,                   # ← MISSING
    llm_called=0,                   # ← MISSING
    embedding_called=1,             # ← MISSING
    retrieval_called=0,             # ← MISSING
    reranker_called=0,              # ← MISSING
    input_tokens=100,
    output_tokens=200,
    total_tokens=300,               # ← MISSING
    cached_input_tokens=50,         # ← MISSING
    avoided_input_tokens=50,        # ← MISSING
    avoided_output_tokens=100,      # ← MISSING
    avoided_total_tokens=150,       # ← MISSING
    embedding_tokens=100,           # ← MISSING
    retrieval_units=0,              # ← MISSING
    estimated_cost=0.001,           # ← MISSING
    actual_cost=0.0005,             # ← MISSING
    tokens_saved=150,               # ← MISSING
    cost_saved=0.0005,              # ← MISSING
    latency_saved=1.5,              # ← MISSING
    latency_ms=50.0,                # ← MISSING
    model="gpt-4o-mini",            # ← MISSING
    model_fingerprint="fp-abc123",  # ← MISSING
    provider="openai",              # ← MISSING
    currency="USD",                 # ← MISSING
    pricing_version="2024-10",      # ← MISSING
    success=True,                   # ← MISSING
    error="",                       # ← MISSING
    metadata={"key": "value"},      # ← MISSING
    usage_source=UsageSource.PROVIDER,  # ← MISSING (UsageSource enum)
)
```

**Expected by decision_engine.py** (lines 179-182, 237, 584):
```python
@dataclass
class LayerEvaluation:
    actual_tokens: TokenUsage = field(default_factory=TokenUsage)
    avoided_tokens: TokenUsage = field(default_factory=TokenUsage)
    actual_cost_usd: float = 0.0
    avoided_cost_usd: float = 0.0
    usage_record: Optional[UsageRecord] = None
```

### 3. CacheEngine Uses Non-Existent SavingsCalculator

**File**: `packages/ico-cache-py/src/ico_cache/core/cache_engine.py`

```python
# Line 169-170: Instantiates non-existent classes
self._token_adapter = ProviderTokenAdapter()  # ABC - cannot instantiate!
self._savings_calculator = SavingsCalculator(self.cost_model)  # Doesn't exist!

# Lines 562-568, 580-587: Uses non-existent method
savings = self._savings_calculator.calculate_l0b_savings(
    embedding_model=model_fingerprint,
    text_length=len(text),
)
record_tokens("saved", savings["avoided_tokens"].total, ...)  # Expected dict with UsageInfo
```

### 4. ProviderTokenAdapter is Abstract (Cannot Instantiate)

**File**: `packages/ico-cache-py/src/ico_cache/telemetry/provider_adapters.py`

```python
class ProviderTokenAdapter(ABC):  # Abstract!
    @abstractmethod
    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo: ...
    
# CacheEngine line 169 tries: self._token_adapter = ProviderTokenAdapter()
# TypeError: Can't instantiate abstract class
```

**Correct usage**: `ProviderAdapterRegistry.get_adapter(provider).extract_usage(response)`

### 5. DecisionEngine Imports Non-Existent Types

**File**: `packages/ico-cache-py/src/ico_cache/core/decision_engine.py`

```python
# Line 18-19
from ..telemetry.accounting import TokenUsage
from ..telemetry.accounting import TokenUsage, LayerAttribution, UsageRecord
```

These imports fail because the types don't exist in accounting.py.

### 6. Metrics Objects Not Exported

**File**: `packages/ico-cache-py/src/ico_cache/telemetry/metrics.py`

Tests access metrics directly:
```python
from ico_cache.telemetry.metrics import (
    TOKENS_TOTAL, LLM_CALLS_TOTAL, LLM_CALLS_AVOIDED_TOTAL,
    EMBEDDING_CALLS_TOTAL, EMBEDDING_CALLS_AVOIDED_TOTAL,
    RETRIEVAL_CALLS_TOTAL, RETRIEVAL_CALLS_AVOIDED_TOTAL,
    COST_USD_TOTAL, COST_SAVED_USD_TOTAL, LATENCY_SAVED_SECONDS,
)
```

But `__all__` only exports helper functions, not the Counter/Histogram objects.

---

## Boundary Violations

### DecisionEngine Does Cost Calculation (Should Not)

**File**: `decision_engine.py` lines 179-182, 237, 584

DecisionEngine's `LayerEvaluation` and `ReuseDecision` contain:
- `actual_tokens: TokenUsage`
- `avoided_tokens: TokenUsage` 
- `actual_cost_usd: float`
- `avoided_cost_usd: float`
- `usage_record: Optional[UsageRecord]`

**Violation**: DecisionEngine should only make reuse decisions. Cost/token accounting belongs in CacheEngine/Accounting layer.

### CacheEngine Mixes Business Logic with Cache Operations

**File**: `cache_engine.py` lines 866-923 (`_record_cache_hit_savings`, `_record_generation_usage`)

```python
def _record_cache_hit_savings(self, response, tenant_id, model, provider):
    # Estimates tokens from response length (rough heuristic)
    estimated_output_tokens = max(len(answer) // 4, 1)
    estimated_input_tokens = estimated_output_tokens * 3
    # Records to metrics directly
    record_tokens("cached", ..., tenant_id)
    record_tokens("saved", ..., tenant_id)
    cost = self.cost_model.estimate_cost(...)
    record_cost("saved", cost, tenant_id)
```

**Violation**: CacheEngine should delegate to Accounting layer (SavingsCalculator, UsageTracker) rather than computing estimates inline.

### Telemetry Layer Has Business Logic (Metrics Helper Functions)

**File**: `metrics.py` lines 200-361

Helper functions like `record_llm_call()`, `record_embedding_call_avoided()` contain business logic about what to record. While they don't raise, they encode accounting semantics in the telemetry layer.

**Better**: Accounting layer calls low-level metric primitives; telemetry only defines metric objects.

---

## Circular Dependency Risk

```
cache_engine.py → imports from accounting.py (TokenUsage, LayerAttribution, ...)
decision_engine.py → imports from accounting.py (TokenUsage, LayerAttribution, UsageRecord)
accounting.py → (currently) no imports from core/
```

**Risk**: If accounting.py ever imports from core/ (e.g., for CacheLayer enum), circular dependency emerges.

**Current state**: No actual cycle, but fragile.

---

## Security Gaps

### 1. No Metadata Scrubbing

**Missing**: `_scrub_metadata()` function (expected by `test_accounting_security.py`)

Without this, API keys, passwords, cloud secrets can leak into telemetry metadata.

### 2. No Rate Limiting on Accounting Events

**Missing**: `AccountingRateLimiter`, `AccountingManager.enable_rate_limiting`

A malicious tenant could DoS the accounting system by generating millions of events.

### 3. No UsageRecord Validation

**Current**: `UsageRecord` (accounting.py) is frozen but has no validation
**Expected**: Non-negative tokens, required tenant_id, immutable after creation (test_accounting_security.py lines 172-313)

### 4. CostModel Allows Runtime Pricing Mutation

**File**: `cost_model.py` - `register_model()` allows adding/overriding pricing at runtime

**Expected**: `allow_runtime_updates=False` by default, frozen `MappingProxyType` for internal pricing dict (test_accounting_security.py lines 494-522)

---

## Test Coverage Gaps

| Test File | Status | Issues |
|-----------|--------|--------|
| `test_accounting.py` | **Cannot collect** | Imports missing types |
| `test_accounting_security.py` | **Cannot collect** | Imports missing types |
| `test_cache_engine.py` | Passes | But uses broken accounting internally |
| `test_decision_engine.py` | Passes | But has broken imports (not exercised) |

---

## Recommendations (Priority Order)

### P0 - Blocking (Must Fix Before Any Tests Pass)

1. **Complete accounting.py implementation** matching test expectations:
   - `TokenUsage` dataclass (input_tokens, output_tokens, total_tokens, cached_input_tokens, reasoning_tokens)
   - `LayerAttribution` dataclass 
   - `UsageRecord` with all test-expected fields + validation
   - `UsageSource` enum
   - `UsageTracker` class with tenant isolation
   - `CostCalculator` class
   - `SavingsCalculator` class with `calculate_savings()` and `calculate_l0b_savings()`
   - `PricingModel` class with versioning
   - `AccountingRateLimiter` (token bucket per tenant)
   - `AccountingManager` with `_scrub_metadata()`, rate limiting, handler registration
   - Global singletons: `get_usage_tracker()`, `get_cost_calculator()`, `get_savings_calculator()`, `get_pricing_model()`, `get_accounting_manager()`, `set_*()` variants
   - `record_usage()` convenience function

2. **Fix cache_engine.py imports**:
   - Remove: `TokenUsage`, `LayerAttribution`, `ProviderTokenAdapter`, `SavingsCalculator`, `create_usage_record`, `create_layer_attribution`
   - Add: `from ..telemetry.provider_adapters import ProviderAdapterRegistry, get_provider_registry`
   - Use: `get_provider_registry().extract_usage(provider, response)`
   - Instantiate: `SavingsCalculator` from accounting (once implemented)

3. **Fix decision_engine.py imports**:
   - Import `TokenUsage`, `LayerAttribution`, `UsageRecord` from accounting (once implemented)
   - Or: Define `TokenUsage` locally if DecisionEngine should own it

4. **Export metrics objects** in `metrics.py` `__all__`

### P1 - Architecture Cleanup

5. **Move cost/token fields out of DecisionEngine** → Accounting layer only
6. **Delegate savings calculation** from CacheEngine → SavingsCalculator
7. **Emit UsageRecord** from CacheEngine on every decision (hit/miss/generation)
8. **Add UsageRecord validation** in `__post_init__`
9. **Add metadata scrubbing** in AccountingManager.record_usage()

### P2 - Production Hardening

10. **Persist UsageTracker** to TSDB (InfluxDB/TimescaleDB) or Kafka
11. **Add cost model integrity hash** (test_accounting_security.py line 499)
12. **Freeze CostModel pricing** by default (MappingProxyType)
13. **Add pricing version audit trail** to UsageRecord

---

## Verification Checklist

After fixes, verify:

- [ ] `python -m pytest packages/ico-cache-py/tests/test_accounting.py -v` → all pass
- [ ] `python -m pytest packages/ico-cache-py/tests/test_accounting_security.py -v` → all pass
- [ ] `python -m pytest packages/ico-cache-py/tests/test_cache_engine.py -v` → all pass
- [ ] `python -m pytest packages/ico-cache-py/tests/test_decision_engine.py -v` → all pass
- [ ] `python -c "from ico_cache.core.cache_engine import CacheEngine"` → no import errors
- [ ] `python -c "from ico_cache.core.decision_engine import DecisionEngine"` → no import errors
- [ ] No circular imports in `packages/ico-cache-py/src/ico_cache/`
- [ ] All 226 existing tests still pass

---

## Files Requiring Changes

| File | Changes Needed |
|------|----------------|
| `accounting.py` | **Major rewrite** - implement all missing types/classes |
| `cache_engine.py` | Fix imports, use ProviderAdapterRegistry, integrate SavingsCalculator |
| `decision_engine.py` | Fix imports, remove cost/token fields from LayerEvaluation/ReuseDecision |
| `metrics.py` | Export Counter/Histogram objects in `__all__` |
| `provider_adapters.py` | Verify UsageInfo matches TokenUsage schema |
| `cost_model.py` | Add `allow_runtime_updates` param, MappingProxyType, integrity_hash |

---

## Architecture Decision

The **test expectations represent the intended architecture**. The current `accounting.py` is a divergent implementation that doesn't match the design agreed upon in tests. 

**Decision**: Align implementation with test expectations (which encode the requirements). The test-defined API is more complete, security-hardened, and production-ready.