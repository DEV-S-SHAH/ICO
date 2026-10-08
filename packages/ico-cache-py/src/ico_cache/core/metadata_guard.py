"""
metadata_guard.py — Config-driven metadata schema and generic hard-gate logic.

Contains generic MetadataSchema, MetadataField, and hard_gate diffing
independent of any specific domain or dataset vocabulary.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class GateMode(str, Enum):
    """Hard gate evaluation mode. AGGRESSIVE removed per ADR-005."""

    STRICT = "strict"
    BALANCED = "balanced"


class MetadataField(BaseModel):
    name: str
    field_type: Any = str
    extractor: Optional[Callable[[str], Optional[Any]]] = None
    required_in_gate: bool = True
    fuzzy: bool = False  # If True, BALANCED mode allows mismatch with confidence penalty


class MetadataSchema(BaseModel):
    fields: List[MetadataField] = Field(default_factory=list)

    def extract(self, text: str) -> Dict[str, Optional[Any]]:
        result: Dict[str, Optional[Any]] = {}
        for f in self.fields:
            if f.extractor is not None:
                try:
                    result[f.name] = f.extractor(text)
                except Exception:
                    result[f.name] = None
            else:
                result[f.name] = None
        return result

    @property
    def filter_keys(self) -> List[str]:
        return [f.name for f in self.fields if f.required_in_gate]

    @property
    def fuzzy_keys(self) -> List[str]:
        return [f.name for f in self.fields if f.fuzzy]


# CRITICAL_FIELDS per layer — always block on mismatch regardless of GateMode
CRITICAL_FIELDS: Dict[str, List[str]] = {
    "L0a": ["function_version", "input_hash", "env_hash"],
    "L0b": ["embedding_model_version", "text_hash"],
    "L1": ["tenant_id", "model_fingerprint", "provider", "prompt_version", "entity", "quarter", "topic"],
    "L2": ["tenant_id", "model_fingerprint", "embedding_version", "entity", "quarter", "topic", "collection_version", "prompt_version", "context_hash"],
    "L3": ["tenant_id", "model_fingerprint", "embedding_version", "entity", "quarter", "topic", "collection_version", "context_hash", "prompt_version"],
    "L4": ["tenant_id", "collection_version", "filter_hash", "top_k", "embedding_version", "reranker_version"],
    "L5": ["tenant_id", "chunk_content_hashes", "template_version", "token_budget", "model_fingerprint", "provider"],
    "L6": ["tenant_id", "tool_name", "tool_version", "arg_hash", "idempotency_key"],
    "L7": ["tenant_id", "project_id", "commit_sha", "file_hashes", "dependency_graph_version", "embedding_version"],
    "L8": ["tenant_id", "user_id", "session_id", "consent_version"],
    "L9": ["tenant_id", "user_id", "model_fingerprint", "provider", "params_hash", "prompt_version", "authz_version", "injected_context_hash"],
}


def hard_gate(
    meta_in: Dict[str, Any],
    meta_cached: Dict[str, Any],
    filter_keys: Optional[List[str]] = None,
    layer: Optional[str] = None,
    mode: GateMode = GateMode.STRICT,
    fuzzy_fields: Optional[List[str]] = None,
    schema: Optional[MetadataSchema] = None,
) -> bool | Tuple[bool, List[str], List[str]]:
    """
    Extended hard gate with CRITICAL_FIELDS and GateMode support.

    Returns:
        - If called with only basic args (backward compat): bool
        - If called with extended args: Tuple (allowed, gates_passed, gates_failed)

    - STRICT: All metadata field differences block the hit
    - BALANCED: Non-FUZZY field differences block; FUZZY fields allow with confidence penalty
    - CRITICAL_FIELDS always block regardless of mode
    """
    # Check if extended parameters are provided
    is_extended = (
        layer is not None
        or mode != GateMode.STRICT
        or fuzzy_fields is not None
        or schema is not None
    )

    critical = CRITICAL_FIELDS.get(layer, []) if layer else []
    fuzzy = set(fuzzy_fields or [])
    if schema:
        fuzzy.update(f.name for f in schema.fields if f.fuzzy)

    passed = []
    failed = []

    keys = filter_keys if filter_keys is not None else list(set(meta_in.keys()).union(meta_cached.keys()))
    # Always include critical fields in check
    all_keys = set(keys).union(critical)

    for key in all_keys:
        v_in = meta_in.get(key)
        v_cached = meta_cached.get(key)

        is_critical = key in critical
        is_fuzzy = key in fuzzy

        if v_in is not None and v_cached is not None and v_in != v_cached:
            # Mismatch — check if it's a critical field or non-fuzzy
            if is_critical or mode == GateMode.STRICT or (mode == GateMode.BALANCED and not is_fuzzy):
                failed.append(key)
            else:
                # BALANCED mode with fuzzy field — allow with penalty
                passed.append(f"{key}(fuzzy)")
        elif v_in is not None or v_cached is not None:
            # One side has value, other doesn't — pass but note
            passed.append(key)
        else:
            # Both None — pass
            passed.append(key)

    allowed = len(failed) == 0

    if is_extended:
        return allowed, passed, failed
    return allowed


def hard_gate_simple(
    meta_in: Dict[str, Any],
    meta_cached: Dict[str, Any],
    filter_keys: Optional[List[str]] = None,
) -> bool:
    """
    Legacy simple hard gate for backward compatibility.
    Returns True if allowed, False if blocked.
    """
    # Use a dummy layer to force extended mode return tuple
    allowed, _, _ = hard_gate(meta_in, meta_cached, filter_keys, layer="__simple__", mode=GateMode.STRICT)  # type: ignore[misc]
    return allowed


class MetadataConfig:
    """Thin wrapper retained for backward compatibility."""

    def __init__(self, filter_keys: Optional[List[str]] = None, schema: Optional[MetadataSchema] = None):
        self.schema = schema or MetadataSchema()
        self.filter_keys = filter_keys or self.schema.filter_keys

    def extract(self, text: str, user_metadata: Optional[dict] = None) -> dict:
        auto = self.schema.extract(text)
        merged = {k: v for k, v in auto.items() if v is not None}
        if user_metadata:
            merged.update(user_metadata)
        return merged
