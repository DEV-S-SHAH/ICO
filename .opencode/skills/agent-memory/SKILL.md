---
name: agent-memory
description: Design and review persistent project and agent memory systems. Covers memory schema, lifecycle, retrieval, invalidation, and staleness prevention. Use when planning memory features or auditing memory freshness.
---

# Agent Memory Skill

## Purpose

Design, review, and validate persistent memory systems for agents — ensuring memory is fresh, isolated, auditable, and actually improves decisions rather than degrading them with stale information.

## When to Use

- Planning memory features (Phase 3+)
- Reviewing memory schema design
- Auditing memory invalidation completeness
- Testing staleness detection
- Defining memory-cache boundaries

## When NOT to Use

- For cache layer changes (use cache-analysis skill)
- For RAG retrieval (use rag-optimization skill)
- For implementation without design review

## Workflow

### 1. Define Memory Scope

| Memory Type | Scope | Lifetime | Invalidation Trigger |
| --- | --- | --- | --- |
| Agent memory | Per agent instance | Session + persistent | Explicit reset, contradiction |
| Project memory | Per repository/project | Long-term | Source file change, explicit update |
| Session memory | Per conversation | Session | Session end, topic change |
| Repository memory | Per codebase | Long-term | Git commit, explicit update |

### 2. Specify Memory Schema

```python
class MemoryUnit:
    id: str                    # Stable identifier
    type: Literal["fact", "decision", "pattern", "context", "preference"]
    content: str               # The memory content
    metadata: {
        entity: str,           # e.g., "MSFT", "auth_module"
        topic: str,            # e.g., "revenue", "authentication"
        source: str,           # "user", "document", "code", "inference"
        source_version: str,   # Git SHA, document version, timestamp
        confidence: float,     # 0.0 - 1.0
        timestamp: datetime,   # When created/updated
        tenant_id: str,        # Isolation boundary
        project_id: str,       # Project boundary
        session_id: str,       # Session boundary (optional)
    }
    embedding: List[float]     # For semantic retrieval
    references: List[str]      # Source chunk IDs, document IDs
```

### 3. Design Lifecycle

**Creation:**
- Explicit: User/agent says "remember X"
- Implicit: High-confidence extraction from documents/code
- Inferred: Pattern detection across interactions

**Update:**
- Contradiction detection (new info conflicts with memory)
- Confidence adjustment based on verification
- Source version change (document updated)

**Invalidation:**
- Explicit: User/agent says "forget X"
- Source change: Git commit modifies referenced file
- Contradiction: New high-confidence info contradicts
- TTL: Configurable expiry for low-confidence memories
- Tenant/project deletion: Cascade purge

**Retrieval:**
- Semantic search + metadata filtering (entity, topic, project)
- Recency weighting (newer memories preferred)
- Confidence threshold (filter low-confidence)
- Cross-reference validation (source still exists)

### 4. Test Staleness Prevention

```python
# Test: Memory invalidated when source document updates
async def test_memory_invalidated_on_source_change():
    mem_id = await memory.store("MSFT Q1 revenue was $60B", source="doc_v1")
    await document.update("doc_v1", new_content="MSFT Q1 revenue was $62B")
    retrieved = await memory.retrieve("MSFT Q1 revenue")
    assert retrieved.content == "MSFT Q1 revenue was $62B"
    assert retrieved.metadata.source_version == "doc_v2"

# Test: Stale memory blocked by confidence decay
async def test_low_confidence_memory_not_used():
    await memory.store("Pattern: use factory pattern", confidence=0.3)
    retrieved = await memory.retrieve("design pattern", min_confidence=0.7)
    assert retrieved is None  # Below threshold
```

## Inputs

- Project context (repository, documents, conventions)
- Session history (conversation, decisions, patterns)
- Agent type (coding, analysis, research, etc.)
- Tenant/project isolation requirements
- Privacy constraints (PII handling)

## Outputs

- Memory schema definition
- Lifecycle rules (create/update/invalidate/retrieve)
- Invalidation triggers and propagation
- Retrieval strategy (semantic + metadata + recency + confidence)
- Staleness detection and prevention mechanisms
- Audit trail specification

## Validation

- **Staleness tests** — Memory invalidated on source change
- **Isolation tests** — No cross-tenant/project leakage
- **Contradiction tests** — Conflicting memories resolved correctly
- **Confidence tests** — Low-confidence memories filtered
- **Privacy tests** — No PII without consent
- **Performance tests** — Retrieval latency < 50ms

## Failure Conditions

- Stale memory influences agent decisions
- Cross-tenant/project memory leakage
- Memory grows unbounded (no eviction)
- Contradictions not detected
- PII exposed in memory
- Memory retrieval slower than cache lookup

## Memory vs Cache Boundary

| Aspect | Memory | Cache |
| --- | --- | --- |
| **Key** | Entity + topic + timestamp | Query + context + metadata |
| **Purpose** | Knowledge accumulation | Response reuse |
| **Reuse decision** | Confidence-weighted (soft) | Hard gate (strict) |
| **Invalidation** | Source change, contradiction | TTL, explicit, source change |
| **Observability** | Retrieval relevance, staleness | Hit/miss, latency |
| **Privacy** | Opt-in, auditable | Transient, automatic |