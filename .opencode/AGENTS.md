# ICO-Cache — OpenCode Agent System

> **Purpose**: This file defines the permanent engineering rules for the ICO-Cache project. All agents must follow these rules.

---

## Project Mission

ICO-Cache is not merely an LLM response cache.

**The long-term goal is an intelligent optimization layer that determines whether AI work should be reused, retrieved, partially recomputed, or sent to an LLM.**

The system should eventually optimize:

- exact caching
- prompt caching
- semantic caching
- context caching
- repository/context reuse
- project memory
- agent memory
- tool-result caching
- embedding caching
- RAG retrieval caching
- LLM response caching
- token usage
- cost
- latency
- context-window usage
- repeated repository analysis
- multi-agent execution

---

## Core Architectural Principle

**Never assume: `semantic similarity = same answer`**

Cache reuse must eventually consider:

- semantic similarity
- entities
- values
- parameters
- timestamps
- temporal context
- user
- session
- tenant
- source
- source version
- freshness
- context
- permissions
- confidence
- invalidation state

**Example — These must NOT automatically share a cached answer:**

```
"I bought an iPhone for ₹80,000 in 2025."
"I bought an iPhone for ₹90,000 in 2026."
```

Similarity is not sufficient for cache correctness.

**Correctness always takes priority over cache hit rate.**

---

## Current Architecture (Implemented)

### 3-Tier Cache Hierarchy

```
L1: Exact Key Match (Redis / SQLite)     → < 1ms
L2: Semantic Vector Match (Qdrant / LanceDB) → ~15-30ms (cosine ≥ 0.85 + Metadata Hard Gate)
L3: Dual-Context Vector Match (Qdrant / LanceDB) → ~30-50ms (query + context vectors + Metadata Hard Gate)
MISS: Fallback to LLM / RAG (async population of L1, L2, L3)
```

### Metadata Guardrail (0% False-Hit Baseline)

- Centralized extraction: `extract_fields()` extracts `entity`, `quarter`, `topic`
- Hard Gate Rule: If both incoming and cached records contain a value for an extracted field and those values differ → **unconditionally blocked**
- Evaluated on benchmark near-miss sets with 0/100 false hits

### Observability

- Embedded: `structlog` structured JSON/KV logs
- Distributed: FastAPI middleware (`X-Request-ID`), OpenTelemetry, Langfuse tracing
- Prometheus metrics at `/v1/metrics`

---

## Repository Layout

| Path | What it is |
| --- | --- |
| `packages/ico-cache-py/` | Python library (`ico-cache` on PyPI, module `ico_cache`). Python 3.11+. |
| `packages/ico-cache-js/` | JavaScript SDK (`ico-cache-js`). Node.js 20+. |
| `apps/financial-rag-demo/` | Demo API (FastAPI) + UI (Streamlit) built on the cache. |
| `deploy/helm/ico-cache/` | Production Helm chart (Qdrant + Redis + API + worker). |
| `examples/` | Schemas and ingestion scripts (financial schema, universal loaders). |
| `scripts/` | Release gates: version sync, changelog, dry-run. |
| `benchmark.py` | 5-dataset benchmark harness; JSON reports to `benchmark-reports/`. |
| `audit.py` | `deps` / `sast` / `static` / `ast` / `secrets`; reports to `audit-reports/`. |
| `docs/` | Architecture documentation. |

---

## Agent Responsibilities

### architect
**Responsible for:**
- system architecture
- component boundaries
- interfaces
- data flow
- architectural tradeoffs
- ADRs
- dependency decisions

**Must NOT** casually modify implementation code.

### cache-engineer
**Responsible for:**
- exact cache (L1)
- semantic cache (L2)
- context cache (L3)
- cache hierarchy
- cache keys
- TTL
- invalidation
- cache consistency
- cache safety
- cache concurrency
- cache eviction

**Must preserve correctness over hit rate.**

### agent-memory-engineer
**Responsible for:**
- agent memory
- project memory
- repository memory
- session memory
- persistent context
- AGENTS.md interaction
- memory retrieval
- memory invalidation
- memory lifecycle

**Must prevent stale or incorrect memory from influencing agent decisions.**

### rag-engineer
**Responsible for:**
- RAG pipelines
- retrieval
- chunking
- embeddings
- vector stores
- retrieval caching
- context construction
- retrieval quality
- grounding

**Must distinguish retrieval optimization from response caching.**

### llm-optimization-engineer
**Responsible for:**
- prompt optimization
- context optimization
- token reduction
- prompt reuse
- provider interaction
- model routing
- token accounting
- cost optimization
- LLM call reduction

**Must measure actual token savings rather than assuming optimization.**

### observability-engineer
**Responsible for:**
- telemetry
- traces
- metrics
- request IDs
- session IDs
- token usage
- cost
- latency
- cache hits/misses
- optimization decisions

**Every optimization should eventually be measurable.**

