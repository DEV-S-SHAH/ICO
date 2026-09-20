import os
import pytest
from ico_cache.loaders.base import BaseLoader, Chunk
from ico_cache.loaders.structured_loader import StructuredLoader
from ico_cache.loaders.code_loader import CodeLoader
from ico_cache.loaders.txt_loader import TXTLoader
from ico_cache.loaders.html_loader import HTMLLoader
from ico_cache.loaders.auto_loader import AutoLoader, ingest
from examples.universal_schema import universal_schema

CORPUS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/test-corpus"))


def test_structured_loader_csv():
    loader = StructuredLoader()
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/products.csv"))
    chunks = loader.load(csv_path)
    assert len(chunks) == 3
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].metadata["name"] == "Sony WH-1000XM5"
    assert "P101" in chunks[0].text


def test_structured_loader_json():
    loader = StructuredLoader()
    raw_json = '[{"user_id": 1, "action": "login"}, {"user_id": 2, "action": "logout"}]'
    chunks = loader.load(raw_json)
    assert len(chunks) == 2
    assert chunks[0].metadata["user_id"] == 1
    assert "action: login" in chunks[0].text


def test_code_loader_ast():
    loader = CodeLoader(language="python")
    code_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/sample_code.py"))
    chunks = loader.load(code_path)
    assert len(chunks) >= 2
    func_chunk = next(c for c in chunks if c.metadata.get("name") == "calculate_discount")
    assert func_chunk.metadata["type"] == "function"
    assert "def calculate_discount" in func_chunk.text

    class_chunk = next(c for c in chunks if c.metadata.get("name") == "InventoryManager")
    assert class_chunk.metadata["type"] == "class"
    assert "class InventoryManager" in class_chunk.text


def test_txt_loader():
    loader = TXTLoader()
    txt_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/sample.txt"))
    chunks = loader.load(txt_path)
    assert len(chunks) == 3
    assert "Universal Document Ingestion" in chunks[0].text


def test_auto_loader_dispatch():
    txt_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/sample.txt"))
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/products.csv"))
    chunks = ingest(path=txt_path)
    assert len(chunks) == 3
    csv_chunks = ingest(path=csv_path)
    assert len(csv_chunks) == 3


def test_corpus_edge_cases_no_unhandled_exceptions():
    """
    Verify that across all corpus edge cases (empty, tiny, non-UTF-8, malformed, large),
    no loader raises an unhandled exception. Malformed input logs/skips and never crashes.
    """
    loaders = {
        "text": TXTLoader(),
        "structured": StructuredLoader(),
        "code": CodeLoader(),
    }
    auto_loader = AutoLoader()

    for category, loader in loaders.items():
        cat_dir = os.path.join(CORPUS_ROOT, category)
        assert os.path.exists(cat_dir), f"Corpus directory missing: {cat_dir}"
        files = os.listdir(cat_dir)
        assert len(files) >= 5, f"Expected at least 5 files in {cat_dir}, found {len(files)}"

        for f in files:
            file_path = os.path.join(cat_dir, f)
            # Must not raise unhandled exception
            chunks = loader.load(file_path)
            assert isinstance(chunks, list)
            auto_chunks = auto_loader.load(file_path)
            assert isinstance(auto_chunks, list)


def test_corpus_sane_chunk_bounds_per_file_size():
    """
    Verify that chunk counts fall within a sane min/max bound per file size.
    """
    categories = {
        "text": TXTLoader(),
        "structured": StructuredLoader(),
        "code": CodeLoader(),
    }

    for cat, loader in categories.items():
        cat_dir = os.path.join(CORPUS_ROOT, cat)

        # Empty file -> 0 chunks
        empty_files = [f for f in os.listdir(cat_dir) if f.startswith("empty")]
        for ef in empty_files:
            chunks = loader.load(os.path.join(cat_dir, ef))
            assert len(chunks) == 0, f"Expected 0 chunks for empty file {ef}, got {len(chunks)}"

        # Tiny file -> exactly 1 chunk
        tiny_files = [f for f in os.listdir(cat_dir) if f.startswith("tiny")]
        for tf in tiny_files:
            chunks = loader.load(os.path.join(cat_dir, tf))
            assert len(chunks) == 1, f"Expected 1 chunk for tiny file {tf}, got {len(chunks)}"

        # Standard file -> bounded between 2 and 20 chunks
        std_files = [f for f in os.listdir(cat_dir) if f.startswith("standard")]
        for sf in std_files:
            chunks = loader.load(os.path.join(cat_dir, sf))
            assert 2 <= len(chunks) <= 20, f"Expected 2-20 chunks for standard file {sf}, got {len(chunks)}"

        # Large file (>10MB) -> bounded between 1,000 and 150,000 chunks
        large_files = [f for f in os.listdir(cat_dir) if f.startswith("large")]
        for lf in large_files:
            chunks = loader.load(os.path.join(cat_dir, lf))
            assert 1000 <= len(chunks) <= 150000, f"Expected 1000-150000 chunks for large file {lf}, got {len(chunks)}"


def test_corpus_schema_metadata_matching():
    """
    Verify that every chunk produced has non-null source metadata matching the configured schema.
    """
    loaders = [
        TXTLoader(schema=universal_schema),
        StructuredLoader(schema=universal_schema),
        CodeLoader(schema=universal_schema),
    ]
    test_files = [
        os.path.join(CORPUS_ROOT, "text/standard.txt"),
        os.path.join(CORPUS_ROOT, "structured/standard.jsonl"),
        os.path.join(CORPUS_ROOT, "code/standard.py"),
    ]

    for loader, file_path in zip(loaders, test_files):
        chunks = loader.load(file_path, schema=universal_schema)
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.source_file == file_path
            assert isinstance(chunk.metadata, dict)
            assert "source_file" in chunk.metadata
            assert chunk.metadata["source_file"] == file_path


def test_structural_boundary_preservation():
    """
    Verify structural boundaries:
    - StructuredLoader never splits a CSV row or JSON record across chunks.
    - CodeLoader never splits a function or class body across chunks.
    """
    # 1. Structured boundary check
    struct_loader = StructuredLoader()
    jsonl_path = os.path.join(CORPUS_ROOT, "structured/standard.jsonl")
    jsonl_chunks = struct_loader.load(jsonl_path)
    assert len(jsonl_chunks) == 4  # Exactly 4 lines/records
    for idx, c in enumerate(jsonl_chunks):
        assert f"record_id: REC-00{idx+1}" in c.text
        assert "Row " in c.page_or_section or "Record " in c.page_or_section

    csv_path = os.path.join(CORPUS_ROOT, "structured/tiny.csv")
    csv_chunks = struct_loader.load(csv_path)
    assert len(csv_chunks) == 1
    assert "metric: operating_margin" in csv_chunks[0].text
    assert "value: 28.4%" in csv_chunks[0].text

    # 2. CodeLoader function/class boundary check
    code_loader = CodeLoader(language="python")
    code_path = os.path.join(CORPUS_ROOT, "code/standard.py")
    code_chunks = code_loader.load(code_path)

    # Class definition should contain all its methods intact
    order_proc = next(c for c in code_chunks if c.metadata.get("name") == "OrderProcessor")
    assert order_proc.metadata["type"] == "class"
    assert "class OrderProcessor:" in order_proc.text
    assert "def calculate_subtotal" in order_proc.text
    assert "def calculate_tax" in order_proc.text
    assert "def process_order" in order_proc.text
    assert '"status": "APPROVED"' in order_proc.text  # Full body retained, never truncated
