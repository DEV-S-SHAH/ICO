from abc import ABC, abstractmethod
from typing import List, Any, Optional

class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> List[float]:
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

    def delete_collection(self, collection: str):
        pass

    async def delete_matching(self, collection: str, filter_dict: Optional[dict] = None) -> int:
        return 0

class BaseExactStore(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def set(self, key: str, value: bytes, ex: Optional[int] = None):
        pass

    def delete_prefix(self, prefix: str) -> int:
        return 0