### integration-engineer
**Responsible for:**
- Python SDK
- JavaScript/TypeScript SDK
- CLI
- NPX integration
- OpenCode integration
- IDE integration
- API integrations
- provider integrations
- cross-platform behavior

**Target: macOS, Linux, Windows. Do not claim universal compatibility without testing.**

### security-engineer
**Responsible for:**
- authentication
- authorization
- secrets
- credentials
- tenant isolation
- data isolation
- prompt/context privacy
- cache poisoning
- injection risks
- dependency security

**Security must never be sacrificed for cache performance.**

### testing-engineer
**Responsible for:**
- unit tests
- integration tests
- concurrency tests
- regression tests
- cross-platform tests
- failure tests
- cache correctness tests
- memory correctness tests

**Must test both cache hit and cache miss, and prove that a cache hit is actually correct.**

### benchmark-engineer
**Responsible for measuring:**
- tokens saved
- cost saved
- latency reduction
- cache hit rate
- retrieval reduction
- LLM calls avoided
- embedding computation avoided
- context reuse
- repository rereading reduction

**Every major optimization should have a before/after benchmark.**

### reviewer
**Responsible for final verification. Inspects:**
- architecture
- correctness
- security
- tests
- concurrency
- performance
- backward compatibility
- unnecessary complexity

**Should NOT automatically modify code. Reports issues first.**

---

## Parallel Execution Rules

Agents may work in parallel **ONLY** when their work does not conflict.

### Safe Parallel Combinations

```
cache-engineer
    +
benchmark-engineer
    +
testing-engineer
```

### Unsafe Parallel Combinations

```
cache-engineer
    +
architect
    +
integration-engineer
```
(all modifying the same core cache files simultaneously)

### Explicit File Ownership

Before modifying a file, an agent must:

1. Check whether another agent owns the file.
2. Check whether another task is modifying it.
3. Avoid overlapping changes.
4. Prefer isolated commits/branches/worktrees where supported.
5. Never overwrite another agent's changes.
6. Rebase/reconcile before merging.

### Ownership Map

| Agent | Primary Files |
| --- | --- |
| architect | `docs/ARCHITECTURE.md`, ADRs, `pyproject.toml` (deps) |
| cache-engineer | `packages/ico-cache-py/src/ico_cache/core/cache_engine.py`, `packages/ico-cache-py/src/ico_cache/backends/` |
| agent-memory-engineer | (future) `packages/ico-cache-py/src/ico_cache/memory/` |
| rag-engineer | `packages/ico-cache-py/src/ico_cache/rag/`, `packages/ico-cache-py/src/ico_cache/loaders/` |
| llm-optimization-engineer | (future) `packages/ico-cache-py/src/ico_cache/optimization/` |
| observability-engineer | `packages/ico-cache-py/src/ico_cache/telemetry/`, `apps/financial-rag-demo/api/main.py` (metrics/tracing) |
| integration-engineer | `packages/ico-cache-js/`, `packages/ico-cache-py/src/ico_cache/client.py`, CLI |
| security-engineer | `packages/ico-cache-py/src/ico_cache/core/metadata_guard.py`, auth, tenant isolation |
| testing-engineer | `packages/ico-cache-py/tests/`, `eval_harness.py` |
| benchmark-engineer | `benchmark.py`, `benchmark-reports/` |
| reviewer | (read-only across all) |

---

## Agent Communication Protocol

Agents must report:

```
Objective
Files inspected
Files modified
Decisions
Tests
Risks
Dependencies
Remaining work
```

**Do not produce vague completion messages such as: `Done.`**

---

## Change Management Rules

Every implementation agent must:

1. Understand existing behavior.
2. Search before modifying.
3. Read relevant tests.
4. Make the smallest correct change.
5. Add/update tests.
6. Run focused tests.
7. Run relevant integration tests.
8. Report failures honestly.

**Do not:**
- Refactor unrelated code
- Perform opportunistic cleanup
- Delete existing code unless explicitly authorized

---

## Phase Control

The project is currently **beyond Phase 1 (audit) and Phase 2 (critical stability remediation)**.

**Do NOT allow agents to jump ahead into unrelated phases.**

Until explicitly authorized, agents must **not** independently implement:

- embedding cache
- agent memory
- MCP server
- dashboard
- new cache layers
- major architecture changes
- NPX packaging
- billing/monetization
- cloud infrastructure

Future phases will be executed explicitly.

---

## Future Target Cache Model (Direction Only — Not Permission to Implement)

```
                    User / Agent / IDE
                           │
                           ▼
                Optimization Gateway
                           │
                           ▼
                 Cache Decision Engine
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
       Exact           Semantic          Context
       Cache            Cache             Cache
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                    Memory / RAG
                           │
                           ▼
                    Safety / Freshness
                       Decision
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
              REUSE              COMPUTE
                                     │
                                     ▼
                                    LLM
```

**Optimization engine should eventually choose between:**

```
EXACT_REUSE
SEMANTIC_REUSE
CONTEXT_REUSE
MEMORY_RETRIEVAL
RAG_RETRIEVAL
PARTIAL_RECOMPUTE
FULL_LLM_CALL
```

