import logging
import os
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.html_loader")

_BLOCK_STRIP_RE = re.compile(
    r"<(script|style|nav|header|footer|aside|iframe)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_EVENT_HANDLER_RE = re.compile(r"\son\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JAVASCRIPT_URI_RE = re.compile(
    r"\b(?:src|href|action|formaction)\s*=\s*(\"javascript:[^\"]*\"|'javascript:[^']*'|javascript:[^\s>]+)",
    re.IGNORECASE,
)


def _strip_active_content(content: str) -> str:
    """Remove active content at the source level.

    Python's bundled ``html.parser`` (bs4 backend) can re-parent script/style
    bodies and emit malformed tag attributes (e.g. ``onerror=``) as raw text,
    so removing them after parsing is unreliable. Stripping the raw markup first
    makes script/style payloads and inline event handlers impossible to ingest,
    regardless of the parser's behavior on malformed documents.
    """
    content = _BLOCK_STRIP_RE.sub("", content)
    content = _EVENT_HANDLER_RE.sub("", content)
    content = _JAVASCRIPT_URI_RE.sub("", content)
    return content


class HTMLLoader(BaseLoader):
    def __init__(self, schema: Optional[MetadataSchema] = None):
        self.schema = schema

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            content = _strip_active_content(content)
            soup = BeautifulSoup(content, "html.parser")
        except Exception as e:
            logger.warning(f"Failed to read/parse HTML {file_path}: {e}")
            return []

        # Strip nav, boilerplate, scripts, styles, embedded frames
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            element.decompose()

        blocks = soup.find_all(["p", "div", "article", "section", "h1", "h2", "h3", "h4", "h5", "h6"])

        def _make_chunk(text: str, section: str, index: int) -> Chunk:
            meta = {
                "source_file": file_path,
                "page_or_section": section,
            }
            if effective_schema:
                extracted = effective_schema.extract(text)
                meta.update({k: v for k, v in extracted.items() if v is not None})
            return Chunk(
                text=text,
                source_file=file_path,
                page_or_section=section,
                chunk_index=index,
                metadata=meta,
            )

        if not blocks:
            text = soup.get_text(separator="\n\n").strip()
            if not text:
                return []
            return [_make_chunk(text, "Body", 0)]

        chunks: List[Chunk] = []
        current_section = "Document"

        for block in blocks:
            if block.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                heading_text = block.get_text(strip=True)
                if heading_text:
                    current_section = heading_text[:100]
            else:
                text = block.get_text(strip=True)
                if text and len(text) > 20:
                    chunks.append(_make_chunk(text, current_section, len(chunks)))

        if not chunks:
            text = soup.get_text(separator="\n\n").strip()
            if text:
                chunks.append(_make_chunk(text, "Body", 0))

        return chunks

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
