# ADR-013: Token and Cost Accounting Foundation

**Status**: Accepted  
**Date**: 2025-10-06  
**Author**: Architect Agent  

## Context

ICO-Cache Phase 3A.5 requires comprehensive token usage tracking, cost calculation, and savings measurement across all cache layers (L0a-L9). The system must:

1. **Measure tokens saved** — Input/output tokens avoided via cache hits
2. **Measure cost saved** — USD cost avoided via cache hits  
3. **Measure latency saved** — Time avoided by skipping LLM calls
4. **Support multi-tenancy** — Complete tenant isolation in accounting records
5. **Support provider neutrality** — Extract tokens from OpenAI, Anthropic, Google, etc. responses
6. **Support pricing versioning** — Historical reproducibility for cost audits
7. **Emit observability** — Prometheus metrics, OpenTelemetry traces, structured logs
8. **Prevent security issues** — No secrets in telemetry, no metric injection, rate limiting

The existing codebase has partial implementations spread across multiple files with inconsistent designs.

## Decision

We establish the following canonical accounting architecture:

### 1. Canonical UsageRecord (accounting.py)

Single immutable record type for all accounting:

```python
@dataclass(frozen=True)
class UsageRecord:
    # Request identity
    request_id: str
    trace_id: str
    tenant_id: str
    timestamp: float
    
    # Layer and decision
    layer: str              # "L0a" | "L0b" | "L1" | "L2" | "L3" | "L4-L9" | "RAG_FALLBACK" | "NONE"
    decision_action: str    # "EXACT_REUSE" | "SEMANTIC_REUSE" | "CONTEXT_REUSE" | "MEMORY_RETRIEVAL" | "RAG_RETRIEVAL" | "PARTIAL_RECOMPUTE" | "FULL_LLM_CALL"
    
    # Token usage (LLM)
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    avoided_input_tokens: int
    avoided_output_tokens: int
    avoided_total_tokens: int
    
    # Embedding usage
    embedding_called: int
    embedding_calls_avoided: int
    embedding_tokens: int
    
    # Retrieval usage
    retrieval_called: int
    retrieval_calls_avoided: int
    retrieval_units: int
    
    # Reranker usage
    reranker_called: int
    reranker_calls_avoided: int
    
    # Cost (USD)
    estimated_cost_usd: float
    actual_cost_usd: float
    tokens_saved: int
    cost_saved_usd: float
    
    # Latency
    latency_saved_s: float
    latency_ms: float
    
    # Model info
    model: str
    model_fingerprint: str
    provider: str
    currency: str
    pricing_version: str
    
    # Status
    success: bool
    error: str
    
    # Metadata (scrubbed)
    metadata: Dict[str, Any]
    
    # Source
    usage_source: str  # "provider" | "estimated" | "litellm" | "unknown"
```

**Validation**: Non-negative tokens, required tenant_id, immutable after creation.

### 2. Provider-Neutral Token Extraction (provider_adapters.py)

Abstract `ProviderTokenAdapter` with concrete implementations per provider:

| Provider | Adapter | Cached Tokens Support |
|----------|---------|----------------------|
| OpenAI | `OpenAIAdapter` | ✅ prompt_tokens_details.cached_tokens |
| Anthropic | `AnthropicAdapter` | ✅ cache_read_input_tokens |
| Google/Gemini | `GoogleAdapter` | ✅ cachedContentTokenCount (Vertex AI) |
| Together AI | `TogetherAdapter` | ❌ |
| Fireworks | `FireworksAdapter` | ❌ |
| Groq | `GroqAdapter` | ✅ x_groq.cached_tokens |
| Cohere | `CohereAdapter` | ❌ |
| Ollama | `OllamaAdapter` | ❌ |
| LiteLLM | `LiteLLMAdapter` | Delegates to underlying |

**Registry**: `ProviderAdapterRegistry` with prefix matching (`openai/gpt-4o` → `openai`) and fallback to `EstimationAdapter`.

### 3. Cost Model with Versioning (cost_model.py)

```python
@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million: float
    output_usd_per_million: float
    provider: str
    model: str

@dataclass(frozen=True)
class PricingVersion:
    version: str
    effective_date: datetime
    source: str
    description: str

class CostModel:
    def estimate_cost(provider, model, input_tokens, output_tokens) -> Optional[float]
    def estimate_cost_with_version(provider, model, input_tokens, output_tokens, version) -> Optional[float]
    def register_model(ModelPricing)
    def register_version(PricingVersion)
    def get_all_models() -> Dict[str, ModelPricing]
    def get_all_versions() -> Dict[str, PricingVersion]
```

**Default pricing**: October 2024 rates for all major providers. Local models (Ollama) = $0.

### 4. Savings Calculation (accounting.py → SavingsCalculator)

```python
class SavingsCalculator:
    def __init__(self, cost_calculator: CostCalculator, baseline_latency_ms: float = 2000.0):
        ...
    
    def calculate_savings(
        layer: str,
        decision_action: DecisionAction,
        provider: str,
        model: str,
        baseline_input_tokens: int,
        baseline_output_tokens: int,
        actual_input_tokens: int,
        actual_output_tokens: int,
        actual_latency_ms: float,
    ) -> SavingsResult:
        """Returns avoided_input, avoided_output, avoided_total, cost_saved, latency_saved"""
    
    def calculate_l0b_savings(embedding_model: str, text_length: int) -> SavingsResult:
        """Embedding-specific: avoids 1 embedding call + tokens"""
    
    def estimate_baseline_tokens(query: str, context: str) -> Tuple[int, int]:
        """Heuristic: min 100 input tokens, 500 output tokens"""
```

