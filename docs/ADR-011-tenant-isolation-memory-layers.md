# ADR-011: Tenant Isolation for L7/L8/L9 Memory Layers

**Status**: ACCEPTED  
**Date**: 2026-10-06  
**Owners**: Agent Memory Engineer, Security Engineer  
**Reviewers**: Architect, Cache Engineer, RAG Engineer, Testing Engineer  

---

## Context

The Phase 3 Architecture Review identified **blocking condition C6**: L7 Project Memory, L8 Session Memory, and L9 LLM Response Cache all lack `tenant_id` in their key specifications, enabling cross-tenant knowledge leakage.

### Current (Vulnerable) Design

| Layer | Current Key | Vulnerability |
|-------|-------------|---------------|
| **L7 Project Memory** | `project_id = hash(repo_url + default_branch)` | Same public repo → same `project_id` across tenants. Tenant A's private repo summaries accessible to Tenant B. |
| **L8 Session Memory** | `session_id + turn_id + scope` | Session IDs not globally unique. Session from Tenant A could be read by Tenant B if IDs collide. |
| **L9 LLM Response Cache** | `hash(full_prompt + model + provider + params + prompt_version)` | No tenant scoping. Response for Tenant A could be served to Tenant B. |

### Security Review Findings (SECURITY_REVIEW_PHASE3.md)

- **CRITICAL Finding #1**: L7/L8/L9 keys lack `tenant_id`
- **CRITICAL Finding #2**: L7 `project_id` not tenant-scoped
- **CRITICAL Finding #7**: No user/session isolation in L8/L9
- **Ambiguity E (Architecture Review)**: L8 injects context into prompt → L9 caches full prompt. Same prompt from different sessions could hit L9 incorrectly.

---

## Decision

### L7 Project Memory — Key Specification

```python
@dataclass
class ProjectMemory:
    # NEW: Tenant-scoped project ID
    project_id: str = hash(tenant_id + repo_url + default_branch)
    
    # Required for authorization
    tenant_id: str
    repo_url: str
    default_branch: str
    commit_sha: str
    # ... rest unchanged
```

**Key Format**: `l7:{tenant_id}:{project_id}:{file_hash}:{symbol_path}`

**Authorization Requirements**:
1. **Write path**: Ingestion request must include valid API key for `tenant_id`. Verify tenant has explicit grant for `repo_url` (allowlist or OAuth token scope).
2. **Read path**: Query must include `tenant_id` and `project_id`. Verify `hash(tenant_id + repo_url + default_branch) == project_id` before returning data.
3. **Cross-tenant access**: Explicitly denied. No shared project memory across tenants even for public repos.

### L8 Session Memory — Key Specification

```python
@dataclass
class SessionMemory:
    # NEW: Fully scoped session key
    tenant_id: str
    user_id: str          # Required for multi-user tenants
    session_id: str       # Unique within (tenant_id, user_id)
    turn_id: int
    scope: Literal["facts", "preferences", "history", "context"]
    consent_version: str  # Track consent policy version
```

**Key Format**: `l8:{tenant_id}:{user_id}:{session_id}:{turn_id}:{scope}`

**Privacy & Consent**:
- Write requires explicit user consent (per-tenant configurable)
- TTL = session timeout (configurable, default 30 min)
- `consent_version` in key → policy change = auto-invalidation
- Explicit revoke endpoint: `DELETE /session/{tenant_id}/{user_id}/{session_id}`

### L9 LLM Response Cache — Key Specification

```python
@dataclass
class LLMResponseCacheKey:
    tenant_id: str
    # Conditional: include if responses are personalized per user/session
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    # Core identity
    full_rendered_prompt_hash: str  # hash of fully assembled prompt
    model: str
    provider: str
    params_hash: str  # hash of temperature, top_p, max_tokens, etc.
    prompt_version: str
    authz_version: str  # Authorization policy version
```

**Key Format**: `l9:{tenant_id}:{user_id?}:{session_id?}:{prompt_hash}:{model}:{provider}:{params_hash}:{prompt_version}:{authz_version}`

**Personalization Rules**:
- **Non-personalized** (default): `user_id` and `session_id` omitted. Response reusable across users in same tenant.
- **Personalized** (opt-in): Include `user_id` and/or `session_id` when response depends on user context (e.g., "my previous analysis", user-specific data).
- Decision Engine determines personalization via `DecisionContext.personalized_response` flag.

---

## Memory Isolation Model

### Isolation Hierarchy

```
Tenant (tenant_id)
    └── User (user_id) — for multi-user tenants
        └── Session (session_id) — ephemeral, consent-scoped
            └── Project (project_id) — tenant-scoped, repo-bound
```

### Cross-Layer Isolation Guarantees

| Layer | Tenant Isolation | User Isolation | Session Isolation | Project Isolation |
|-------|------------------|----------------|-------------------|-------------------|
| L7 Project Memory | ✅ `project_id` includes `tenant_id` | ❌ N/A (project-level) | ❌ N/A | ✅ `repo_url + branch` in `project_id` |
| L8 Session Memory | ✅ Key prefix `l8:{tenant_id}:` | ✅ Key includes `user_id` | ✅ Key includes `session_id` | ❌ N/A |
| L9 Response Cache | ✅ Key prefix `l9:{tenant_id}:` | ✅ Optional (personalized) | ✅ Optional (personalized) | ❌ N/A |

