from abc import ABC, abstractmethod
from typing import List, Any, Optional


class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        pass

    @property
    @abstractmethod
    def model_version(self) -> str:
        """
        Return a version string that uniquely identifies this embedding model.

        Must change when model weights, architecture, tokenizer, or configuration changes.
        Used for L0b embedding cache key to prevent cross-version reuse.

        Example: "BAAI/bge-small-en-v1.5@1.0.0" or "text-embedding-3-small@2024-01-01"
        """
        pass


class BaseVectorStore(ABC):
    @abstractmethod
    async def insert(self, collection: str, id: int, vector: Any, payload: dict):
        pass

    @abstractmethod
    async def search(self, collection: str, vector: Any, query_filter: Any, limit: int, score_threshold: float, using: Optional[str] = None, **kwargs: Any) -> List[Any]:
        pass

    @abstractmethod
    async def delete(self, collection: str, id: int):
        pass

    @abstractmethod
    def collection_exists(self, collection: str) -> bool:
        pass

    @abstractmethod
    def create_collection(self, collection: str, config: Any):
        pass

    @abstractmethod
    async def get_vectors(self, collection: str, ids: List[int]) -> List[Optional[List[float]]]:
        pass

    def delete_collection(self, collection: str):
        pass

    async def delete_matching(self, collection: str, filter_dict: Optional[dict] = None) -> int:
        return 0

class BaseExactStore(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def set(self, key: str, value: bytes, ex: Optional[int] = None, nx: bool = False):
        pass

    def delete_prefix(self, prefix: str) -> int:
        return 0

