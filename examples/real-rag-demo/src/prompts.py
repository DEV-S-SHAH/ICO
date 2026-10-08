"""Prompt templates and versioning for Real RAG Demo."""

from typing import Any, Dict, List

PROMPT_TEMPLATE_VERSION = "v1"

SYSTEM_PROMPT = """You are an expert AI research assistant. Your task is to answer user questions strictly based on the provided research paper contexts.
Cite your sources with document names and page numbers.
If the context does not contain enough information to answer the question, state: 'Insufficient context.'"""

USER_PROMPT_TEMPLATE = """Context passages from research documents:
{context}

Question: {query}

Answer strictly using the passages above and include citations (Document, Page):"""


def format_context_from_chunks(chunks: List[Dict[str, Any]]) -> str:
    """Format retrieved chunks into structured context with provenance markers."""
    if not chunks:
        return "No relevant passages found."

    parts = []
    for idx, c in enumerate(chunks):
        filename = c.get("filename", "unknown.pdf")
        page = c.get("page", 1)
        chunk_id = c.get("chunk_id", f"c{idx+1}")
        text = c.get("text", "").strip()

        header = f"--- Document: {filename} | Page: {page} | Chunk ID: {chunk_id} ---"
        parts.append(f"{header}\n{text}")

    return "\n\n".join(parts)