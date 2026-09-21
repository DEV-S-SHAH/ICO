"""Factory for resolving and instantiating embedders."""

import logging
from typing import Any, Callable, Optional, Union
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.embeddings.default import DefaultEmbedder

logger = logging.getLogger(__name__)


def create_embedder(
    embedder: Union[str, BaseEmbedder, Callable[[str], list[float]], None] = "default",
    model_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseEmbedder:
    """Create or resolve an embedder instance.
    
    Args:
        embedder: Can be:
            - 'default': Fast zero-dependency feature hashing embedder
            - 'sentence-transformers' / 'local': SentenceTransformers model
            - 'openai': OpenAI embeddings API
            - 'gemini': Google Gemini embeddings API
            - An instance of BaseEmbedder
            - A callable: (text: str) -> list[float]
        model_name: Optional model name override.
        kwargs: Additional arguments passed to embedder constructor.
    """
    if embedder is None or embedder == "default":
        dim = kwargs.get("dimension", 256)
        return DefaultEmbedder(dimension=dim)

    if isinstance(embedder, BaseEmbedder):
        return embedder

    if callable(embedder):
        from intelligent_cache.embeddings.custom import CustomEmbedder
        return CustomEmbedder(embedder, **kwargs)

    if isinstance(embedder, str):
        embedder_lower = embedder.lower().strip()

        if embedder_lower in ("default", "fast", "hash"):
            dim = kwargs.get("dimension", 256)
            return DefaultEmbedder(dimension=dim)

        if embedder_lower in ("sentence-transformers", "sentence_transformers", "st", "local"):
            try:
                from intelligent_cache.embeddings.sentence_transformers import SentenceTransformerEmbedder
                return SentenceTransformerEmbedder(
                    model_name=model_name or "all-MiniLM-L6-v2",
                    **kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "Could not load SentenceTransformerEmbedder (%s). Falling back to DefaultEmbedder.",
                    exc,
                )
                return DefaultEmbedder()

        if embedder_lower == "openai":
            try:
                from intelligent_cache.embeddings.openai import OpenAIEmbedder
                return OpenAIEmbedder(
                    model_name=model_name or "text-embedding-3-small",
                    **kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "Could not load OpenAIEmbedder (%s). Falling back to DefaultEmbedder.",
                    exc,
                )
                return DefaultEmbedder()

        if embedder_lower in ("gemini", "google"):
            try:
                from intelligent_cache.embeddings.gemini import GeminiEmbedder
                return GeminiEmbedder(
                    model_name=model_name or "models/text-embedding-004",
                    **kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "Could not load GeminiEmbedder (%s). Falling back to DefaultEmbedder.",
                    exc,
                )
                return DefaultEmbedder()

    # Fallback
    logger.warning("Unrecognized embedder '%s'. Using DefaultEmbedder.", embedder)
    return DefaultEmbedder()
