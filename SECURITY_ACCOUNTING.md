# Security Accounting: Threat Model and Mitigations

## Overview

This document describes the threat model for the ICO-Cache token and cost accounting system (Phase 3A.5), the security controls implemented, and remaining risks.

---

## Threat Model

### Assets Protected

| Asset | Description | Impact if Compromised |
|-------|-------------|----------------------|
| **Tenant Usage Data** | Token counts, costs per tenant | Billing fraud, competitive intelligence |
| **Pricing Registry** | Model pricing (USD/1M tokens) | Cost manipulation, inflated savings claims |
| **API Keys/Secrets** | Credentials in metadata | Full account takeover |
| **Prompt/Context Data** | User queries, document content | PII leakage, IP theft |
| **Audit Trail** | UsageRecord integrity | Non-repudiation failure |

### Threat Actors

| Actor | Capability | Motivation |
|-------|------------|------------|
| **Malicious Tenant** | Authenticated API access | Reduce bill, inflate savings, access other tenant data |
| **Compromised Client** | Valid tenant credentials | Data exfiltration, billing manipulation |
| **Insider** | Code access, deployment | Insert backdoors, modify pricing |
| **Supply Chain** | Dependency compromise | Inject malicious pricing, exfiltrate data |

### Attack Vectors

```
┌─────────────────────────────────────────────────────────────────┐
│                     ACCOUNTING SYSTEM                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Client  │───▶│  API     │───▶│ Accounting│───▶│ Metrics/ │  │
│  │ Request  │    │ Gateway  │    │ Manager  │    │ Export   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │              │                 │              │         │
│       ▼              ▼                 ▼              ▼         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   THREAT SURFACE                          │  │
│  │  1. Tenant ID spoofing in request                         │  │
│  │  2. Inflated token counts in usage                        │  │
│  │  3. Negative/injected cost values                         │  │
│  │  4. Pricing registry manipulation                         │  │
│  │  5. Secret leakage in metadata/labels                     │  │
│  │  6. Rate limit bypass (DoS)                               │  │
│  │  7. Cross-tenant data access                              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implemented Mitigations

### 1. UsageRecord Validation (Usage Spoofing Prevention)

**File:** `src/ico_cache/telemetry/accounting.py`

```python
@dataclass(frozen=True)
class UsageRecord:
    tenant_id: str           # Required, non-empty
    request_id: str          # Required, non-empty
    timestamp: float         # Required, positive
    provider: str            # Required, non-empty
    model: str               # Required, non-empty
    input_tokens: int        # Required, >= 0
    output_tokens: int       # Required, >= 0
    cache_hit: bool          # Required, boolean
    # Optional cost fields - validated >= 0
    estimated_cost_usd: Optional[float]
    actual_cost_usd: Optional[float]
    saved_cost_usd: Optional[float]
    metadata: Dict           # Auto-scrubbed
```

**Controls:**
- All fields validated on construction (hard gates, not warnings)
- Immutable after creation (`frozen=True`)
- Negative token counts rejected
- Negative cost values rejected
- Metadata automatically scrubbed for secrets

### 2. Metadata Scrubbing (Sensitive Data Leakage Prevention)

**File:** `src/ico_cache/telemetry/accounting.py` — `_scrub_metadata()`

```python
SECRET_PATTERNS = [
    "api_key", "apikey", "api-key", "secret", "token", "password",
    "authorization", "bearer", "x-api-key", "access_token",
    "refresh_token", "client_secret", "private_key", "ssh_key",
    "aws_secret", "azure_key", "gcp_key", ...
]
```

**Controls:**
- Recursive scrubbing of nested dicts
- Long values truncated (>100 chars)
- Applied at UsageRecord creation time
- Also applied in tracing spans (`tracing.py`)

### 3. Pricing Registry Integrity (Pricing Manipulation Prevention)

**File:** `src/ico_cache/telemetry/cost_model.py`

```python
class CostModel:
    def __init__(self, pricing=None, allow_runtime_updates=False):
        # Merge defaults + custom
        merged = {**_DEFAULT_PRICING, **(pricing or {})}
        # FREEZE: MappingProxyType makes registry read-only
        from types import MappingProxyType
        self._pricing = MappingProxyType(merged)

        # Integrity hash computed once at init
        self._integrity_hash = self._compute_integrity_hash()
        self._allow_runtime_updates = allow_runtime_updates  # Default False

    def _verify_integrity(self) -> bool:
        current = self._compute_integrity_hash()
        if current != self._integrity_hash:
            logger.critical("PRICING INTEGRITY VIOLATION!")
            return False
        return True

    def get_pricing(self, provider, model):
        self._verify_integrity()  # Checked on EVERY access
        return self._pricing.get(f"{provider}:{model}")
