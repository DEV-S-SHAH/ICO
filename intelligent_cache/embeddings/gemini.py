"""Google Gemini embedding provider."""

import logging
import os
from typing import Any, Optional, Sequence
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


class GeminiEmbedder(BaseEmbedder):
    """Embedder using Google Gemini embeddings API."""

    def __init__(
        self,
        model_name: str = "models/text-embedding-004",
        api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._configured = False
        self._dim: Optional[int] = 768

    def _ensure_configured(self) -> None:
        if self._configured:
            return
        try:
            import google.generativeai as genai
            if self.api_key:
                genai.configure(api_key=self.api_key)
            self._configured = True
        except ImportError as exc:
            raise EmbeddingError(
                "google-generativeai is not installed. Install it via `pip install google-generativeai`"
            ) from exc

    @property
    def dimension(self) -> int:
        return self._dim or 768

    @property
    def name(self) -> str:
        return f"Gemini({self.model_name})"

    def embed(self, text: str) -> list[float]:
        self._ensure_configured()
        import google.generativeai as genai
        try:
            result = genai.embed_content(
                model=self.model_name,
                content=text,
                task_type="retrieval_query",
            )
            embedding = result.get("embedding", [])
            if self._dim != len(embedding) and embedding:
                self._dim = len(embedding)
            return embedding
        except Exception as exc:
            raise EmbeddingError(f"Gemini embedding call failed: {exc}") from exc

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
