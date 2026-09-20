import os
import pytest
from ico_cache.loaders.base import BaseLoader, Chunk
from ico_cache.loaders.structured_loader import StructuredLoader
from ico_cache.loaders.code_loader import CodeLoader
from ico_cache.loaders.txt_loader import TXTLoader
from ico_cache.loaders.html_loader import HTMLLoader
from ico_cache.loaders.auto_loader import ingest

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
    # Check function and class chunks
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
