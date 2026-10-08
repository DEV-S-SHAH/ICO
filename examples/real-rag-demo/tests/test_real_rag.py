"""Comprehensive integration and unit tests for Real-world RAG Demo."""

import os
import shutil
import sys
import tempfile
import pytest
from pathlib import Path

# Add real-rag-demo and repo root to sys.path
_DEMO_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_ROOT.parent.parent
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))
if str(_REPO_ROOT / "packages" / "ico-cache-py" / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "packages" / "ico-cache-py" / "src"))

from src.config import DemoConfig
from src.ingest import DocumentIngestion, compute_content_hash
from src.embeddings import CachedEmbedder
from src.vectorstore import RAGVectorStore
from src.retriever import RAGRetriever
from src.rag_graph import LangGraphRAG
from src.api import create_demo_app
from scripts.generate_sample_papers import build_paper


@pytest.fixture
def temp_rag_env():
    """Create isolated temporary environment for RAG tests."""
    temp_dir = tempfile.mkdtemp()
    docs_dir = Path(temp_dir) / "documents"
    data_dir = Path(temp_dir) / "data"
    docs_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Generate sample paper
    pdf_path = docs_dir / "test_paper.pdf"
    build_paper(
        str(pdf_path),
        "Test Paper on Multi-Layered Cache Engineering",
        "Alice Smith, Bob Jones",
        "This paper introduces multi-layered caching for generative AI systems. Caching reduces inference latency and API cost drastically.",
        [
            ("Introduction", "Large Language Models require substantial computation. Context caching and retrieval caching enable significant savings across multi-turn interactions."),
            ("Conclusion", "Multi-tiered caching achieves up to 80% cost reduction while strictly preserving source provenance and factual correctness.")
        ]
    )

    config = DemoConfig(
        documents_dir=str(docs_dir),
        data_dir=str(data_dir),
        lancedb_uri=str(data_dir / "lance"),
        sqlite_path=str(data_dir / "cache.db"),
        embedding_provider="fastembed",
        vector_db_type="lancedb",
        llm_provider="mock",
    )

    yield {"config": config, "docs_dir": docs_dir, "data_dir": data_dir, "pdf_path": pdf_path}

    shutil.rmtree(temp_dir, ignore_errors=True)


class TestIngestionAndCorpusVersioning:
    """Test PDF ingestion, metadata schema, and deterministic corpus versioning."""

    def test_pdf_ingestion_and_metadata(self, temp_rag_env):
        config = temp_rag_env["config"]
        ingestion = DocumentIngestion(config.documents_dir)
        chunks, corpus_ver = ingestion.extract_chunks()

        assert len(chunks) > 0
        assert corpus_ver.startswith("v_")

        # Verify chunk metadata schema
        chunk = chunks[0]
        assert "document_id" in chunk
        assert chunk["filename"] == "test_paper.pdf"
        assert chunk["page"] >= 1
        assert "chunk_id" in chunk
        assert len(chunk["content_hash"]) == 16
        assert chunk["corpus_version"] == corpus_ver
        assert len(chunk["text"]) > 0

    def test_corpus_version_determinism_and_invalidation(self, temp_rag_env):
        config = temp_rag_env["config"]
        docs_dir = temp_rag_env["docs_dir"]
        ingestion = DocumentIngestion(config.documents_dir)

        chunks_v1, corpus_ver_v1 = ingestion.extract_chunks()
        chunks_repeat, corpus_ver_repeat = ingestion.extract_chunks()
        # Must be deterministic given same files
        assert corpus_ver_v1 == corpus_ver_repeat

        # Invalidate by adding another document
        new_pdf = docs_dir / "second_paper.pdf"
        build_paper(
            str(new_pdf),
            "Second Paper on Vector Index Partitioning",
            "Carol White",
            "Vector search partitioning speeds up nearest neighbor retrieval across large corpora.",
            [("Overview", "Partitioned indices scale linearly with cluster nodes.")]
        )

        chunks_v2, corpus_ver_v2 = ingestion.extract_chunks()
        assert corpus_ver_v2 != corpus_ver_v1
        assert len(chunks_v2) > len(chunks_v1)


@pytest.mark.asyncio
class TestRetrievalAndL4Cache:
    """Test vector storage, retrieval, and L4 cache isolation."""

    async def test_l4_retrieval_cache_and_isolation(self, temp_rag_env):
        config = temp_rag_env["config"]
        ingestion = DocumentIngestion(config.documents_dir)
        chunks, corpus_ver = ingestion.extract_chunks()

        from ico_cache.backends.exact.sqlite_store import SQLiteStore
        exact_store = SQLiteStore(db_path=config.sqlite_path)

        embedder = CachedEmbedder(exact_store=exact_store, model_name=config.embedding_model)
        vector_store = RAGVectorStore(config)
        vectors = embedder.embed_batch([c["text"] for c in chunks])
        await vector_store.insert_chunks(chunks, vectors, tenant_id="tenant-1")

        retriever = RAGRetriever(
            vector_store=vector_store,
            embedder=embedder,
            exact_store=exact_store,
            enable_l4_cache=True,
        )

        query = "What does this paper introduce?"

        # 1. Cold retrieval: L4 miss
        res1 = await retriever.retrieve(query, corpus_version=corpus_ver, tenant_id="tenant-1")
        assert len(res1) > 0
        assert retriever.retrieval_cache_misses == 1
        assert retriever.retrieval_cache_hits == 0

        # Verify source provenance metadata
        top_chunk = res1[0]
        assert "filename" in top_chunk
        assert "page" in top_chunk
        assert "chunk_id" in top_chunk
        assert top_chunk["filename"] == "test_paper.pdf"

        # 2. Repeat retrieval: L4 hit
        res2 = await retriever.retrieve(query, corpus_version=corpus_ver, tenant_id="tenant-1")
        assert len(res2) == len(res1)
        assert retriever.retrieval_cache_hits == 1
        assert res2[0]["chunk_id"] == top_chunk["chunk_id"]

        # 3. Same query with changed corpus_version: L4 miss (cache isolation)
        res_v2 = await retriever.retrieve(query, corpus_version="v_changed_corpus", tenant_id="tenant-1")
        assert retriever.retrieval_cache_misses == 2

        # 4. Same query with different tenant: L4 miss (tenant isolation)
        res_tenant2 = await retriever.retrieve(query, corpus_version=corpus_ver, tenant_id="tenant-2")
        assert retriever.retrieval_cache_misses == 3


