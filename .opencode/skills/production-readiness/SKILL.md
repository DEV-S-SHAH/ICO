---
name: production-readiness
description: Audit reliability, security, observability, scalability, and portability for production deployment. Use pre-release, pre-deployment, and for architecture reviews. Produces readiness scorecard with blocking issues.
---

# Production Readiness Skill

## Purpose

Comprehensive audit of production readiness across five dimensions: reliability, security, observability, scalability, and portability.

## When to Use

- Pre-release validation
- Pre-deployment checklist
- Architecture review for production changes
- Incident postmortem prevention
- Compliance verification

## When NOT to Use

- During active development (use during validation gates)
- For feature design (use architect agent)
- For micro-optimizations

## Workflow

### 1. Reliability Audit

| Check | Tool/Method | Pass Criteria |
| --- | --- | --- |
| Health probes | `/v1/health`, `/v1/ready` | 200 when healthy, 503 when degraded |
| Graceful degradation | Backend down simulation | Cache falls back to MISS, no crashes |
| Single-flight coalescing | Concurrency test (50 parallel) | Exactly 1 generation |
| Timeout handling | `lookup_timeout` config | Slow backend → MISS, not hang |
| Error caching prevention | Refusal/error injection | Never cached (test_error_and_refusal) |
| Invalidation propagation | Multi-instance test | All instances purge within 5s |
| Data durability | Redis/Qdrant persistence | Acknowledged writes survive restart |
| Connection pooling | Load test (1000 RPS) | No connection exhaustion |

### 2. Security Audit

```bash
# Run full security audit
python audit.py --all

# Checks:
# - pip-audit: dependency vulnerabilities
# - bandit: SAST (SQL injection, hardcoded secrets, etc.)
# - ruff + mypy: static analysis
# - AST analysis: dangerous patterns
# - Secrets scan: no credentials in code
```

| Check | Tool | Pass Criteria |
| --- | --- | --- |
| Dependency vulnerabilities | pip-audit | 0 critical, 0 high |
| Static analysis | bandit | 0 high, 0 medium |
| Type safety | mypy | 0 errors |
| Code quality | ruff | 0 errors |
| Secrets in code | audit.py | 0 findings |
| Tenant isolation | test_multitenancy.py | All tests pass |
| Auth constant-time | code review | secrets.compare_digest used |
| Input validation | test_security_hardening.py | All tests pass |
| Path traversal | test_security_hardening.py | All tests pass |

### 3. Observability Audit

| Check | Verification |
| --- | --- |
| Structured logs | JSON output with layer, tenant, query_hash, latency, hit |
| Request ID propagation | X-Request-ID in logs, traces, response headers |
| Metrics exposed | `/v1/metrics` returns Prometheus format |
| Cache layer metrics | ico_cache_lookups_total{layer,result} |
| Latency histograms | ico_cache_lookup_seconds{layer} |
| Generation metrics | ico_cache_generation_seconds |
| Backend health | ico_cache_backend_up{backend} |
| Tracing spans | cache_lookup.l1/l2/l3, rag_fallback |
| Langfuse integration | Optional, no crash when disabled |
| Log PII safety | No raw queries in production logs (configurable) |

### 4. Scalability Audit

| Dimension | Test | Target |
| --- | --- | --- |
| Cache throughput | 10K RPS L1 | < 5ms p99 |
| Semantic throughput | 1K RPS L2 | < 50ms p99 |
| Context throughput | 500 RPS L3 | < 100ms p99 |
| Ingestion throughput | 100 docs/min | Async, non-blocking |
| Memory stability | 24h soak | No leaks, stable RSS |
| Connection scaling | 100 concurrent | Pool reuse, no exhaustion |
| Horizontal scaling | 3+ API replicas | Shared Redis/Qdrant, consistent |
| Tenant isolation scale | 1000 tenants | Collection or payload mode |

### 5. Portability Audit

| Platform | CI Status | Local Validation |
| --- | --- | --- |
| Linux (Ubuntu) | ✅ CI passes | Required |
| macOS (Apple Silicon) | ❌ Not in CI | Required for release |
| Windows | ❌ Not in CI | Required for release |
| Python 3.11 | ✅ | Required |
| Python 3.12 | ✅ | Required |
| Python 3.13 | ⚠️ Test | Optional |

**Portability Checks:**
- [ ] No Unix-only syscalls (signals, fork, /dev/*)
- [ ] SQLite WAL mode works on Windows
- [ ] Path handling uses `os.path` / `pathlib`
- [ ] No hardcoded `/tmp` or `/var` paths
- [ ] Threading model works on all platforms
- [ ] Docker images multi-arch (amd64/arm64)

## Inputs

- Current codebase (main branch or release candidate)
- Deployment configuration (Helm values, docker-compose)
- Test suite results (pytest, eval_harness, benchmark)
- Security audit report (`audit.py --all`)
- Benchmark report (`benchmark.py --dataset all`)

## Outputs

**Readiness Scorecard:**

```
Production Readiness Report
===========================

Version: 1.0.4
Date: 2026-01-15
Git SHA: abc123...

=== Reliability ===     Score: 9/10
✅ Health probes
✅ Graceful degradation
✅ Single-flight coalescing
✅ Timeout handling
✅ Error caching prevention
⚠️ Invalidation propagation (5s target, measured 8s)
✅ Data durability
✅ Connection pooling

=== Security ===        Score: 10/10
✅ Dependency vulnerabilities (0 critical/high)
✅ Static analysis (0 high/medium)
✅ Type safety (0 mypy errors)
✅ Code quality (0 ruff errors)
✅ Secrets scan (0 findings)
✅ Tenant isolation
✅ Auth constant-time
✅ Input validation
✅ Path traversal prevention

=== Observability ===   Score: 9/10
✅ Structured logs
✅ Request ID propagation
✅ Metrics exposed
✅ Cache layer metrics
✅ Latency histograms
✅ Generation metrics
✅ Backend health
✅ Tracing spans
✅ Langfuse integration
⚠️ Log PII safety (configurable, not default)

=== Scalability ===     Score: 7/10
✅ Cache throughput
✅ Semantic throughput
✅ Context throughput
✅ Ingestion throughput
⚠️ Memory stability (minor leak in worker, tracked in #234)
✅ Connection scaling
✅ Horizontal scaling
✅ Tenant isolation scale

=== Portability ===     Score: 6/10
✅ Linux
❌ macOS (not in CI)
❌ Windows (not in CI)
✅ Python 3.11/3.12
⚠️ Python 3.13 (untested)
✅ No Unix-only syscalls
✅ SQLite WAL on Windows
✅ Path handling
✅ No hardcoded paths
✅ Threading model
✅ Multi-arch Docker

=== Overall ===         Score: 8.2/10
Status: CONDITIONAL PASS
Blocking Issues: 0
Required Before Release:
  - Add macOS/Windows to CI
  - Fix worker memory leak (#234)
  - Enable PII-safe logging by default
```

## Validation

- All automated checks pass (audit.py, pytest, benchmark.py)
- Manual verification of scorecard items
- Stakeholder sign-off for conditional items

## Failure Conditions

**Block Release:**
- Any critical security finding
- Reliability score < 8 (data loss, crash, hang risk)
- Observability score < 7 (blind in production)

**Conditional Pass (fix in next patch):**
- Scalability score < 8 with known workaround
- Portability gaps with documented timeline

**Tracking:**
- All findings filed as GitHub issues with `production-readiness` label
- Owner assigned, target milestone set