import asyncio
import threading
from typing import List, Any, Optional
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance
from ..base import BaseVectorStore

class QdrantStore(BaseVectorStore):
    def __init__(self, host: str = "localhost", port: int = 6333):
        self.host = host
        self.port = port
        self.qc = QdrantClient(host, port=port, check_compatibility=False)
        self._local = threading.local()

    @property
    def aqc(self) -> AsyncQdrantClient:
        if not hasattr(self._local, "client"):
            self._local.client = AsyncQdrantClient(self.host, port=self.port, check_compatibility=False)
        return self._local.client

    async def insert(self, collection: str, id: int, vector: Any, payload: dict):
        await self.aqc.upsert(
            collection_name=collection,
            points=[{
                "id": id,
                "vector": vector,
                "payload": payload
            }]
        )

    async def search(self, collection: str, vector: Any, query_filter: Any, limit: int, score_threshold: float, using: Optional[str] = None, **kwargs: Any) -> List[Any]:
        # Use the async client so the event loop is never blocked by network I/O.
        if using:
            res = await self.aqc.query_points(
                collection_name=collection,
                query=vector,
                using=using,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        else:
            res = await self.aqc.query_points(
                collection_name=collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )
        return res.points

    async def delete(self, collection: str, id: int):
        await self.aqc.delete(collection_name=collection, points_selector=[id])

    def collection_exists(self, collection: str) -> bool:
        return self.qc.collection_exists(collection)

    def create_collection(self, collection: str, config: Any = None):
        if config is None:
            config = VectorParams(size=384, distance=Distance.COSINE)
        elif isinstance(config, dict):
            # parse custom dict to VectorParams
            new_config = {}
            for k, v in config.items():
                if isinstance(v, dict):
                    new_config[k] = VectorParams(size=v["size"], distance=Distance.COSINE)
                else:
                    new_config[k] = v
            config = new_config
        self.qc.create_collection(collection, vectors_config=config)

    def delete_collection(self, collection: str):
        if self.qc.collection_exists(collection):
            self.qc.delete_collection(collection)

    async def delete_matching(self, collection: str, filter_dict: Optional[dict] = None) -> int:
        if not await asyncio.to_thread(self.qc.collection_exists, collection):
            return 0
        from qdrant_client.http import models
        if not filter_dict:
            await asyncio.to_thread(self.qc.delete_collection, collection)
            return -1
        conditions = []
        for k, v in filter_dict.items():
            field_key = f"meta.{k}" if (not k.startswith("meta.") and k != "tenant_id" and k != "doc_id") else k
            conditions.append(models.FieldCondition(key=field_key, match=models.MatchValue(value=v)))
        q_filter = models.Filter(must=conditions)
        await self.aqc.delete(collection_name=collection, points_selector=models.FilterSelector(filter=q_filter))
        return len(conditions)

    async def get_vectors(self, collection: str, ids: List[int]) -> List[Optional[List[float]]]:
        """Get vectors by IDs from a collection."""
        if not await asyncio.to_thread(self.qc.collection_exists, collection):
            return [None] * len(ids)
        results = []
        for id_val in ids:
            try:
                res = await self.aqc.retrieve(collection_name=collection, ids=[id_val], with_vectors=True)
                if res:
                    results.append(res[0].vector)
                else:
                    results.append(None)
            except Exception:
                results.append(None)
        return results

