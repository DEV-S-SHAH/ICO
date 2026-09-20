import glob
import logging
import os
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.auto_loader")


def _get_parser(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        from .pdf_loader import PDFLoader

        return PDFLoader()
    elif ext in [".htm", ".html"]:
        from .html_loader import HTMLLoader

        return HTMLLoader()
    elif ext == ".txt":
        from .txt_loader import TXTLoader

        return TXTLoader()
    elif ext in [".csv", ".json", ".jsonl"]:
        from .structured_loader import StructuredLoader

        return StructuredLoader()
    elif ext in [".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp"]:
        from .code_loader import CodeLoader

        return CodeLoader()
    else:
        raise ValueError(f"Unsupported file extension: {ext}")


class AutoLoader(BaseLoader):
    """
    Universal auto loader that automatically selects the appropriate loader
    based on file extension, supporting error resilience and metadata schemas.
    """

    def __init__(self, schema: Optional[MetadataSchema] = None):
        self.schema = schema

    def load(self, source: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        try:
            parser = _get_parser(source)
            if hasattr(parser, "load"):
                return parser.load(source, schema=effective_schema)
        except Exception as e:
            logger.warning(f"Failed to auto-parse file {source}: {e}")
        return []


def ingest(
    path: Optional[str] = None,
    raw_text: Optional[str] = None,
    source_id: Optional[str] = None,
    schema: Optional[MetadataSchema] = None,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    if path:
        if "*" in path:
            files = glob.glob(path)
        else:
            files = [path]

        auto_loader = AutoLoader(schema=schema)
        for f in files:
            chunks.extend(auto_loader.load(f))

    if raw_text:
        source = source_id or "manual"
        meta = {"source_file": source}
        if schema:
            extracted = schema.extract(raw_text)
            meta.update({k: v for k, v in extracted.items() if v is not None})
        chunks.append(
            Chunk(
                text=raw_text,
                source_file=source,
                page_or_section="Manual Input",
                chunk_index=0,
                metadata=meta,
            )
        )

    return chunks
