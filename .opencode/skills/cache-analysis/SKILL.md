---
name: cache-analysis
description: Analyze whether a computation can safely be cached. Validates metadata extraction, hard gate coverage, and invalidation paths. Use before adding new cache paths or reviewing cache correctness.
---

# Cache Analysis Skill

## Purpose

Determine if a given query/context/response can be safely cached without risking incorrect reuse (false hits).

## When to Use

- Before adding new cache paths (L1/L2/L3)
- Reviewing cache key design
- Validating hard gate coverage for new metadata fields
- Auditing invalidation completeness
- Evaluating cache safety for new domains

## When NOT to Use

- For implementation (use cache-engineer agent)
- For benchmarking (use benchmarking skill)
- For RAG retrieval decisions (use rag-optimization skill)

## Workflow

### 1. Inspect Metadata Extraction
```python
# Check what fields are extracted from query/context
schema = MetadataSchema(fields=[...])
extracted = schema.extract(query_text)
# Verify: entity, quarter, topic, and domain-specific fields
```

### 2. Verify Hard Gate Coverage
```python
# For each extracted field, confirm it's in filter_keys
filter_keys = schema.filter_keys  # fields with required_in_gate=True
# Confirm: all security-relevant fields are gated
```

### 3. Analyze Invalidation Paths
```python
# For each cache layer, verify invalidation triggers
# L1: TTL expiry, explicit invalidate, source change
# L2: Vector delete by filter, collection drop, TTL (if supported)
# L3: Vector delete by filter, collection drop
# Async: Redis Streams invalidation worker
```

### 4. Cross-Check Against False-Hit Tests
```bash
python eval_harness.py              # Standard near-miss set
python eval_harness.py --eval-adversarial  # Adversarial set
# Must achieve 0/100 false hits
```

## Inputs

- Query text
- Context text (optional)
- Explicit metadata (optional)
- Cache entry candidate (for hit validation)
- MetadataSchema configuration

## Outputs

**Verdict:** `SAFE` | `UNSAFE` | `CONDITIONAL`

**Blocking Fields:** List of metadata fields that would block a hit

**Risk Factors:**
- Missing metadata extraction for security-relevant fields
- Hard gate not covering all filter_keys
- Invalidation path gaps (stale data possible)
- Cross-tenant leakage potential
- Temporal staleness (quarter/year boundaries)

## Validation

- Run `eval_harness.py` — must pass 0% false-hit baseline
- Run `test_cache_engine.py` — concurrency and correctness tests pass
- Run `test_invalidation.py` — invalidation propagation tests pass

## Failure Conditions

Any path that allows:
- Cross-entity cache bleed (MSFT ↔ AAPL)
- Cross-quarter cache bleed (Q1 ↔ Q2)
- Cross-topic cache bleed (revenue ↔ R&D)
- Cross-tenant cache bleed
- Stale data served after source update
- Uncacheable content cached (errors, refusals)

## Example Analysis

```
Query: "What was Microsoft's revenue in Q1 2026?"
Context: "MSFT 2026-Q1 earnings call transcript"

Extracted Metadata:
  entity: "MSFT"
  quarter: "2026-Q1"
  topic: "revenue"

Cache Candidate Metadata:
  entity: "MSFT"        → MATCH (gate passes)
  quarter: "2026-Q1"    → MATCH (gate passes)
  topic: "revenue"      → MATCH (gate passes)

Verdict: SAFE (all gated fields match)
```

```
Query: "What was Apple's revenue in Q1 2026?"
Context: "AAPL 2026-Q1 earnings call transcript"

Cache Candidate Metadata (from MSFT query above):
  entity: "MSFT"        → CONFLICT (gate BLOCKS)
  quarter: "2026-Q1"    → MATCH
  topic: "revenue"      → MATCH

Verdict: UNSAFE (entity conflict blocks hit)
```