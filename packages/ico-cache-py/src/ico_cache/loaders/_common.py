"""Shared helpers for document loaders (chunk/metadata construction)."""
from typing import Any, Dict, List, Optional

from .base import Chunk
from ..core.metadata_guard import MetadataSchema


def build_metadata(
    source_file: str,
    text: str,
    schema: Optional[MetadataSchema] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"source_file": source_file}
    if extra:
        meta.update(extra)
    if schema:
        try:
            extracted = schema.extract(text)
            meta.update({k: v for k, v in extracted.items() if v is not None})
        except Exception:
            pass
    return meta


def make_chunk(
    text: str,
    source_file: str,
    page_or_section: str,
    chunk_index: int,
    loader_type: str,
    schema: Optional[MetadataSchema] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Chunk:
    return Chunk(
        text=text,
        source_file=source_file,
        page_or_section=page_or_section,
        chunk_index=chunk_index,
        loader_type=loader_type,
        metadata=build_metadata(source_file, text, schema, extra),
    )


def coalesce(values: List[str], max_chars: int) -> List[str]:
    """Group consecutive strings into blocks of at most ``max_chars`` characters."""
    blocks: List[str] = []
    current: List[str] = []
    current_len = 0
    for value in values:
        if current and current_len + len(value) > max_chars:
            blocks.append("\n".join(current))
            current = [value]
            current_len = len(value)
        else:
            current.append(value)
            current_len += len(value) + 1
    if current:
        blocks.append("\n".join(current))
    return blocks
