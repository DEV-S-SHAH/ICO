"""Tests for PDF and text document extraction, retrieval QA, and caching."""

from pathlib import Path
from intelligent_cache import IntelligentCache, CacheHitType
from intelligent_cache.evaluations import (
    DocumentChunk,
    DocumentQAEngine,
    extract_text_from_file,
)


def test_pdf_extraction():
    pdf_path = Path("data/sample_policy.pdf")
    assert pdf_path.exists(), "Sample PDF must exist in data/"

    chunks = extract_text_from_file(pdf_path)
    assert len(chunks) >= 1
    assert chunks[0].doc_type == "pdf"
    assert chunks[0].doc_name == "sample_policy.pdf"

    # Verify content was extracted
    all_text = " ".join(c.text for c in chunks)
    assert "LLM" in all_text or "AI" in all_text or "Security" in all_text


def test_text_extraction():
    txt_path = Path("data/expense_policy.txt")
    assert txt_path.exists(), "Expense policy text file must exist in data/"

    chunks = extract_text_from_file(txt_path)
    assert len(chunks) >= 1
    assert chunks[0].doc_type == "text"
    assert chunks[0].doc_name == "expense_policy.txt"


def test_document_qa_engine():
    engine = DocumentQAEngine(data_dir="data")
    assert len(engine.chunks) > 0

    # Query matching PDF
    ans1 = engine.answer_query("What is the meal allowance during domestic travel?")
    assert ans1["source"] != "none"
    assert "sample_policy.pdf" in ans1["source"] or "expense" in ans1["source"]

    # Query matching remote work policy
    ans2 = engine.answer_query("How many remote work days per week?")
    assert ans2["source"] != "none"


def test_document_qa_caching():
    engine = DocumentQAEngine(data_dir="data")
    cache = IntelligentCache(similarity_threshold=0.55, namespace="doc_test")

    q1 = "What is the domestic daily meal allowance?"
    ans = engine.answer_query(q1)

    # Cache response
    cache.set(q1, ans["answer"], ttl=3600)

    # 1. Exact lookup
    hit1 = cache.get(q1)
    assert hit1 is not None
    assert hit1.hit_type == CacheHitType.EXACT
    assert hit1.value == ans["answer"]

    # 2. Semantic lookup (paraphrased question)
    q_para = "Tell me the daily meal allowance for domestic travel"
    hit2 = cache.get(q_para)
    assert hit2 is not None
    assert hit2.hit_type in (CacheHitType.EXACT, CacheHitType.SEMANTIC)
    assert hit2.value == ans["answer"]
