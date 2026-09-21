"""SentenceTransformers embedding provider."""

import logging
from typing import Optional, Sequence
from intelligent_cache.embeddings.base import BaseEmbedder
from intelligent_cache.exceptions import EmbeddingError

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedder(BaseEmbedder):
    """Embedder using the sentence-transformers library."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: Optional[str] = None):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._dimension: Optional[int] = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._dimension = self._model.get_sentence_embedding_dimension()
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed. Install it via `pip install sentence-transformers` "
                "or `pip install intelligent-cache[sentence-transformers]`"
            ) from exc
        except Exception as exc:
            raise EmbeddingError(f"Failed to load SentenceTransformer '{self.model_name}': {exc}") from exc

    @property
    def dimension(self) -> int:
        self._ensure_model()
        return self._dimension or 384

    @property
    def name(self) -> str:
        return f"SentenceTransformer({self.model_name})"

    def embed(self, text: str) -> list[float]:
        self._ensure_model()
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        self._ensure_model()
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return vecs.tolist() if hasattr(vecs, "tolist") else [list(v) for v in vecs]
