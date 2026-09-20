"""
universal_schema.py — Multi-modal, dataset-agnostic MetadataSchema plugin.

Extracts domain entities (tickers, regions, code classes), temporal/stage scopes,
and topics/operations across Text, Structured (CSV/JSON), and Code documents.
"""

import re
from typing import Dict, List, Optional
from ico_cache.core.metadata_guard import MetadataField, MetadataSchema

_ENTITY_TOKENS: List[str] = [
    # Text / Financial
    "GS", "JPM", "BAC", "AAPL", "MSFT", "WMT", "TGT", "PFE",
    "JNJ", "COST", "UNH", "GOOGL", "AMZN", "TSLA", "META", "NVDA",
    "BRK", "XOM", "CVX", "NFLX",
    # Structured / Tabular
    "North", "South", "East", "West", "Acme", "TXN-101", "TXN-102",
    # Code / AST Classes
    "OrderProcessor", "WorkerHandler", "InventoryManager", "OrderItem", "PaymentGateway",
    "FinancialService", "FinancialLedger",
]

_QUARTER_TOKENS: List[str] = [
    "Q1", "Q2", "Q3", "Q4",
    "Stage 1", "Stage 2", "Phase 1", "Phase 2",
]

_TOPIC_TOKENS: List[str] = [
    # Financial / Business
    "supply chain", "risk factors", "R&D", "research and development",
    "revenue", "margins", "gross margin", "net income", "earnings",
    "competition", "debt", "cash flow", "capex", "guidance", "dividend",
    "sales", "operating margin", "transaction", "amount",
    # Code operations
    "subtotal", "tax", "checkout", "discount", "execute", "add", "calculate",
    "order", "subtotal calculation", "tax calculation",
]

_TOPIC_CANONICAL: Dict[str, str] = {
    "research and development": "R&D",
    "competitors": "competition",
    "gross margin": "margins",
    "net income": "earnings",
    "subtotal calculation": "subtotal",
    "tax calculation": "tax",
    "sales": "revenue",
}


def _canonical_topic(raw: str) -> str:
    return _TOPIC_CANONICAL.get(raw.lower(), raw.lower())


def extract_entity(text: str) -> Optional[str]:
    txn_match = re.search(r"\b(TXN-\d+|ACCT-\d+)\b", text, re.IGNORECASE)
    if txn_match:
        return txn_match.group(1).upper()
    for tok in _ENTITY_TOKENS:
        pattern = r"\b" + re.escape(tok) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return tok
    return None


def extract_quarter(text: str) -> Optional[str]:
    for q in _QUARTER_TOKENS:
        pattern = r"\b" + re.escape(q) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return q.upper()
    return None


def extract_topic(text: str) -> Optional[str]:
    lower = text.lower()
    for t in _TOPIC_TOKENS:
        if t.lower() in lower:
            return _canonical_topic(t)
    return None


def extract_fields(text: str) -> Dict[str, Optional[str]]:
    return {
        "entity": extract_entity(text),
        "quarter": extract_quarter(text),
        "topic": extract_topic(text),
    }


universal_schema = MetadataSchema(
    fields=[
        MetadataField(name="entity", field_type=str, extractor=extract_entity, required_for_match=True),
        MetadataField(name="quarter", field_type=str, extractor=extract_quarter, required_for_match=True),
        MetadataField(name="topic", field_type=str, extractor=extract_topic, required_for_match=True),
    ]
)
