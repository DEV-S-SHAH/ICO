"""
metadata_guard.py — Config-driven metadata schema and generic hard-gate logic.

Contains generic MetadataSchema, MetadataField, and hard_gate diffing
independent of any specific domain or dataset vocabulary.
"""

from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class MetadataField(BaseModel):
    name: str
    field_type: Any = str
    extractor: Optional[Callable[[str], Optional[Any]]] = None
    required_in_gate: bool = True


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


def hard_gate(
    meta_in: Dict[str, Any],
    meta_cached: Dict[str, Any],
    filter_keys: Optional[List[str]] = None,
) -> bool:
    """
    Generic hard gate:
    Returns True  → allow similarity result through (possible hit).
    Returns False → block immediately (forced MISS).

    A field blocks a hit when BOTH sides have a non-None value for that field
    AND those values differ. If either side is None, the gate passes for that
    field.
    """
    keys = filter_keys if filter_keys is not None else list(set(meta_in.keys()).union(meta_cached.keys()))
    for key in keys:
        v_in = meta_in.get(key)
        v_cached = meta_cached.get(key)
        if v_in is not None and v_cached is not None and v_in != v_cached:
            return False
    return True


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