### 5. Tenant-Isolated Recording (accounting.py → UsageTracker + AccountingManager)

```python
class UsageTracker:
    def record(record: UsageRecord) -> None
    def get_records(tenant_id: str, since: Optional[datetime], limit: int) -> List[UsageRecord]
    def get_all_tenants() -> List[str]
    def clear_tenant(tenant_id: str) -> int
    def clear_all() -> int

class AccountingRateLimiter:
    def __init__(max_events_per_minute: int = 10000, burst_allowance: int = 1000):
        """Token bucket per tenant"""
    def allow(tenant_id: str) -> bool

class AccountingManager:
    def __init__(rate_limiter: AccountingRateLimiter, enable_rate_limiting: bool = True):
        ...
    def record_usage(...) -> Optional[UsageRecord]:  # Returns None if rate limited
    def register_handler(handler: Callable[[UsageRecord], None]) -> None
```

**Global singletons**: `get_usage_tracker()`, `get_cost_calculator()`, `get_savings_calculator()`, `get_pricing_model()`, `get_accounting_manager()`

### 6. Security: Metadata Scrubbing

```python
def _scrub_metadata(metadata: Optional[Dict]) -> Dict:
    """Redact secrets from metadata before recording.
    
    Redacted patterns: api_key, apikey, api-key, authorization, bearer, 
    access_token, refresh_token, client_secret, password, passwd, 
    aws_secret, azure_key, gcp_key, private_key, ssh_key, and nested dicts.
    
    Truncates values > 100 chars.
    """
```

Applied automatically in `UsageRecord.__post_init__` and `AccountingManager.record_usage()`.

### 7. Observability Integration

**Metrics** (metrics.py) - Prometheus counters/histograms:
- `ico_tokens_total` — by type (input/output/cached/saved/embedding/avoided_*) and tenant
- `ico_llm_calls_total` / `ico_llm_calls_avoided_total` — by layer, tenant
- `ico_embedding_calls_total` / `ico_embedding_calls_avoided_total` — by layer, tenant
- `ico_retrieval_calls_total` / `ico_retrieval_calls_avoided_total` — by layer, tenant
- `ico_cost_usd_total` / `ico_cost_saved_usd_total` — by type, tenant
- `ico_latency_saved_seconds` — by layer, tenant

**Tracing** (tracing.py) - OpenTelemetry spans:
- `cache_lookup.l1|L2|L3` with attributes: cache.layer, cache.hit, tenant_id, latency_ms
- `rag_fallback` with attributes: cache.layer=RAG_FALLBACK, cache.hit=false

**Logging** (logging.py) - Structured JSON via structlog.

### 8. Component Boundaries (Enforced)

| Component | Owns | Does NOT Own |
|-----------|------|--------------|
| DecisionEngine | Reuse decisions, confidence, hard gates | Cost calc, token extraction, metrics |
| CacheEngine | Cache ops, single-flight, embedding cache | Reuse decisions, pricing logic |
| Accounting | UsageRecord, savings, cost calc, recording | Cache ops, reuse decisions |
| Telemetry | Metric emission, tracing, logging | Business logic |
| Pricing | ModelPricing, CostModel, versioning | Everything else |
| Provider Adapters | Token extraction, model fingerprinting | Cost calculation, recording |

**No circular dependencies**: Accounting → Pricing → (none), Telemetry → (none), CacheEngine → Accounting/Telemetry (recording only), DecisionEngine → CacheEngine (read-only layer access).

## Consequences

### Positive
- **Single source of truth** for token/cost accounting
- **Provider agnostic** — new providers only need adapter
- **Historically reproducible** — pricing versions for audit
- **Tenant isolated** — no cross-tenant data leakage
- **Secure by default** — metadata scrubbing, validation, rate limiting
- **Extensible** — new layers (L4-L9) only need new enum values in UsageRecord
- **Observable** — rich Prometheus metrics for dashboards/alerting

### Negative
- **Implementation gap** — Current code has partial/inconsistent implementation
- **Test failures** — Existing tests expect different API than implemented
- **Migration needed** — CacheEngine must be updated to use new accounting API
- **Complexity** — More components than minimal implementation

### Tradeoffs
- **In-memory tracking** (UsageTracker) vs. persistent TSDB — Chosen for simplicity; production should add persistence layer
- **Heuristic baseline** (SavingsCalculator.estimate_baseline_tokens) vs. actual baseline — Chosen for practicality; can be refined per-agent
- **Global singletons** vs. dependency injection — Chosen for ergonomics; can be overridden for testing

## Implementation Plan

1. **Complete accounting.py** — Add `UsageTracker`, `CostCalculator`, `SavingsCalculator`, `PricingModel`, `AccountingManager`, `AccountingRateLimiter`, `_scrub_metadata()`, global singletons, `UsageRecord.create()`, validation
2. **Fix CacheEngine imports** — Use `ProviderAdapterRegistry` from provider_adapters, remove non-existent imports
3. **Integrate SavingsCalculator** — Use in `_record_cache_hit_savings()` and L0b embedding cache
4. **Emit UsageRecord** — From CacheEngine on every decision (hit/miss)
5. **Export metrics objects** — Add Counter/Histogram to `metrics.__all__`
6. **Run all tests** — Verify `test_accounting.py` and `test_accounting_security.py` pass