@pytest.mark.asyncio
class TestEndToEndRAGAPIAndDashboardTelemetry:
    """Test full HTTP API with cache cascade, source provenance, and telemetry."""

    async def test_full_rag_cascade_and_provenance(self, temp_rag_env):
        from httpx import AsyncClient, ASGITransport

        config = temp_rag_env["config"]
        app = create_demo_app(config)

        # Trigger initial ingestion
        chunks, corpus_ver = app.state.ingestion.extract_chunks()
        app.state.corpus_version = corpus_ver
        app.state.chunks = chunks
        if chunks:
            vectors = app.state.embedder.embed_batch([c["text"] for c in chunks])
            await app.state.vector_store.insert_chunks(chunks, vectors)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            query = "What is the main conclusion of the paper?"

            # 1. Cold request -> LLM executed (miss)
            resp1 = await client.post("/rag/query", json={"query": query})
            assert resp1.status_code == 200
            data1 = resp1.json()
            assert data1["cache"]["hit"] is False
            assert len(data1["sources"]) > 0
            assert data1["sources"][0]["document"] == "test_paper.pdf"
            assert data1["sources"][0]["page"] >= 1
            assert data1["sources"][0]["chunk_id"] is not None

            # 2. Exact repeated query -> L1 HIT, LLM avoided
            resp2 = await client.post("/rag/query", json={"query": query})
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["cache"]["hit"] is True
            assert data2["cache"]["layer"] == "L1"
            assert data2["answer"] == data1["answer"]

            # CRITICAL: Provenance must NEVER be stripped on cache hits
            assert len(data2["sources"]) == len(data1["sources"])
            assert data2["sources"][0]["document"] == data1["sources"][0]["document"]
            assert data2["sources"][0]["page"] == data1["sources"][0]["page"]
            assert data2["sources"][0]["chunk_id"] == data1["sources"][0]["chunk_id"]

            # 3. Tenant Isolation
            resp_tenant_b = await client.post("/rag/query", json={"query": query, "tenant_id": "tenant-b"})
            assert resp_tenant_b.status_code == 200
            data_b = resp_tenant_b.json()
            # Must NOT hit tenant-a's cache
            assert data_b["cache"]["hit"] is False

            # 4. Check dashboard metrics overview endpoint
            resp_metrics = await client.get("/v1/metrics/overview")
            assert resp_metrics.status_code == 200
            metrics = resp_metrics.json()
            assert int(metrics["requests"]["value"]) >= 2
            assert metrics["cacheHitRate"]["value"] != ""

            # 5. Check dashboard requests endpoint
            resp_reqs = await client.get("/v1/requests?pageSize=10")
            assert resp_reqs.status_code == 200
            req_data = resp_reqs.json()
            assert len(req_data["data"]) >= 2
            assert req_data["data"][0]["id"] is not None

            # 6. Check decision trace for winning request
            trace_id = data2["request_id"]
            resp_trace = await client.get(f"/v1/decision-traces/{trace_id}")
            if resp_trace.status_code == 200:
                trace_data = resp_trace.json()
                assert "steps" in trace_data or "layers" in trace_data


@pytest.mark.asyncio
class TestEmbeddingCacheAndL5:
    """Test L0b embedding cache and L5 context cache."""

    async def test_l0b_embedding_cache_hit_and_telemetry(self, temp_rag_env):
        config = temp_rag_env["config"]
        from ico_cache.backends.exact.sqlite_store import SQLiteStore
        exact_store = SQLiteStore(db_path=config.sqlite_path)

        embedder = CachedEmbedder(exact_store=exact_store, model_name=config.embedding_model)
        sample_text = "Dense vector embeddings represent semantic meaning."

        # Cold embed
        v1 = embedder.embed(sample_text)
        assert len(v1) > 0
        assert embedder.embedding_calls == 1
        assert embedder.embedding_cache_hits == 0

        # Repeat embed: L0b hit
        v2 = embedder.embed(sample_text)
        assert v1 == v2
        assert embedder.embedding_calls == 2
        assert embedder.embedding_cache_hits == 1
        assert embedder.embedding_calls_avoided == 1

        # Check telemetry batch
        batch = [sample_text, "Another sentence for vectorization."]
        v_batch = embedder.embed_batch(batch)
        assert len(v_batch) == 2
        # sample_text should hit again
        assert embedder.embedding_cache_hits >= 2

    async def test_empty_or_corrupted_document_handling(self, temp_rag_env):
        docs_dir = temp_rag_env["docs_dir"]
        # Add an empty text/corrupted file with .pdf extension
        corrupt_file = docs_dir / "corrupted.pdf"
        corrupt_file.write_bytes(b"%PDF-1.4 empty or broken content")

        ingestion = DocumentIngestion(str(docs_dir))
        # Should not raise exception
        try:
            chunks, ver = ingestion.extract_chunks()
            assert len(chunks) >= 0
        except Exception as e:
            pytest.fail(f"Ingestion should handle corrupt PDFs gracefully, got {e}")

