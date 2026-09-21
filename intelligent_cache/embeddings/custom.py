"""Custom user-provided embedder wrapper."""

from typing import Callable, Optional, Sequence
from intelligent_cache.embeddings.base import BaseEmbedder


class CustomEmbedder(BaseEmbedder):
    """Wraps any user-defined embedding callable into a BaseEmbedder."""

    def __init__(
        self,
        embed_fn: Callable[[str], list[float]],
        dimension: Optional[int] = None,
        name: str = "CustomEmbedder",
    ):
        self._embed_fn = embed_fn
        self._custom_name = name
        if dimension is not None:
            self._dim = dimension
        else:
            sample = embed_fn("test")
            self._dim = len(sample)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return self._custom_name

    def embed(self, text: str) -> list[float]:
        return self._embed_fn(text)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_fn(t) for t in texts]