```

**Controls:**
- `MappingProxyType` provides true immutability
- SHA256 integrity hash verified on every pricing access
- Runtime updates disabled by default (`allow_runtime_updates=False`)
- Global instance created once at startup, frozen
- Tampering logged at CRITICAL level

### 4. Per-Tenant Rate Limiting (DoS Prevention)

**File:** `src/ico_cache/telemetry/accounting.py` — `AccountingRateLimiter`

```python
class AccountingRateLimiter:
    def __init__(self, max_events_per_minute=1000, burst_allowance=100):
        self.max_rate = max_events_per_minute / 60.0  # events/sec
        self.burst = burst_allowance
        # Token bucket per tenant
```

**Controls:**
- Token bucket algorithm per tenant
- Configurable rate and burst
- Thread-safe with locks
- Separate buckets per tenant (isolation)
- Can be disabled for testing

### 5. Tenant Isolation Enforcement

**API Layer** (`apps/financial-rag-demo/api/main.py`):

```python
# Constant-time API key lookup
for configured_key, tenant_id in settings.api_keys.items():
    if secrets.compare_digest(configured_key, api_key):
        matched_tenant = tenant_id

# Enforce tenant scope on ALL endpoints
if req.tenant_id != authed_tenant:
    raise HTTPException(403, "Forbidden")
```

**Cache Layer** (`core/cache_engine.py`):

```python
# All cache operations scoped by tenant_id
await self.set_l1(query, response, meta, tenant_id=tenant_id, ...)
await self.async_write_l2(query, response, meta=meta, tenant_id=tenant_id)
```

**Controls:**
- API key binds to single tenant at auth time
- All cache operations require tenant_id
- Tenant isolation modes: `collection` (separate DB) or `payload` (filter)
- Accounting records carry tenant_id, validated at API boundary

### 6. No Secrets in Metrics/Labels

**File:** `src/ico_cache/telemetry/metrics.py`

```python
def record_tokens(token_type: str, count: int, tenant: str = "default"):
    TOKENS_TOTAL.labels(type=token_type, tenant=tenant).inc(count)

def record_cost(cost_type: str, usd: float, tenant: str = "default"):
    COST_USD_TOTAL.labels(type=cost_type, tenant=tenant).inc(usd)