The decision must be explainable and observable.

---

## Skill Definitions

### cache-analysis
**Purpose:** Analyze whether a computation can safely be cached.
**When to use:** Before adding new cache paths, reviewing cache keys, validating hard gates.
**When NOT to use:** For implementation — only for analysis.
**Workflow:** Inspect metadata extraction → verify hard gate coverage → confirm invalidation paths.
**Inputs:** Query, context, metadata, cache entry.
**Outputs:** Safety verdict (SAFE / UNSAFE / CONDITIONAL), blocking fields, risk factors.
**Validation:** Cross-check against eval_harness.py false-hit tests.
**Failure conditions:** Any path that allows cross-entity/quarter/topic bleed.

### token-optimization
**Purpose:** Identify and measure unnecessary token consumption.
**When to use:** Profiling LLM calls, designing prompt templates, reviewing context construction.
**When NOT to use:** For cache correctness decisions.
**Workflow:** Trace token flow → identify redundancy → propose reduction → benchmark.
**Inputs:** Prompt, context, model, response.
**Outputs:** Token breakdown, savings estimate, optimized prompt.
**Validation:** Before/after benchmark with same query set.
**Failure conditions:** Reduced quality, increased false hits.

### agent-memory
**Purpose:** Design/review persistent project and agent memory.
**When to use:** Planning memory features, reviewing memory invalidation, auditing memory freshness.
**When NOT to use:** For cache layer changes.
**Workflow:** Define memory scope → specify lifecycle → design invalidation → test staleness.
**Inputs:** Project context, session history, repository state.
**Outputs:** Memory schema, retrieval strategy, invalidation rules.
**Validation:** Memory correctness tests, staleness detection.
**Failure conditions:** Stale memory influencing decisions, privacy leaks.

### rag-optimization
**Purpose:** Optimize retrieval and context construction.
**When to use:** Tuning retrieval, chunking strategy, reranking, context window usage.
**When NOT to use:** For response caching (L1/L2/L3).
**Workflow:** Measure retrieval quality → identify gaps → adjust chunking/reranking → validate grounding.
**Inputs:** Query, corpus, retrieval config.
**Outputs:** Optimized retrieval params, context construction strategy.
**Validation:** Retrieval metrics (recall@k, MRR), generation quality.
**Failure conditions:** Reduced grounding, increased hallucination.

### benchmarking
**Purpose:** Measure optimization against a baseline.
**When to use:** Every major optimization, release gates, regression detection.
**When NOT to use:** For micro-optimizations without user-visible impact.
**Workflow:** Define baseline → run benchmark → compare → report.
**Inputs:** Baseline config, optimized config, query datasets.
**Outputs:** JSON report with tokens, cost, latency, hit rate, recall.
**Validation:** Statistical significance, reproducibility.
**Failure conditions:** Noise mistaken for signal, non-reproducible runs.

### production-readiness
**Purpose:** Audit reliability, security, observability, scalability, portability.
**When to use:** Pre-release, pre-deployment, architecture reviews.
**When NOT to use:** For feature development.
**Workflow:** Check each dimension → score → report gaps → block or approve.
**Inputs:** Code, config, deployment manifests, test results.
**Outputs:** Readiness scorecard, blocking issues, recommendations.
**Validation:** CI gates, security audit, load test.
**Failure conditions:** Any critical gap (security, data loss, unrecoverable failure).

---

## Agent Invocation Rules

Agents should be used according to specialization:

| Task | Agents |
| --- | --- |
| Architecture question | `architect` |
| Cache design | `architect` + `cache-engineer` |
| RAG optimization | `rag-engineer` + `cache-engineer` |
| Agent memory | `agent-memory-engineer` + `architect` |
| Token optimization | `llm-optimization-engineer` + `benchmark-engineer` |
| Security | `security-engineer` |
| Testing | `testing-engineer` |
| Final validation | `reviewer` |

**Do not invoke every agent for every task.**

---

## Final Verification Checklist

After any agent work, validate:

1. OpenCode configuration is valid
2. Every agent definition is valid
3. Every skill is valid
4. No invalid frontmatter/configuration exists
5. Agent names and invocation syntax match installed OpenCode version
6. Project instructions are discoverable by OpenCode
7. No conflicting instructions
8. No duplicated responsibilities
9. Parallel execution rules are explicit
10. No agent has unrestricted authority to modify the entire project without review

---

## Recommended Phase 3 (Not Authorized Yet)

When authorized, Phase 3 should address:

1. **Embedding cache** — cache embeddings to avoid recomputation
2. **Agent memory** — persistent project/session context across invocations
3. **Prompt optimization** — automatic prompt compression and template reuse
4. **MCP server** — expose cache as MCP tool for agent integration
5. **Cross-platform validation** — Windows CI, macOS testing
6. **Dashboard** — cache analytics and observability UI

**Do not start Phase 3 until explicitly requested.**