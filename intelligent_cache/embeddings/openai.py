"""OpenAI embedding provider."""

import logging
import os
from typing import Any, Optional, Sequence
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


class OpenAIEmbedder(BaseEmbedder):
    """Embedder using OpenAI's embeddings API."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        dimensions: Optional[int] = None,
    ):
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.dimensions = dimensions
        self._client = client
        self._detected_dim = dimensions

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
            return self._client
        except ImportError as exc:
            raise EmbeddingError(
                "openai package is not installed. Install it via `pip install intelligent-cache[openai]`"
            ) from exc
        except Exception as exc:
            raise EmbeddingError(f"Failed to initialize OpenAI client: {exc}") from exc

    @property
    def dimension(self) -> int:
        if self._detected_dim is not None:
            return self._detected_dim
        # Default known dimensions
        if "3-small" in self.model_name:
            return self.dimensions or 1536
        if "3-large" in self.model_name:
            return self.dimensions or 3072
        if "ada-002" in self.model_name:
            return 1536
        # Probe once
        sample = self.embed("test")
        self._detected_dim = len(sample)
        return self._detected_dim

    @property
    def name(self) -> str:
        return f"OpenAI({self.model_name})"

    def embed(self, text: str) -> list[float]:
        client = self._ensure_client()
        kwargs: dict[str, Any] = {"input": text, "model": self.model_name}
        if self.dimensions and "3-" in self.model_name:
            kwargs["dimensions"] = self.dimensions
        try:
            resp = client.embeddings.create(**kwargs)
            vec = resp.data[0].embedding
            if self._detected_dim is None:
                self._detected_dim = len(vec)
            return vec
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding call failed: {exc}") from exc

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        client = self._ensure_client()
        kwargs: dict[str, Any] = {"input": list(texts), "model": self.model_name}
        if self.dimensions and "3-" in self.model_name:
            kwargs["dimensions"] = self.dimensions
        try:
            resp = client.embeddings.create(**kwargs)
            return [item.embedding for item in resp.data]
        except Exception as exc:
            raise EmbeddingError(f"OpenAI batch embedding call failed: {exc}") from exc
