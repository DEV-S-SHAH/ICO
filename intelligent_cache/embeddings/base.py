"""Base embedder interface for semantic caching."""

from abc import ABC, abstractmethod
from typing import Sequence


class BaseEmbedder(ABC):
    """Abstract base class for all embedding generators."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text."""
        raise NotImplementedError

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts."""
        return [self.embed(t) for t in texts]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        """Return the name or identifier of the embedder."""
        return self.__class__.__name__
