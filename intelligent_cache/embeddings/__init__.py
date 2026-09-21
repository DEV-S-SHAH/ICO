"""Embeddings subpackage for intelligent_cache."""

from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.embeddings.default import DefaultEmbedder
from intelligent_cache.embeddings.factory import create_embedder

__all__ = [
    "BaseEmbedder",
    "DefaultEmbedder",
    "create_embedder",
]
