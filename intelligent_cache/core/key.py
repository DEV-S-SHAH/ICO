"""Key generation and normalization utilities."""

import hashlib
import json
from typing import Any, Optional


def normalize_query(query: str) -> str:
    """Normalize query text for deterministic exact matching.
    
    Lowers casing and collapses consecutive whitespace.
    """
    if not isinstance(query, str):
        query = str(query)
    normalized = " ".join(query.lower().strip().split())
    return normalized


def _json_serializable(obj: Any) -> Any:
    """Helper to convert arbitrary objects to JSON serializable structures."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _json_serializable(v) for k, v in sorted(obj.items())}
    if hasattr(obj, "__dict__"):
        return _json_serializable(vars(obj))
    return str(obj)


def generate_key(
    query: str,
    namespace: str = "default",
    extra_params: Optional[dict[str, Any]] = None,
) -> str:
    """Generate a deterministic SHA-256 cache key for a query."""
    normalized = normalize_query(query)
    payload: dict[str, Any] = {
        "ns": namespace,
        "q": normalized,
    }
    if extra_params:
        payload["extra"] = _json_serializable(extra_params)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest[:32]}"


def generate_tool_key(
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    namespace: str = "tools",
) -> str:
    """Generate a deterministic cache key for an agent tool or function call."""
    payload = {
        "tool": tool_name,
        "args": _json_serializable(args),
        "kwargs": _json_serializable(kwargs),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{tool_name}:{digest[:32]}"


def generate_embedding_key(text: str, model_name: str = "default") -> str:
    """Generate a cache key for embedding vectors."""
    payload = {
        "model": model_name,
        "text": text,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"emb:{model_name}:{digest[:32]}"
