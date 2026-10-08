"""Document Ingestion and Corpus Versioning for Real RAG Demo."""

import hashlib
import os
import re
from typing import Any, Dict, List, Tuple
from pypdf import PdfReader


def compute_content_hash(text: str) -> str:
    """Deterministic hash of text content."""
    clean = " ".join(text.strip().split())
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def split_text_into_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into coherent chunks respecting sentence boundaries and chunk size."""
    # Split text into sentences/segments
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return [text.strip()] if text.strip() else []

    chunks: List[str] = []
    current_chunk = ""

    for s in sentences:
        if not current_chunk:
            current_chunk = s
        elif len(current_chunk) + len(s) + 1 <= chunk_size:
            current_chunk += " " + s
        else:
            chunks.append(current_chunk)
            # Find overlap from end of current chunk
            words = current_chunk.split()
            overlap_words = words[-max(1, overlap // 6):] if len(words) > 10 else []
            prefix = " ".join(overlap_words)
            current_chunk = (prefix + " " + s) if prefix else s

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class DocumentIngestion:
    """Loads PDF documents, extracts metadata, creates chunks and computes corpus version."""

    def __init__(self, documents_dir: str, chunk_size: int = 500, chunk_overlap: int = 50):
        self.documents_dir = documents_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_pdf(self, file_path: str) -> List[Tuple[int, str]]:
        """Load a single PDF and return list of (page_number, page_text). Gracefully handles corrupt or empty files."""
        if not os.path.exists(file_path):
            return []

        try:
            reader = PdfReader(file_path)
            pages = []
            for idx, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                    clean_text = text.strip()
                    if clean_text:
                        pages.append((idx + 1, clean_text))
                except Exception:
                    continue
            return pages
        except Exception:
            return []

    def extract_chunks(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Process all PDFs in documents_dir.
        Returns:
            (chunks, corpus_version)
        """
        if not os.path.isdir(self.documents_dir):
            return [], "v_empty"

        pdf_files = sorted([
            f for f in os.listdir(self.documents_dir)
            if f.lower().endswith(".pdf") and not f.startswith(".")
        ])

        if not pdf_files:
            return [], "v_empty"

        raw_chunks: List[Dict[str, Any]] = []

        for filename in pdf_files:
            full_path = os.path.join(self.documents_dir, filename)
            doc_id = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:12]
            pages = self.load_pdf(full_path)

            for page_num, page_text in pages:
                page_chunks = split_text_into_chunks(
                    page_text,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap
                )
                for chunk_idx, chunk_text in enumerate(page_chunks):
                    content_hash = compute_content_hash(chunk_text)
                    chunk_id = f"{doc_id}_p{page_num}_c{chunk_idx+1}"

                    raw_chunks.append({
                        "document_id": doc_id,
                        "filename": filename,
                        "page": page_num,
                        "chunk_id": chunk_id,
                        "content_hash": content_hash,
                        "text": chunk_text,
                    })

        # Deterministic corpus version computation
        # Combine sorted chunk content hashes and filenames
        sorted_fingerprints = sorted(
            f"{c['filename']}:{c['chunk_id']}:{c['content_hash']}"
            for c in raw_chunks
        )
        combined_digest = hashlib.sha256(
            "|".join(sorted_fingerprints).encode("utf-8")
        ).hexdigest()[:12]
        corpus_version = f"v_{combined_digest}"

        # Attach corpus_version to all chunks
        for c in raw_chunks:
            c["corpus_version"] = corpus_version

        return raw_chunks, corpus_version