import logging
import os
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.pdf_loader")


class PDFLoader(BaseLoader):
    def __init__(self, schema: Optional[MetadataSchema] = None):
        self.schema = schema

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        chunks = []
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return []

        try:
            try:
                import pypdf
                reader_cls = pypdf.PdfReader
            except ImportError:
                import PyPDF2
                reader_cls = PyPDF2.PdfReader

            with open(file_path, "rb") as f:
                reader = reader_cls(f)
                for i, page in enumerate(reader.pages):
                    try:
                        text = page.extract_text() or ""
                    except Exception as pe:
                        logger.warning(f"Error extracting page {i+1} from {file_path}: {pe}")
                        text = ""

                    clean_text = text.strip()
                    if clean_text:
                        meta = {
                            "source_file": file_path,
                            "page_or_section": f"Page {i+1}",
                        }
                        if effective_schema:
                            extracted = effective_schema.extract(clean_text)
                            meta.update({k: v for k, v in extracted.items() if v is not None})

                        chunks.append(
                            Chunk(
                                text=clean_text,
                                source_file=file_path,
                                page_or_section=f"Page {i+1}",
                                chunk_index=len(chunks),
                                metadata=meta,
                            )
                        )
        except Exception as e:
            logger.warning(f"Failed to parse PDF file {file_path}: {e}")
            return []

        return chunks

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
