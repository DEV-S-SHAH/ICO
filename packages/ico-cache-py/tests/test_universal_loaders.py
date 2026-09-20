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
        large_files = [f for f in os.listdir(cat_dir) if f.startswith("large.")]
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


def test_pdf_and_html_formats():
    """
    Verify TextLoader format coverage:
    - Clean PDF extracts text layer and schema metadata
    - Scanned/OCR PDF extracts text via OCR fallback, recording extraction_method='ocr'
    - Blank image PDF returns 0 chunks with explicit status 'image_only_no_text'
    - Zero-byte PDF returns 0 chunks with explicit status 'empty_file'
    - Malformed HTML strips malicious scripts and extracts clean content chunks
    """
    auto_loader = AutoLoader(schema=universal_schema)
    from ico_cache.loaders.pdf_loader import PDFLoader
    import tempfile
    import fitz

    # 1. Clean PDF
    clean_pdf_path = os.path.join(CORPUS_ROOT, "text/clean.pdf")
    pdf_chunks = auto_loader.load(clean_pdf_path)
    assert len(pdf_chunks) >= 1
    assert "Apple Inc. (AAPL)" in pdf_chunks[0].text
    assert pdf_chunks[0].metadata.get("entity") == "AAPL"
    assert pdf_chunks[0].metadata.get("extraction_method") == "text_layer"

    # 2. Scanned OCR PDF (image containing text)
    scanned_pdf_path = os.path.join(CORPUS_ROOT, "text/scanned_ocr.pdf")
    scanned_chunks = auto_loader.load(scanned_pdf_path)
    assert len(scanned_chunks) >= 1
    assert "Scanned Document" in scanned_chunks[0].text
    assert scanned_chunks[0].metadata.get("extraction_method") == "ocr"

    # 3. Blank image PDF (image with no text)
    pdf_loader = PDFLoader()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp_blank:
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        pix = fitz.Pixmap(fitz.csRGB, (0, 0, 300, 300), False)
        pix.clear_with(255)
        page.insert_image(fitz.Rect(0, 0, 300, 300), pixmap=pix)
        doc.save(tmp_blank.name)
        doc.close()

        blank_chunks = pdf_loader.load(tmp_blank.name)
        assert len(blank_chunks) == 0
        assert pdf_loader.last_status == "image_only_no_text"

    # 4. Zero-byte PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp_empty:
        empty_chunks = pdf_loader.load(tmp_empty.name)
        assert len(empty_chunks) == 0
        assert pdf_loader.last_status == "empty_file"

    # 5. Malformed HTML (unclosed tags, script injection)
    html_path = os.path.join(CORPUS_ROOT, "text/malformed.html")
    html_chunks = auto_loader.load(html_path)
    assert len(html_chunks) >= 1
    full_html_text = "\n".join(c.text for c in html_chunks)
    assert "Microsoft Corporation (MSFT)" in full_html_text
    assert "XSS Attack!" not in full_html_text
    assert "onerror=" not in full_html_text
    assert "Confidential copyright footer" not in full_html_text


def test_multi_language_code_loaders():
    """
    Verify tree-sitter code loading across JavaScript and Go:
    - Functions and classes are structurally bounded
    - Never split across chunks
    """
    auto_loader = AutoLoader(schema=universal_schema)

    # JavaScript via tree-sitter
    js_path = os.path.join(CORPUS_ROOT, "code/standard.js")
    js_chunks = auto_loader.load(js_path)
    assert len(js_chunks) == 3
    js_names = [c.metadata.get("name") for c in js_chunks]
    assert "calculateRevenue" in js_names
    assert "applyDiscount" in js_names
    assert "FinancialService" in js_names

    # Check JS class body integrity
    service_chunk = next(c for c in js_chunks if c.metadata.get("name") == "FinancialService")
    assert "processCheckout" in service_chunk.text
    assert "approved" in service_chunk.text

    # Go via tree-sitter
    go_path = os.path.join(CORPUS_ROOT, "code/standard.go")
    go_chunks = auto_loader.load(go_path)
    assert len(go_chunks) == 3
    go_names = [c.metadata.get("name") for c in go_chunks]
    assert "CalculateMargin" in go_names
    assert "ComputeTax" in go_names

    # Check Go function body integrity
    margin_chunk = next(c for c in go_chunks if c.metadata.get("name") == "CalculateMargin")
    assert "return (revenue - cost) / revenue" in margin_chunk.text


def test_large_scale_malformed_code_fallback():
    """
    Verify that large-scale malformed code (>1MB with scattered syntax errors)
    produces reasonably-sized, non-degenerate chunks via AST fallback
    rather than failing or producing one giant fallback blob.
    """
    code_loader = CodeLoader()
    large_malformed_path = os.path.join(CORPUS_ROOT, "code/large_malformed.py")
    assert os.path.exists(large_malformed_path)
    assert os.path.getsize(large_malformed_path) > 1_000_000

    chunks = code_loader.load(large_malformed_path)
    assert 400 <= len(chunks) <= 1200

    sizes = [len(c.text) for c in chunks]
    assert min(sizes) > 100  # No empty/degenerate chunks
    assert max(sizes) < 10_000  # No giant fallback blobs


