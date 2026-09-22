import glob
import logging
import os
from typing import List, Optional

from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.auto_loader")

PDF_EXTENSIONS = {".pdf"}
HTML_EXTENSIONS = {".htm", ".html", ".xhtml"}
ODF_EXTENSIONS = {".odt", ".ods", ".odp", ".odg", ".odf", ".otp", ".ots"}
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif",
    ".webp", ".jp2", ".ico", ".ppm", ".pgm",
}
STRUCTURED_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".db", ".sqlite", ".sqlite3"}
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".rb", ".php", ".kt", ".kts", ".swift",
    ".scala", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".r", ".lua", ".pl",
    ".dart", ".vue", ".svelte",
}
TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".log", ".nfo", ".srt",
    ".vtt", ".rtf", ".tex", ".adoc", ".org", ".cfg", ".ini", ".conf",
    ".yaml", ".yml", ".toml", ".xml",
}


def _get_parser(file_path: str):
    """Select a loader by extension. Returns None for unknown extensions."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in PDF_EXTENSIONS:
        from .pdf_loader import PDFLoader

        return PDFLoader()
    if ext in HTML_EXTENSIONS:
        from .html_loader import HTMLLoader

        return HTMLLoader()
    if ext in ODF_EXTENSIONS:
        from .odf_loader import ODFLoader

        return ODFLoader()
    if ext in OFFICE_EXTENSIONS:
        from .office_loader import OfficeLoader

        return OfficeLoader()
    if ext in IMAGE_EXTENSIONS:
        from .image_loader import ImageLoader

        return ImageLoader()
    if ext in STRUCTURED_EXTENSIONS:
        from .structured_loader import StructuredLoader

        return StructuredLoader()
    if ext in CODE_EXTENSIONS:
        from .code_loader import CodeLoader

        return CodeLoader()
    if ext in TEXT_EXTENSIONS:
        from .txt_loader import TXTLoader

        return TXTLoader()
    return None


def _looks_like_text(file_path: str, sample_size: int = 8192) -> bool:
    try:
        with open(file_path, "rb") as f:
            data = f.read(sample_size)
    except OSError:
        return False
    if not data or b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
        return printable / len(data) > 0.85


class AutoLoader(BaseLoader):
    """
    Universal auto loader that selects the appropriate loader by file extension
    (PDF/HTML/ODF/Office/images/structured/code/text) and, when a document
    yields no text, falls back to content-based OCR regardless of file type.
    """

    def __init__(
        self,
        schema: Optional[MetadataSchema] = None,
        ocr_fallback: bool = True,
        languages: Optional[str] = None,
    ):
        self.schema = schema
        self.ocr_fallback = ocr_fallback
        self.languages = languages

    def load(self, source: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        if not isinstance(source, str) or not os.path.isfile(source):
            logger.warning("AutoLoader received a non-file or missing source: %.80s", source)
            return []

        parser = _get_parser(source)
        chunks: List[Chunk] = []

        if parser is not None:
            try:
                chunks = parser.load(source, schema=effective_schema) or []
            except Exception as e:
                logger.warning(f"Failed to auto-parse file {source} with {type(parser).__name__}: {e}")
                chunks = []

        # Content-based OCR fallback (scanned images / PDFs) for any type whose
        # primary parser produced no text.
        if not chunks and self.ocr_fallback and not self._parser_handles_ocr(parser):
            from .ocr import ocr_any

            chunks = ocr_any(
                source,
                schema=effective_schema,
                source_file=source,
                languages=self.languages,
            )

        # Unknown extension or empty result: last-resort plain-text read for
        # text-like files only (never for binary blobs).
        if not chunks and parser is None and _looks_like_text(source):
            from .txt_loader import TXTLoader

            try:
                chunks = TXTLoader(schema=effective_schema).load(source, schema=effective_schema) or []
            except Exception as e:
                logger.warning(f"Failed to read {source} as plain text: {e}")
                chunks = []

        return chunks

    @staticmethod
    def _parser_handles_ocr(parser) -> bool:
        if parser is None:
            return False
        return type(parser).__name__ in {"PDFLoader", "ImageLoader"}


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
