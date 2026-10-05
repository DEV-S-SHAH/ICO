---
name: token-optimization
description: Identify and measure unnecessary token consumption in LLM calls. Use for profiling token usage, designing prompt templates, reviewing context construction, and validating optimization savings.
---

# Token Optimization Skill

## Purpose

Identify, measure, and reduce unnecessary token consumption in LLM interactions while maintaining or improving answer quality.

## When to Use

- Profiling LLM token usage per query type
- Designing/optimizing prompt templates
- Reviewing context construction for redundancy
- Validating claimed token savings
- Model routing decisions (cost/quality tradeoffs)

## When NOT to Use

- For cache correctness decisions (use cache-analysis skill)
- For retrieval optimization (use rag-optimization skill)
- For implementation without measurement (must benchmark)

## Workflow

### 1. Trace Token Flow
```python
# Instrument every LLM call
from ico_cache.telemetry.metrics import GENERATION_SECONDS

# Token accounting per call:
# - Prompt tokens (input)
# - Completion tokens (output)
# - Cached tokens (if provider supports)
# - Total tokens = prompt + completion
```

### 2. Identify Redundancy Categories

| Category | Detection | Reduction Strategy |
| --- | --- | --- |
| Repeated system prompts | Same prompt prefix across calls | Template + variable injection |
| Verbose context | Low-relevance chunks in context | Relevance filtering, summarization |
| Redundant few-shots | Same examples for similar queries | Dynamic few-shot selection |
| Unnecessary calls | Cacheable queries hitting LLM | Cache hierarchy optimization |
| Oversized model | Simple queries using expensive model | Model routing by complexity |

### 3. Design Optimization
- **Prompt templates** — Parameterized, versioned, tested
- **Context packing** — Hierarchical: summary → relevant chunks → full text
- **Model routing** — Classify query complexity → route to appropriate model
- **Prompt caching** — Provider-level (e.g., Anthropic prompt caching) + ICO-Cache

### 4. Benchmark Before/After
```bash
# Baseline
python benchmark.py --dataset all --output baseline.json

# After optimization
python benchmark.py --dataset all --output optimized.json

# Compare
python -c "
import json
b = json.load(open('baseline.json'))
o = json.load(open('optimized.json'))
print(f'Tokens saved: {b[\"tokens\"] - o[\"tokens\"]}')
print(f'Cost saved: ${b[\"cost\"] - o[\"cost\"]:.2f}')
print(f'Quality delta: {o[\"quality\"] - b[\"quality\"]:.3f}')
"
```

## Inputs

- Prompt templates and examples
- Context construction pipeline
- Model configuration (provider, model name, parameters)
- Query workload (representative query set)
- Quality evaluation criteria

## Outputs

- Token breakdown per query type (prompt/completion/cached)
- Savings estimate (tokens, USD, latency)
- Optimized prompt/context configuration
- Quality impact assessment
- Model routing rules

## Validation

- **Before/after benchmark** on same query set
- **Quality evaluation** — Must not degrade (eval_harness.py or human eval)
- **Statistical significance** — Enough samples for confidence
- **Regression test** — Add benchmark as CI gate for token metrics

## Failure Conditions

- Quality degradation (increased false hits, hallucination, incomplete answers)
- Optimization adds latency exceeding token savings
- Provider-specific optimizations breaking portability
- Unmeasured "savings" claimed without benchmark evidence

## Example Output

```
Token Optimization Report
=========================

Query Type: Financial Q&A (100 queries)

Baseline (per query avg):
  Prompt tokens:    4,200
  Completion tokens:   350
  Total tokens:     4,550
  Cost:           $0.0136
  Latency:          3.2s

Optimized (per query avg):
  Prompt tokens:    2,800  (-33%)
  Completion tokens:   340  (-3%)
  Total tokens:     3,140  (-31%)
  Cost:           $0.0094  (-31%)
  Latency:          2.1s  (-34%)

Quality:  No significant degradation (p > 0.05)

Savings (100 queries/day):
  Tokens/day:    141,000
  Cost/month:    $126
  Latency saved: 110s/day
```