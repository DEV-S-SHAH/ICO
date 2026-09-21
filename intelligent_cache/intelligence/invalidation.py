"""Cache invalidation manager."""

import logging
from typing import Optional
from intelligent_cache.backends.base import BaseStorageBackend
from intelligent_cache.core.key import generate_key
from intelligent_cache.embeddings.base import BaseEmbedder

logger = logging.getLogger(__name__)


class InvalidationManager:
    """Manages cache invalidations across keys, namespaces, tags, and semantic radii."""

    def __init__(self, backend: BaseStorageBackend, embedder: BaseEmbedder):
        self.backend = backend
        self.embedder = embedder

    def invalidate(
        self,
        key: Optional[str] = None,
        query: Optional[str] = None,
        namespace: Optional[str] = None,
        tag: Optional[str] = None,
        semantic_query: Optional[str] = None,
        radius: float = 0.85,
    ) -> int:
        """Invalidate entries matching any of the specified criteria.
        
        Returns:
            Total count of deleted entries.
        """
        deleted = 0

        # Exact key
        if key is not None:
            if self.backend.delete(key):
                deleted += 1

        # Query text (generates exact key in namespace)
        if query is not None:
            ns = namespace or "default"
            exact_key = generate_key(query, namespace=ns)
            if self.backend.delete(exact_key):
                deleted += 1

        # Namespace
        if namespace is not None and key is None and query is None and semantic_query is None and tag is None:
            deleted += self.backend.invalidate_namespace(namespace)

        # Tag
        if tag is not None:
            deleted += self.backend.invalidate_tag(tag)

        # Semantic radius
        if semantic_query is not None:
            vec = self.embedder.embed(semantic_query)
            deleted += self.backend.invalidate_semantic(
                query_vector=vec,
                radius=radius,
                namespace=namespace,
            )

        return deleted
