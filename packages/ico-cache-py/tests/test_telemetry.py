import os
import shutil
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ico_cache.core.cache_engine import CacheEngine
from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.rag.pipeline import RAGPipeline


@pytest.fixture(scope="module")
def tracer_setup():
    """Sets up an in-memory OpenTelemetry tracer provider."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def test_engine(tmp_path):
    db_dir = tmp_path / "lancedb_otel_test"
    db_path = str(tmp_path / "cache_otel_test.db")
    engine = CacheEngine(
        embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        exact_store=SQLiteStore(db_path=db_path),
    )
    yield engine
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(str(db_dir)):
        shutil.rmtree(str(db_dir), ignore_errors=True)


@pytest.mark.asyncio
async def test_otel_spans_on_cache_miss_and_hit(tracer_setup, test_engine):
    exporter = tracer_setup
    exporter.clear()
    engine = test_engine
    tenant = "tenant_otel_demo"

    query = "What was the Q2 revenue?"
    answer = {"revenue": "$4.5B"}

    # 1. Query on cold cache -> MISS
    res_miss = await engine.resolve(query, tenant_id=tenant)
    assert res_miss["source"] == "MISS"

    spans = exporter.get_finished_spans()
    # On MISS, resolve tries L1, L2, L3
    span_names = [s.name for s in spans]
    assert "cache_lookup.l1" in span_names
    assert "cache_lookup.l2" in span_names
    assert "cache_lookup.l3" in span_names

    # Check L1 span attributes
    l1_span = next(s for s in spans if s.name == "cache_lookup.l1")
    assert l1_span.attributes["cache.layer"] == "L1"
    assert l1_span.attributes["cache.hit"] is False
    assert l1_span.attributes["tenant_id"] == tenant
    assert "latency_ms" in l1_span.attributes
    assert l1_span.attributes["latency_ms"] >= 0

    # 2. Populate L1 and query again -> HIT
    exporter.clear()
    engine.set_l1(query, answer, tenant_id=tenant)
    res_hit = await engine.resolve(query, tenant_id=tenant)
    assert res_hit["source"] == "L1"
    assert res_hit["response"] == answer

    hit_spans = exporter.get_finished_spans()
    l1_hit_span = next(s for s in hit_spans if s.name == "cache_lookup.l1")
    assert l1_hit_span.attributes["cache.layer"] == "L1"
    assert l1_hit_span.attributes["cache.hit"] is True
    assert l1_hit_span.attributes["tenant_id"] == tenant
    assert l1_hit_span.attributes["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_otel_span_on_rag_fallback(tracer_setup, tmp_path):
    exporter = tracer_setup
    exporter.clear()

    db_dir = tmp_path / "lancedb_rag_otel"
    rag = RAGPipeline(
        dense_embedder=FastEmbedder(),
        vector_store=LanceDBStore(uri=str(db_dir)),
        collection_name="rag_otel_corpus",
    )

    def mock_llm(prompt):
        return "Generated fallback answer"

    # Generate fallback
    ans, t_ret, t_gen, score, citations = await rag.generate(
        query="Explain quantum computing",
        tenant_id="tenant_research",
        llm_generate_fn=mock_llm,
    )

    spans = exporter.get_finished_spans()
    rag_span = next((s for s in spans if s.name == "rag_fallback"), None)
    assert rag_span is not None
    assert rag_span.attributes["cache.layer"] == "RAG_FALLBACK"
    assert rag_span.attributes["cache.hit"] is False
    assert rag_span.attributes["tenant_id"] == "tenant_research"
    assert "latency_ms" in rag_span.attributes
    assert rag_span.attributes["latency_ms"] >= 0
