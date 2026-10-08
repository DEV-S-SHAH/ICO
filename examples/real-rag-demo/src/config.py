"""Configuration for Real-World RAG Demo."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DemoConfig:
    # Documents & Ingestion
    documents_dir: str = os.getenv(
        "DOCUMENTS_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents")
    )
    data_dir: str = os.getenv(
        "DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    )
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "500"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "50"))

    # Vector store
    vector_db_type: str = os.getenv("VECTOR_DB_TYPE", "lancedb").lower()  # "lancedb" or "qdrant"
    lancedb_uri: str = os.getenv("LANCEDB_URI", "")
    qdrant_host: str = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))
    collection_name: str = os.getenv("COLLECTION_NAME", "rag_corpus")

    # Exact store (for L1, L4, L5)
    exact_store_type: str = os.getenv("EXACT_STORE_TYPE", "sqlite").lower()  # "sqlite" or "redis"
    sqlite_path: str = os.getenv("SQLITE_PATH", "")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD", None)

    # Embeddings
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "fastembed")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")  # "mock", "gemini", "openai", "ollama"
    llm_model: str = os.getenv("LLM_MODEL", "gemini-1.5-flash")
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY", None)
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY", None)
    openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL", None)

    # Cache parameters
    semantic_threshold: float = float(os.getenv("SEMANTIC_THRESHOLD", "0.85"))
    l1_ttl: int = int(os.getenv("L1_TTL", "3600"))
    l4_ttl: int = int(os.getenv("L4_TTL", "3600"))
    default_tenant: str = os.getenv("DEFAULT_TENANT", "default")
    top_k: int = int(os.getenv("TOP_K", "5"))

    # Server
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    def __post_init__(self):
        os.makedirs(self.data_dir, exist_ok=True)
        if not self.lancedb_uri:
            self.lancedb_uri = os.path.join(self.data_dir, "lancedb")
        if not self.sqlite_path:
            self.sqlite_path = os.path.join(self.data_dir, "cache.db")

config = DemoConfig()
RAGConfig = DemoConfig