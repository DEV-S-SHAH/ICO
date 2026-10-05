# ADR-002: DecisionEngine vs CacheEngine Ownership

**Status**: ACCEPTED  
**Date**: 2026-10-06  
**Deciders**: Architect, Cache Engineer  
**Reviewers**: Security Engineer, Integration Engineer, Observability Engineer

## Context

The Phase 3 architecture introduces a Decision Engine to make intelligent reuse decisions across 10 cache layers (L0-L9). The Phase 3 Architecture Review identified ambiguity between DecisionEngine and CacheEngine responsibilities, with two competing patterns proposed:

- **Option A**: DecisionEngine as wrapper class around CacheEngine
- **Option B**: DecisionEngine as policy layer above CacheEngine; CacheEngine retains `resolve()` as stable public API

The review recommended **Option B** to maintain backward compatibility and clear separation of concerns.

## Decision

**DecisionEngine is a policy/orchestration layer that sits ABOVE CacheEngine.**

### DecisionEngine Responsibilities (Policy Layer)

| Responsibility | Description |
|----------------|-------------|
| **Evaluate reuse opportunity** | Given a `DecisionContext`, determine which layers are applicable and in what order to check them |
| **Evaluate policies** | Apply `ReusePolicy` (STRICT/BALANCED) to gate evaluations and confidence thresholds |
| **Evaluate hard gates** | Execute `hard_gate()` with appropriate `GateMode` per layer; collect pass/fail results |
| **Evaluate confidence** | Compute confidence scores per layer using the confidence model; apply modifiers |
| **Select reuse action** | Choose `ReuseAction` (EXACT_REUSE, SEMANTIC_REUSE, CONTEXT_REUSE, MEMORY_RETRIEVAL, RAG_RETRIEVAL, PARTIAL_RECOMPUTE, FULL_LLM_CALL) based on highest-confidence passing layer |
| **Determine fallback** | If no layer meets confidence threshold, construct fallback plan (PARTIAL_RECOMPUTE → FULL_LLM_CALL) |
| **Explain decision** | Produce human-readable `reasoning`, `metadata_gates_passed`, `metadata_gates_failed`, `fallback_reason` |
| **Register layer implementations** | Accept `CacheLayer` implementations via `register_layer()` for extensibility |

### CacheEngine Responsibilities (Storage/Execution Layer)

| Responsibility | Description |
|----------------|-------------|
| **Cache storage interaction** | Direct read/write to Redis, SQLite, Qdrant, LanceDB via backend abstractions |
| **Existing cache hierarchy** | Implements L1/L2/L3 lookup and write logic (`get_l1`, `get_l2`, `get_l3`, `async_write_l2`, `async_write_l3`) |
| **Lookup/write** | Low-level `get(key)`, `set(key, value, ttl)` operations per layer |
| **Single-flight** | Manages `_inflight` dict and locks for deduplicating concurrent generations (EXISTING) |
| **Backend interaction** | Uses `BaseExactStore`, `BaseVectorStore`, `BaseEmbedder` abstractions |
| **Invalidation integration** | Executes `invalidate()` across L1/L2/L3; publishes to Redis Streams for L4-L9 |
| **Stable public API** | `resolve()`, `resolve_or_generate()`, `invalidate()` remain unchanged for 2.x compatibility |

### Interface Contract

