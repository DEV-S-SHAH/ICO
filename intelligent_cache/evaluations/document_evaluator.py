"""Document ingestion and QA evaluation with intelligent caching."""

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from intelligent_cache.core.cache import IntelligentCache
from intelligent_cache.core.entry import CacheHitType


@dataclass
class DocumentChunk:
    """A chunk of text extracted from a PDF or text document."""
    doc_name: str
    doc_type: str  # 'pdf' or 'text'
    page_or_section: Union[int, str]
    text: str
    chunk_id: str


def extract_text_from_file(file_path: Union[str, Path]) -> list[DocumentChunk]:
    """Extract text chunks from a PDF or text file with cross-platform compatibility."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    chunks: list[DocumentChunk] = []
    doc_name = path.name
    ext = path.suffix.lower()

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                clean_text = " ".join(text.split())
                if clean_text:
                    chunks.append(
                        DocumentChunk(
                            doc_name=doc_name,
                            doc_type="pdf",
                            page_or_section=i + 1,
                            text=clean_text,
                            chunk_id=f"{doc_name}:p{i + 1}",
                        )
                    )
        except Exception as exc:
            # Fallback simple extractor
            raw = path.read_bytes()
            # Simple text stream extraction
            extracted = re.findall(b"\\((.*?)\\)", raw)
            text = " ".join(s.decode("latin1", errors="ignore") for s in extracted)
            clean_text = " ".join(text.split())
            chunks.append(
                DocumentChunk(
                    doc_name=doc_name,
                    doc_type="pdf",
                    page_or_section=1,
                    text=clean_text or f"Extracted binary content from {doc_name}",
                    chunk_id=f"{doc_name}:fallback",
                )
            )

    else:
        # Standard text file
        content = path.read_text(encoding="utf-8", errors="ignore")
        # Split by sections or paragraphs
        sections = re.split(r"\n\s*\n", content)
        for i, sec in enumerate(sections):
            clean_sec = " ".join(sec.split())
            if len(clean_sec) > 30:
                chunks.append(
                    DocumentChunk(
                        doc_name=doc_name,
                        doc_type="text",
                        page_or_section=f"sec_{i + 1}",
                        text=clean_sec,
                        chunk_id=f"{doc_name}:sec_{i + 1}",
                    )
                )

    return chunks


class DocumentQAEngine:
    """Simple document retrieval QA engine used for caching evaluations."""

    def __init__(self, data_dir: Union[str, Path] = "data"):
        self.data_dir = Path(data_dir)
        self.chunks: list[DocumentChunk] = []
        self._load_documents()

    def _load_documents(self) -> None:
        if not self.data_dir.exists():
            return
        for f in sorted(self.data_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".pdf", ".txt", ".md"):
                extracted = extract_text_from_file(f)
                self.chunks.extend(extracted)

    def answer_query(self, query: str) -> dict[str, Any]:
        """Answer a query by matching relevant document chunks and generating an answer."""
        query_words = set(re.findall(r"\b[a-zA-Z0-9_-]+\b", query.lower()))
        best_chunk = None
        best_overlap = 0

        for chunk in self.chunks:
            chunk_words = set(re.findall(r"\b[a-zA-Z0-9_-]+\b", chunk.text.lower()))
            overlap = len(query_words.intersection(chunk_words))
            if overlap > best_overlap:
                best_overlap = overlap
                best_chunk = chunk

        if best_chunk and best_overlap >= 2:
            return {
                "answer": f"According to {best_chunk.doc_name} ({best_chunk.chunk_id}): {best_chunk.text[:250]}...",
                "source": best_chunk.doc_name,
                "confidence": min(1.0, best_overlap / max(1, len(query_words))),
                "chunk_id": best_chunk.chunk_id,
            }

        return {
            "answer": "Information not found in the indexed policy documents.",
            "source": "none",
            "confidence": 0.0,
            "chunk_id": None,
        }