```

**Controls:**
- Only `tenant` label (no query, no API key, no prompt)
- Tenant ID is opaque identifier, not secret
- Cost values are aggregates, not per-request details

---

## Security Test Coverage

**File:** `tests/test_accounting_security.py`

| Test Class | Coverage |
|------------|----------|
| `TestMetadataScrubbing` | 7 tests — secret redaction, truncation, nesting |
| `TestUsageRecordValidation` | 12 tests — negative values, types, immutability |
| `TestTenantIsolation` | 4 tests — rate limiter, concurrent, API boundary |
| `TestPricingManipulation` | 7 tests — immutability, integrity hash, tampering |
| `TestCostMetricInjection` | 3 tests — negative costs, inflated savings |
| `TestRateLimiting` | 4 tests — burst, refill, integration, disable |
| `TestMetricsIntegration` | 3 tests — tenant labels, no secrets |
| `TestGlobalState` | 4 tests — singleton, replacement |
| `TestEdgeCases` | 5 tests — zero values, large values, unicode |
| `TestModelPricingValidation` | 7 tests — pricing validation, calculation |

**Run:** `python -m pytest packages/ico-cache-py/tests/test_accounting_security.py -v`

---

## Remaining Risks

### HIGH

| Risk | Description | Mitigation Status |
|------|-------------|-------------------|
| **API Boundary Tenant Validation** | If API layer bypassed, forged tenant_id accepted | **PARTIAL** — UsageRecord validates format, not authority. Requires API gateway enforcement. |
| **Pricing Integrity in Memory** | Attacker with memory access could modify `_pricing` | **PARTIAL** — MappingProxyType prevents Python-level mutation. Native code / memory attacks still possible. |

### MEDIUM

| Risk | Description | Mitigation Status |
|------|-------------|-------------------|
| **Rate Limit Bypass via Distributed Tenants** | Attacker creates many tenant IDs to bypass per-tenant limits | **OPEN** — Requires tenant provisioning controls (out of scope for accounting). |
| **Cost Estimation Accuracy** | Rough token estimation (chars/4) on cache hits | **ACCEPTED** — Estimates marked as `estimated_cost_usd`. Actual costs from provider usage. |
| **Timestamp Manipulation** | Client could send fake timestamps | **MITIGATED** — Server-side `time.time()` used in `record_usage()`. |

### LOW

| Risk | Description | Mitigation Status |
|------|-------------|-------------------|
| **Denial of Service via Large Metadata** | Large metadata objects consume memory | **MITIGATED** — Truncation at 100 chars, nested scrubbing. |
| **Integer Overflow** | Very large token counts | **MITIGATED** — Python arbitrary precision integers. |
| **Clock Skew** | Timestamp integrity | **ACCEPTED** — Monotonic clock for rate limiting, wall clock for records. |

---

## Secure Deployment Checklist

- [ ] Set `API_KEYS` environment variable with strong random keys
- [ ] Configure `INGEST_ROOT_DIR` to isolated directory
- [ ] Enable TLS for all API endpoints
- [ ] Set up Prometheus metrics scraping with authentication
- [ ] Configure OTLP endpoint with TLS for tracing
- [ ] Run `python audit.py --all` before deployment
- [ ] Verify `test_accounting_security.py` passes in CI
- [ ] Monitor for "PRICING INTEGRITY VIOLATION" logs
- [ ] Alert on rate limit exceeded events
- [ ] Review tenant provisioning process (prevent tenant enumeration)

---

## Incident Response

### Pricing Integrity Violation Alert

```
CRITICAL: PRICING INTEGRITY VIOLATION: Cost model pricing has been modified!
expected_hash=a1b2c3d4... actual_hash=e5f6g7h8...
```

**Response:**
1. Immediately isolate affected instance
2. Compare pricing registry with known-good backup
3. Check for unauthorized code deployment
4. Rotate all API keys
5. Audit billing for affected period

### Rate Limit Exceeded

```
WARNING: Accounting rate limit exceeded for tenant=tenant_x
```

**Response:**
1. Check if legitimate burst (new deployment, load test)
2. If attack: block tenant API key, investigate source
3. Adjust rate limits if legitimate growth

---

## Compliance Notes

- **SOC 2 Type II**: Audit trail via immutable UsageRecord
- **GDPR**: No PII in metrics; metadata scrubbing; tenant isolation
- **PCI DSS**: No card data in accounting; secrets redacted
- **ISO 27001**: Integrity controls (hash verification), access control (tenant isolation)

---

## Future Hardening

1. **Signed UsageRecords** — Cryptographic signature for non-repudiation
2. **Pricing Attestation** — Remote attestation of pricing registry
3. **Tenant Provisioning API** — Controlled tenant creation with approval
4. **Anomaly Detection** — ML-based detection of unusual usage patterns
5. **Hardware Security Module** — HSM-backed pricing registry for high-value deployments

---

*Document version: 1.0*
*Last updated: 2026-10-06*
*Owner: Security Engineer*