### Default Isolation Mode

| Deployment | L7 | L8 | L9 |
|------------|----|----|----|
| **Single-tenant** | Tenant ID in key (single value) | User + Session in key | Tenant ID in key |
| **Multi-tenant** | Required — enforced at write/read | Required — enforced at write/read | Required — enforced at write/read |

**No payload-mode fallback for memory layers**: L7/L8/L9 MUST use tenant-scoped keys. Collection isolation is not sufficient for memory layers because memory is semantically rich and long-lived.

---

## Resolution of L8 → L9 Interaction Risk (Ambiguity E)

### Problem

From PHASE3_ARCHITECTURE_REVIEW.md Ambiguity E:
> L8 injects context into prompt → L9 caches full prompt. Same prompt from different sessions could hit L9 incorrectly.

**Scenario**:
1. Session A (Tenant 1, User 1): L8 retrieves session context → injects into prompt
2. L9 caches full rendered prompt + response
3. Session B (Tenant 1, User 2): Same base query, different session context injected
3. L9 key (without session_id) matches → returns Session A's response to Session B

### Solution

**Option A (Chosen): L9 key includes injected context hash**

```python
def build_l9_key(ctx: DecisionContext, injected_context: Optional[str]) -> str:
    context_hash = hash(injected_context) if injected_context else "none"
    personalized = ctx.personalized_response  # True if L8 context injected
    
    components = [
        ctx.tenant_id,
        ctx.user_id if personalized else "shared",
        ctx.session_id if personalized else "shared",
        hash(ctx.full_rendered_prompt),
        ctx.model,
        ctx.provider,
        hash(ctx.model_params),
        ctx.prompt_version,
        context_hash,  # NEW: binds L9 entry to specific injected context
        ctx.authz_version,
    ]
    return "l9:" + ":".join(components)
```

**Option B (Alternative): L8 feeds L5, not L9**

- L8 session memory → injects into L5 context window cache key
- L9 only caches non-personalized, deterministic responses (temp=0)
- Rejected: L9 is valuable for personalized deterministic responses too (classification, extraction with user context)

### Decision Engine Integration

```python
async def decide(self, ctx: DecisionContext) -> ReuseDecision:
    # ... existing logic ...
    
    # When L8 provides context, mark response as personalized
    if ctx.session_id and await self.session_memory.has_context(ctx.tenant_id, ctx.user_id, ctx.session_id):
        ctx.personalized_response = True
        ctx.injected_context_hash = await self.session_memory.get_context_hash(...)
    
    # L9 lookup uses personalized key
    if decision.action == FULL_LLM_CALL and ctx.supports_l9:
        l9_key = build_l9_key(ctx, ctx.injected_context_hash)
        # ...
```

---

## Updated CRITICAL_FIELDS (Per Security Review Section 14)

| Layer | CRITICAL_FIELDS (Mandatory Hard Gates) |
|-------|----------------------------------------|
| **L7** | `tenant_id`, `project_id`, `commit_sha`, `file_hash`, `embedding_model_version`, `dependency_graph_version` |
| **L8** | `tenant_id`, `user_id`, `session_id`, `consent_version` |
| **L9** | `tenant_id`, `model`, `provider`, `params_hash`, `prompt_version`, `authz_version`, `injected_context_hash` (if personalized) |

---

## Implementation Checklist (for Phase 3 Authorization)

- [ ] Update `ProjectMemory` dataclass with tenant-scoped `project_id`
- [ ] Add authorization check in L7 write path (verify repo grant)
- [ ] Update `SessionMemory` dataclass with `(tenant_id, user_id, session_id)` key
- [ ] Add consent_version tracking and revoke endpoint
- [ ] Update L9 key builder with `tenant_id`, optional `user_id`/`session_id`, `injected_context_hash`
- [ ] Add `personalized_response` flag to `DecisionContext`
- [ ] Update hard gate validation for L7/L8/L9 with new CRITICAL_FIELDS
- [ ] Add integration tests: cross-tenant isolation for L7/L8/L9
- [ ] Add adversarial test: L8 context injection → L9 false hit prevention

---

## Consequences

### Positive
- **Security**: Cross-tenant leakage eliminated for memory layers
- **Correctness**: L8→L9 interaction risk resolved via context hash binding
- **Compliance**: Supports GDPR/CCPA user data isolation
- **Auditability**: Every memory entry traceable to tenant/user/session

### Negative
- **Storage overhead**: Longer keys, more key variants for personalized L9
- **Complexity**: Personalization logic in Decision Engine
- **Migration**: Existing L7/L8/L9 implementations (when built) must adopt new keys

### Neutral
- No change to L0-L6 key specifications (already include tenant_id per design)
- Collection/payload isolation modes unchanged for vector layers (L2/L3/L4/L7-vectors)

---

## Related Documents

- SECURITY_REVIEW_PHASE3.md (Sections 1, 2, 3, 7, 14)
- PHASE3_ARCHITECTURE_REVIEW.md (Sections 4, 5, 8, 12)
- PHASE3_ARCHITECTURE.md (Sections 2, 4, 5, 10, 14)
- .opencode/agents/agent-memory-engineer.md (Memory vs Cache distinction)

---

## Approval

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Agent Memory Engineer | | | 2026-10-06 |
| Security Engineer | | | 2026-10-06 |
| Architect | | | |
| Cache Engineer | | | |