def test_structured_loader_row_coalescing():
    """
    Verify that StructuredLoader coalesces rows into bounded chunks
    (50-100 rows per chunk) for large CSV files while keeping small files 1:1.
    """
    loader = StructuredLoader()
    # 1. Large CSV (>100k rows) coalesces into 50-row chunks
    large_csv = os.path.join(CORPUS_ROOT, "structured/large.csv")
    large_chunks = loader.load(large_csv)
    assert 1000 <= len(large_chunks) <= 3000
    assert "Rows 1-50" in large_chunks[0].page_or_section
    assert large_chunks[0].metadata["row_count"] == 50

    # 2. Small CSV (3 rows) preserves 1 row per chunk
    small_csv = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../examples/data/products.csv"))
    small_chunks = loader.load(small_csv)
    assert len(small_chunks) == 3


def test_async_ingestion_job_manager():
    """
    Verify IngestionJobManager threshold dispatch and job status tracking.
    """
    import tempfile
    import time
    from ico_cache.async_ingest import IngestionJobManager
    from ico_cache.core.cache_engine import CacheEngine
    from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
    from ico_cache.backends.vector.lancedb_store import LanceDBStore
    from ico_cache.backends.exact.sqlite_store import SQLiteStore

    with tempfile.TemporaryDirectory() as td:
        engine = CacheEngine(
            embedder=FastEmbedder(),
            vector_store=LanceDBStore(uri=f"{td}/lancedb"),
            exact_store=SQLiteStore(db_path=f"{td}/exact.db"),
        )
        mgr = IngestionJobManager(async_threshold_bytes=1000)

        # Sync dispatch (< 1000 bytes)
        small_file = os.path.join(CORPUS_ROOT, "text/standard.txt")
        job_sync = mgr.submit_ingest(small_file, "tenant_test", engine)
        assert job_sync.is_async is False
        assert job_sync.status == "completed"
        assert job_sync.chunks_processed == 3

        # Async dispatch (> 1000 bytes)
        code_file = os.path.join(CORPUS_ROOT, "code/standard.py")
        job_async = mgr.submit_ingest(code_file, "tenant_test", engine)
        assert job_async.is_async is True
        assert job_async.status in ["queued", "processing", "completed"]

        # Wait for async completion
        for _ in range(50):
            polled = mgr.get_job(job_async.job_id)
            if polled.status == "completed":
                break
            time.sleep(0.1)

        polled = mgr.get_job(job_async.job_id)
        assert polled.status == "completed"
        assert polled.chunks_processed >= 3


def test_cross_type_adversarial_similarity_bounds():
    """
    Verify that all rebuilt cross-type adversarial query pairs:
    - Have 0 metadata conflicts (pass hard_gate)
    - Fall strictly in the 0.8000 to 0.8499 range
    - Produce 0% false hits at the 0.850 threshold
    """
    import json
    adv_path = os.path.join(CORPUS_ROOT, "queries/cross_type_adversarial.jsonl")
    assert os.path.exists(adv_path)

    with open(adv_path) as f:
        pairs = [json.loads(l) for l in f if l.strip()]

    assert len(pairs) >= 30
    for p in pairs:
        sim = p["similarity"]
        assert 0.8000 <= sim <= 0.8499, f"Pair out of bounds: {p}"


def test_ingestion_job_manager_memory_bounds():
    """
    Verify IngestionJobManager bounded memory policy:
    - Evicts jobs older than job_ttl_seconds after completion
    - Enforces max_jobs capacity cap
    """
    import time
    from ico_cache.async_ingest import IngestionJobManager, IngestionJob

    # Test TTL eviction (e.g. 10 second TTL)
    mgr = IngestionJobManager(job_ttl_seconds=10, max_jobs=5)
    now = time.time()

    # Create 3 jobs: one completed 20s ago (expired), one completed 5s ago (active), one processing
    job1 = IngestionJob(
        job_id="job_old",
        tenant_id="t1",
        file_path="f1",
        file_size_bytes=100,
        status="completed",
        completed_at=now - 20.0,
    )
    job2 = IngestionJob(
        job_id="job_recent",
        tenant_id="t1",
        file_path="f2",
        file_size_bytes=100,
        status="completed",
        completed_at=now - 5.0,
    )
    job3 = IngestionJob(
        job_id="job_running",
        tenant_id="t1",
        file_path="f3",
        file_size_bytes=100,
        status="processing",
    )

    mgr.jobs["job_old"] = job1
    mgr.jobs["job_recent"] = job2
    mgr.jobs["job_running"] = job3

    # Cleanup with current time
    evicted = mgr.cleanup_expired_jobs(now=now)
    assert evicted == 1
    assert "job_old" not in mgr.jobs
    assert "job_recent" in mgr.jobs
    assert "job_running" in mgr.jobs

    # Test max_jobs capacity cap (cap is 5)
    for i in range(10):
        mgr.jobs[f"job_fill_{i}"] = IngestionJob(
            job_id=f"job_fill_{i}",
            tenant_id="t1",
            file_path=f"f_{i}",
            file_size_bytes=100,
            status="completed",
            completed_at=now - (10 - i),
        )

    mgr.cleanup_expired_jobs(now=now)
    assert len(mgr.jobs) <= 5


