"""
financial_schema.py — Financial MetadataSchema plugin example.

Extracts entity (ticker), fiscal quarter, and canonical financial topic
for SEC EDGAR filings and financial QA queries.
"""

import re
from typing import Dict, List, Optional

from ico_cache.core.metadata_guard import MetadataField, MetadataSchema

_ENTITY_TOKENS: List[str] = [
    "GS", "JPM", "BAC", "AAPL", "MSFT", "WMT", "TGT", "PFE",
    "JNJ", "COST", "UNH", "GOOGL", "AMZN", "TSLA", "META", "NVDA",
    "BRK", "XOM", "CVX", "NFLX",
]

_QUARTER_TOKENS: List[str] = ["Q1", "Q2", "Q3", "Q4"]

_TOPIC_TOKENS: List[str] = [
    "supply chain",
    "risk factors",
    "R&D",
    "research and development",
    "revenue",
    "margins",
    "gross margin",
    "net income",
    "earnings",
    "competition",
    "competitors",
    "debt",
    "cash flow",
    "capex",
    "guidance",
    "outlook",
    "dividend",
    "buyback",
]

_TOPIC_CANONICAL: Dict[str, str] = {
    "research and development": "R&D",
    "competitors": "competition",
    "gross margin": "margins",
    "net income": "earnings",
}


def _canonical_topic(raw: str) -> str:
    return _TOPIC_CANONICAL.get(raw.lower(), raw.lower())


def extract_entity(text: str) -> Optional[str]:
    for tok in _ENTITY_TOKENS:
        if re.search(r"\b" + re.escape(tok) + r"\b", text, re.IGNORECASE):
            return tok.upper()
    return None


def extract_quarter(text: str) -> Optional[str]:
    for tok in _QUARTER_TOKENS:
        if tok in text:
            return tok
    return None


def extract_topic(text: str) -> Optional[str]:
    text_lower = text.lower()
    for tok in _TOPIC_TOKENS:
        if tok.lower() in text_lower:
            return _canonical_topic(tok)
    return None


def extract_fields(text: str) -> Dict[str, Optional[str]]:
    return {
        "entity": extract_entity(text),
        "quarter": extract_quarter(text),
        "topic": extract_topic(text),
    }


def get_financial_schema() -> MetadataSchema:
    return MetadataSchema(
        fields=[
            MetadataField(name="entity", field_type=str, extractor=extract_entity),
            MetadataField(name="quarter", field_type=str, extractor=extract_quarter),
            MetadataField(name="topic", field_type=str, extractor=extract_topic),
        ]
    )


financial_schema = get_financial_schema()
