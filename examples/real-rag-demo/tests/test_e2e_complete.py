import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

_DEMO_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_ROOT.parent.parent
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))
if str(_REPO_ROOT / "packages" / "ico-cache-py" / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "packages" / "ico-cache-py" / "src"))

from src.config import DemoConfig
from src.api import create_demo_app


@pytest.fixture
def isolated_demo_env():
    """Create isolated test environment with sample PDFs."""
    temp_dir = tempfile.mkdtemp(prefix="ico_e2e_")
    docs_dir = Path(temp_dir) / "documents"
    data_dir = Path(temp_dir) / "data"
    docs_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Copy real sample PDFs
    src_docs = Path(__file__).resolve().parent.parent / "documents"
    for pdf in src_docs.glob("*.pdf"):
        shutil.copy(pdf, docs_dir / pdf.name)

    cfg = DemoConfig(
        documents_dir=str(docs_dir),
        data_dir=str(data_dir),
        lancedb_uri=str(data_dir / "lancedb"),
        sqlite_path=str(data_dir / "sqlite.db"),
        vector_db_type="lancedb",
        exact_store_type="sqlite",
        semantic_threshold=0.85,
        llm_provider="mock",
        llm_model="gemini-1.5-flash",
    )

    yield {"config": cfg, "docs_dir": docs_dir, "data_dir": data_dir}
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_complete_e2e_lifecycle(isolated_demo_env):
    """
    Test full lifecycle:
    PDF Ingestion -> L0 -> L0b -> L1 -> L2 -> L4 -> L5 -> Provenance ->
    Invalidation -> Isolation -> OpenAI endpoint -> SDK endpoint -> Dashboard.
    """
    cfg = isolated_demo_env["config"]
    app = create_demo_app(cfg)

    # Ingestion
    chunks, corpus_v1 = app.state.ingestion.extract_chunks()
    assert len(chunks) > 0, "Should extract chunks from real PDFs"
    app.state.corpus_version = corpus_v1
    app.state.chunks = chunks
    vectors = app.state.embedder.embed_batch([c["text"] for c in chunks])
    await app.state.vector_store.insert_chunks(chunks, vectors)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        h_resp = await client.get("/v1/health")
        assert h_resp.status_code == 200
        assert h_resp.json()["status"] == "ok"

        # 2. L0 Deterministic Function Cache Check
        det_resp = await client.post("/rag/query", json={"query": "calc: 42 * 2"})
        assert det_resp.status_code == 200
        det_data = det_resp.json()
        assert det_data["cache"]["hit"] is True
        assert det_data["cache"]["layer"] == "L0a"
        assert "84" in det_data["answer"]

        # 3. First dynamic query -> CACHE MISS (runs LangGraph RAG, L4, L5, LLM)
        q1 = "What is the primary contribution of the Transformer model?"
        r1 = await client.post("/rag/query", json={"query": q1})
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["cache"]["hit"] is False
        assert len(d1["sources"]) > 0
        p1_source = d1["sources"][0]
        assert p1_source["document"] == "attention_is_all_you_need.pdf"
        assert p1_source["page"] >= 1
        assert p1_source["chunk_id"] is not None

        # 4. Repeated exact query -> L1 EXACT CACHE HIT (<1ms, sources 100% preserved)
        r2 = await client.post("/rag/query", json={"query": q1})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["cache"]["hit"] is True
        assert d2["cache"]["layer"] == "L1"
        assert d2["answer"] == d1["answer"]
        assert len(d2["sources"]) == len(d1["sources"])
        assert d2["sources"][0]["chunk_id"] == p1_source["chunk_id"]

        # 5. Semantically similar paraphrase query -> L2 SEMANTIC VECTOR HIT
        q_para = "What is the main contribution of the Transformer architecture?"
        r3 = await client.post("/rag/query", json={"query": q_para})
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3["cache"]["hit"] is True
        assert d3["cache"]["layer"] == "L2"
        assert d3["cache"]["similarity"] >= 0.85
        assert d3["answer"] == d1["answer"]
        assert len(d3["sources"]) == len(d1["sources"])

        # 6. Tenant Isolation: same query from different tenant -> CACHE MISS
        r_tenant = await client.post("/rag/query", json={"query": q1, "tenant_id": "tenant_enterprise"})
        assert r_tenant.status_code == 200
        d_tenant = r_tenant.json()
        assert d_tenant["cache"]["hit"] is False, "Tenant enterprise must not leak default tenant cache"

        # 7. Model Isolation: same query with different model -> CACHE MISS
        r_model = await client.post("/rag/query", json={"query": q1, "model": "gpt-4o"})
        assert r_model.status_code == 200
        d_model = r_model.json()
        assert d_model["cache"]["hit"] is False, "Different model must not hit prior model cache"

        # 8. Corpus Invalidation: mutate corpus by deleting a PDF and re-ingesting
        docs_dir = isolated_demo_env["docs_dir"]
        rag_pdf = docs_dir / "retrieval_augmented_generation.pdf"
        if rag_pdf.exists():
            rag_pdf.unlink()

        chunks_v2, corpus_v2 = app.state.ingestion.extract_chunks()
        assert corpus_v2 != corpus_v1, "Corpus version digest must mutate when documents change"
        app.state.corpus_version = corpus_v2
        app.state.chunks = chunks_v2
        vectors_v2 = app.state.embedder.embed_batch([c["text"] for c in chunks_v2])
        await app.state.vector_store.insert_chunks(chunks_v2, vectors_v2)

        # Query on new corpus version must NOT hit prior corpus cache
        r_mutated = await client.post("/rag/query", json={"query": q1, "corpus_version": corpus_v2})
        assert r_mutated.status_code == 200
        d_mutated = r_mutated.json()
        assert d_mutated["cache"]["hit"] is False, "Mutated corpus must invalidate prior cache"

        # 9. OpenAI Compatibility endpoint (/v1/chat/completions)
        chat_req = {
            "model": "gemini-1.5-flash",
            "messages": [
                {"role": "system", "content": "You are a research assistant."},
                {"role": "user", "content": "What is the primary contribution of the Transformer model?"},
            ],
        }
        chat_resp = await client.post("/v1/chat/completions", json=chat_req)
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        assert chat_data["object"] == "chat.completion"
        assert len(chat_data["choices"]) > 0
        assert "content" in chat_data["choices"][0]["message"]
        assert chat_data["usage"]["total_tokens"] > 0
        assert "ico_cache" in chat_data

        # 10. SDK Compatibility endpoints (/v1/query and /v1/ingest)
        sdk_query = await client.post("/v1/query", json={"query": "ping"})
        assert sdk_query.status_code == 200
        sdk_data = sdk_query.json()
        assert sdk_data["response"] == "pong"
        assert sdk_data["source"] == "L0a"

        sdk_ingest = await client.post(
            "/v1/ingest",
            json={"query": "test manual ingest", "response": "manual cached answer"},
        )
        assert sdk_ingest.status_code == 200
        assert sdk_ingest.json()["status"] == "ingested"

        # 11. Dashboard Live Metrics & Traces
        overview = await client.get("/v1/metrics/overview")
        assert overview.status_code == 200
        ov_data = overview.json()
        assert ov_data["totalRequests"] >= 6
        assert "value" in ov_data["cacheHitRate"]
        assert ov_data["cacheHitRate"]["value"] != "0.0%"

        cache_m = await client.get("/v1/cache/metrics")
        assert cache_m.status_code == 200
        cm_data = cache_m.json()
        assert "L0" in cm_data["layers"]
        assert "L0b" in cm_data["layers"]
        assert "L1" in cm_data["layers"]
        assert "L2" in cm_data["layers"]
        assert "L4" in cm_data["layers"]
        assert "L5" in cm_data["layers"]

        reqs = await client.get("/v1/requests")
        assert reqs.status_code == 200
        reqs_data = reqs.json()
        assert reqs_data["total"] >= 6
        assert len(reqs_data["data"]) > 0

        traces = await client.get("/v1/decision-traces")
        assert traces.status_code == 200
        traces_data = traces.json()
        assert traces_data["count"] > 0
