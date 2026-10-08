"""Vector store integration supporting LanceDB and Qdrant."""

import hashlib
import json
from typing import Any, Dict, List, Optional
from ico_cache.backends.base import BaseVectorStore
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.vector.qdrant_store import QdrantStore
from .config import DemoConfig


class RAGVectorStore:
    """Manages document vectors and metadata using ICO-Cache supported vector backends."""

    def __init__(self, config: DemoConfig):
        self.config = config
        self.collection_name = config.collection_name
        self.db_type = config.vector_db_type

        if self.db_type == "qdrant":
            self.backend: BaseVectorStore = QdrantStore(
                host=config.qdrant_host,
                port=config.qdrant_port,
            )
        else:
            self.backend = LanceDBStore(uri=config.lancedb_uri)

    def _id_to_int(self, chunk_id: str) -> int:
        """Derive 64-bit int ID from chunk_id string."""
        digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)

    async def insert_chunks(self, chunks: List[Dict[str, Any]], vectors: List[List[float]], tenant_id: str = "default"):
        """Store chunk vectors and complete source metadata."""
        coll = f"{tenant_id}_{self.collection_name}" if tenant_id != "default" else self.collection_name
        for chunk, vector in zip(chunks, vectors):
            point_id = self._id_to_int(chunk["chunk_id"])
            payload = {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "filename": chunk["filename"],
                "page": chunk["page"],
                "content_hash": chunk["content_hash"],
                "corpus_version": chunk["corpus_version"],
                "text": chunk["text"],
            }
            await self.backend.insert(
                collection=coll,
                id=point_id,
                vector=vector,
                payload=payload,
            )

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        corpus_version: Optional[str] = None,
        tenant_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """Search vector store and return chunks with full source metadata."""
        coll = f"{tenant_id}_{self.collection_name}" if tenant_id != "default" else self.collection_name

        query_filter = None
        if corpus_version:
            query_filter = {"corpus_version": corpus_version}

        try:
            results = await self.backend.search(
                collection=coll,
                vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=0.0,
            )
        except Exception:
            # Fallback without filter if collection was created flatly
            results = await self.backend.search(
                collection=coll,
                vector=query_vector,
                query_filter=None,
                limit=top_k,
                score_threshold=0.0,
            )

        formatted: List[Dict[str, Any]] = []
        for r in results:
            payload = getattr(r, "payload", None)
            if payload is None and isinstance(r, dict):
                payload = r.get("payload", r)

            if payload:
                # Filter by corpus_version if needed
                if corpus_version and payload.get("corpus_version") != corpus_version:
                    continue

                item = dict(payload)
                if hasattr(r, "score"):
                    item["score"] = float(r.score)
                elif isinstance(r, dict) and "score" in r:
                    item["score"] = float(r["score"])
                elif isinstance(r, dict) and "_distance" in r:
                    item["score"] = 1.0 - float(r["_distance"])
                else:
                    item["score"] = 1.0

                formatted.append(item)

        return formatted[:top_k]

    async def insert_l2_cache(
        self,
        query: str,
        vector: List[float],
        answer: str,
        sources: List[Dict[str, Any]],
        corpus_version: str,
        model: str,
        provider: str,
        tenant_id: str = "default",
    ):
        """Insert a generated answer vector and metadata into L2 semantic response cache."""
        coll = f"{tenant_id}_l2_responses" if tenant_id != "default" else "l2_responses"
        point_id = self._id_to_int(f"l2_{tenant_id}_{query}_{corpus_version}_{model}")
        payload = {
            "query": query,
            "answer": answer,
            "sources": sources,
            "corpus_version": corpus_version,
            "model": model,
            "provider": provider,
            "tenant_id": tenant_id,
        }
        await self.backend.insert(
            collection=coll,
            id=point_id,
            vector=vector,
            payload=payload,
        )

    async def search_l2_cache(
        self,
        query_vector: List[float],
        min_score: float = 0.85,
        corpus_version: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        tenant_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Search L2 semantic cache with cosine similarity and hard gate validation."""
        coll = f"{tenant_id}_l2_responses" if tenant_id != "default" else "l2_responses"
        try:
            results = await self.backend.search(
                collection=coll,
                vector=query_vector,
                limit=3,
                score_threshold=0.0,
            )
        except Exception:
            return None

        for r in results:
            payload = getattr(r, "payload", None)
            if payload is None and isinstance(r, dict):
                payload = r.get("payload", r)
            if not payload:
                continue

            score = 1.0
            if hasattr(r, "score") and r.score is not None:
                score = float(r.score)
            elif isinstance(r, dict) and "score" in r and r["score"] is not None:
                score = float(r["score"])
            elif isinstance(r, dict) and "_distance" in r and r["_distance"] is not None:
                score = 1.0 - float(r["_distance"])

            if score < min_score:
                continue

            # Hard gate verification: tenant, corpus version, model, provider
            if payload.get("tenant_id", "default") != tenant_id:
                continue
            if corpus_version and payload.get("corpus_version") != corpus_version:
                continue
            if model and payload.get("model") != model:
                continue
            if provider and payload.get("provider") != provider:
                continue

            sources = payload.get("sources", [])
            if isinstance(sources, str):
                try:
                    sources = json.loads(sources)
                except Exception:
                    sources = []

            return {
                "answer": payload.get("answer", ""),
                "sources": sources,
                "score": score,
                "cached_query": payload.get("query", ""),
                "corpus_version": payload.get("corpus_version"),
            }

        return None

    async def insert_l3_cache(
        self,
        query: str,
        query_vector: List[float],
        context: str,
        context_vector: List[float],
        answer: str,
        sources: List[Dict[str, Any]],
        corpus_version: str,
        model: str,
        provider: str,
        tenant_id: str = "default",
    ):
        """Insert a context-aware entry into L3 cache."""
        coll = f"{tenant_id}_l3_responses" if tenant_id != "default" else "l3_responses"
        point_id = self._id_to_int(f"l3_{tenant_id}_{query}_{context}_{corpus_version}_{model}")
        payload = {
            "query": query,
            "context": context,
            "context_vector": context_vector,
            "answer": answer,
            "sources": sources,
            "corpus_version": corpus_version,
            "model": model,
            "provider": provider,
            "tenant_id": tenant_id,
        }
        await self.backend.insert(
            collection=coll,
            id=point_id,
            vector=query_vector,
            payload=payload,
        )

    async def search_l3_cache(
        self,
        query_vector: List[float],
        context_vector: List[float],
        min_query_score: float = 0.85,
        min_context_score: float = 0.80,
        corpus_version: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        tenant_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Search L3 context-aware cache with dual-vector scoring."""
        coll = f"{tenant_id}_l3_responses" if tenant_id != "default" else "l3_responses"
        try:
            results = await self.backend.search(
                collection=coll,
                vector=query_vector,
                limit=5,
                score_threshold=0.0,
            )
        except Exception:
            return None

        def _cosine(v1, v2):
            if not v1 or not v2 or len(v1) != len(v2):
                return 0.0
            dot = sum(a * b for a, b in zip(v1, v2))
            norm1 = sum(a * a for a in v1) ** 0.5
            norm2 = sum(b * b for b in v2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)

        for r in results:
            payload = getattr(r, "payload", None)
            if payload is None and isinstance(r, dict):
                payload = r.get("payload", r)
            if not payload:
                continue

            q_score = 1.0
            if hasattr(r, "score") and r.score is not None:
                q_score = float(r.score)
            elif isinstance(r, dict) and "score" in r and r["score"] is not None:
                q_score = float(r["score"])
            elif isinstance(r, dict) and "_distance" in r and r["_distance"] is not None:
                q_score = 1.0 - float(r["_distance"])

            if q_score < min_query_score:
                continue

            # Hard gate verification: tenant, corpus version, model, provider
            if payload.get("tenant_id", "default") != tenant_id:
                continue
            if corpus_version and payload.get("corpus_version") != corpus_version:
                continue
            if model and payload.get("model") != model:
                continue
            if provider and payload.get("provider") != provider:
                continue

            cached_c_vec = payload.get("context_vector")
            if isinstance(cached_c_vec, str):
                try:
                    cached_c_vec = json.loads(cached_c_vec)
                except Exception:
                    cached_c_vec = []
            c_score = _cosine(context_vector, cached_c_vec)
            if c_score < min_context_score:
                continue

            sources = payload.get("sources", [])
            if isinstance(sources, str):
                try:
                    sources = json.loads(sources)
                except Exception:
                    sources = []

            combined_score = round(0.5 * q_score + 0.5 * c_score, 4)
            return {
                "answer": payload.get("answer", ""),
                "sources": sources,
                "score": combined_score,
                "query_score": q_score,
                "context_score": c_score,
                "cached_query": payload.get("query", ""),
                "cached_context": payload.get("context", ""),
                "corpus_version": payload.get("corpus_version"),
            }

        return None