```python
# DecisionEngine (NEW)
class DecisionEngine:
    def __init__(self, cache_engine: CacheEngine, policy: ReusePolicy = ReusePolicy.BALANCED):
        self.cache_engine = cache_engine
        self.policy = policy
        self._layers: Dict[str, CacheLayer] = {}  # L0-L9 implementations
    
    def register_layer(self, layer: CacheLayer) -> None:
        """Register a cache layer implementation."""
        self._layers[layer.name] = layer
    
    async def decide(self, ctx: DecisionContext) -> ReuseDecision:
        """Main entry point: evaluate all layers, return decision with confidence."""
        ...
    
    def _evaluate_layer(self, layer_name: str, ctx: DecisionContext) -> LayerEvaluation:
        """Check a single layer: lookup, hard gates, confidence."""
        ...
    
    def _apply_policy(self, evaluations: List[LayerEvaluation]) -> ReuseDecision:
        """Select best action based on policy thresholds."""
        ...


# CacheEngine (EXTENDED - backward compatible)
class CacheEngine:
    # EXISTING - unchanged
    async def resolve(self, query, context, meta, tenant_id) -> ResolveResult: ...
    async def resolve_or_generate(self, query, context, meta, tenant_id, generate_fn) -> Result: ...
    async def invalidate(self, tenant_id, filter_dict) -> InvalidationResult: ...
    
    # PROPOSED - new layer-agnostic primitives
    async def get_layer(self, layer: str, key: str) -> Optional[Any]: ...
    async def set_layer(self, layer: str, key: str, value: Any, ttl: int) -> bool: ...
    async def invalidate_layer(self, layer: str, pattern: str) -> int: ...
```

### Data Flow

```
Application / SDK
       │
       ▼
DecisionEngine.decide(DecisionContext)
       │
       ├─→ Evaluates L0: cache_engine.get_layer("L0", key)
       ├─→ Evaluates L1: cache_engine.get_layer("L1", key)
       ├─→ Evaluates L2: cache_engine.get_layer("L2", key) + embedder
       ├─→ Evaluates L3: cache_engine.get_layer("L3", key) + embedder
       ├─→ Evaluates L4: cache_engine.get_layer("L4", key)
       ├─→ Evaluates L5: cache_engine.get_layer("L5", key)
       ├─→ Evaluates L6: cache_engine.get_layer("L6", key)
       ├─→ Evaluates L7: project_memory.query()  (separate component)
       ├─→ Evaluates L8: session_memory.get()    (separate component)
       └─→ Evaluates L9: cache_engine.get_layer("L9", key)
       │
       ▼
ReuseDecision (action, confidence, layer, reasoning, fallback_plan)
       │
       ▼
Application executes decision:
  - EXACT_REUSE/SEMANTIC_REUSE/CONTEXT_REUSE → return cached response
  - MEMORY_RETRIEVAL/RAG_RETRIEVAL → construct prompt, call LLM
  - PARTIAL_RECOMPUTE → execute recompute_plan, cache results
  - FULL_LLM_CALL → generate_fn()
       │
       ▼
CacheEngine writes results to appropriate layers (async)
```

## Consequences

### Positive
- **Clear separation**: Policy (what to reuse) vs Mechanism (where data lives)
- **Backward compatibility**: Existing `CacheEngine.resolve()` continues to work unchanged
- **Testability**: DecisionEngine logic unit-testable without storage backends
- **Extensibility**: New layers registered via `register_layer()` without modifying CacheEngine
- **Observability**: DecisionEngine emits decision events; CacheEngine emits storage events

### Negative
- **Additional abstraction**: One more class to understand
- **Indirection**: DecisionEngine delegates to CacheEngine for storage ops

## Implementation Notes

1. **DecisionEngine does NOT inherit from CacheEngine** — composition over inheritance
2. **CacheEngine remains the single source of truth for storage** — DecisionEngine never writes directly to backends
3. **Single-flight stays in CacheEngine** — DecisionEngine returns decision; CacheEngine handles deduplication on write
4. **L7/L8 are separate components** — DecisionEngine calls `project_memory.query()` and `session_memory.get()`, not `cache_engine.get_layer("L7")`

## Related ADRs

- ADR-001: 10-Layer Cache Hierarchy (defines layers L0-L9)
- ADR-003: Project Memory Architecture (L7)
- ADR-004: Retrieval/Context Cache Separation (L4/L5)
- ADR-005: Hard Gates on CRITICAL_FIELDS
- ADR-006: Confidence-Thresholded Reuse

## Migration from 2.x

2.x code using `CacheEngine.resolve()` continues to work. The sequential L1→L2→L3 logic is preserved as a **legacy evaluation path** inside `CacheEngine.resolve()`. New code should use `DecisionEngine.decide()` for full Phase 3 capabilities.

---
*This ADR resolves blocking condition C2 from the Phase 3 Architecture Review.*