import hashlib
import math
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SRC_DIR = os.path.join(REPO_ROOT, "packages/ico-cache-py/src")
DEMO_DIR = os.path.join(REPO_ROOT, "apps/financial-rag-demo")
for _p in (REPO_ROOT, SRC_DIR, DEMO_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The demo API no longer ships default credentials; production must provision
# API_KEYS explicitly. Tests run against these fixture keys, set before any test
# module imports api/config.py.
os.environ.setdefault(
    "API_KEYS",
    '{"dev-key-default": "default", "key-tenant-a": "tenant_a", "key-tenant-b": "tenant_b"}',
)

# Keep ingestion tests off the production ingest root.
os.environ.setdefault("INGEST_ROOT_DIR", tempfile.mkdtemp(prefix="ico_ingest_"))


class FakeEmbedder:
    """
    Deterministic, dependency-free 384-dim embedder.

    Identical text always maps to the identical unit vector, so tests exercise
    the real cache paths (LanceDB/SQLite) without downloading an ONNX model or
    touching the network. Distinct texts map to near-orthogonal vectors.
    """

    dim = 384

    def embed(self, text: str):
        digest = hashlib.sha256(text.encode()).digest()
        raw = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def engine(tmp_path):
    """Service-free CacheEngine backed by embedded LanceDB + SQLite."""
    from ico_cache.core.cache_engine import CacheEngine
    from ico_cache.backends.vector.lancedb_store import LanceDBStore
    from ico_cache.backends.exact.sqlite_store import SQLiteStore

    return CacheEngine(
        embedder=FakeEmbedder(),
        vector_store=LanceDBStore(uri=str(tmp_path / "lancedb")),
        exact_store=SQLiteStore(db_path=str(tmp_path / "cache.db")),
        lookup_timeout=1.0,
    )
