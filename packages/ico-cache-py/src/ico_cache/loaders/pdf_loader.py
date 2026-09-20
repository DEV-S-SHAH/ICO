import logging
import os
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.pdf_loader")


class PDFLoader(BaseLoader):
    """
    PDFLoader extracts text from PDF documents with automatic OCR fallback.
    - Attempts fast embedded text-layer extraction via pypdf / PyPDF2 first.
    - Falls back to OCR via pdf2image + pytesseract if 0 chunks result from text layer.
    - Explicitly tracks status ('empty_file', 'text_layer_success', 'ocr_success', 'image_only_no_text').
    """

    def __init__(self, schema: Optional[MetadataSchema] = None):
        self.schema = schema
        self.last_status: Optional[str] = None
        self.last_error: Optional[str] = None

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        self.last_status = None
        self.last_error = None

        if not os.path.exists(file_path):
            self.last_status = "file_not_found"
            logger.warning(f"File not found: {file_path}")
            return []

        if os.path.getsize(file_path) == 0:
            self.last_status = "empty_file"
            logger.warning(f"Empty PDF file (0 bytes): {file_path}")
            return []

        chunks = []

        # 1. Attempt embedded text-layer extraction
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
                        logger.warning(f"Error extracting text layer on page {i+1} of {file_path}: {pe}")
                        text = ""

                    clean_text = text.strip()
                    if clean_text:
                        meta = {
                            "source_file": file_path,
                            "page_or_section": f"Page {i+1}",
                            "extraction_method": "text_layer",
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
            logger.warning(f"Failed to read PDF text layer for {file_path}: {e}")

        if chunks:
            self.last_status = "text_layer_success"
            return chunks

        # 2. Fallback to OCR if 0 chunks resulted from embedded text layer
        logger.info(f"No text-layer found in {file_path}. Attempting OCR fallback via pdf2image + pytesseract...")
        try:
            import pdf2image
            import pytesseract

            images = pdf2image.convert_from_path(file_path)
            for i, img in enumerate(images):
                ocr_text = pytesseract.image_to_string(img).strip()
                if ocr_text:
                    meta = {
                        "source_file": file_path,
                        "page_or_section": f"Page {i+1} (OCR)",
                        "extraction_method": "ocr",
                    }
                    if effective_schema:
                        extracted = effective_schema.extract(ocr_text)
                        meta.update({k: v for k, v in extracted.items() if v is not None})

                    chunks.append(
                        Chunk(
                            text=ocr_text,
                            source_file=file_path,
                            page_or_section=f"Page {i+1} (OCR)",
                            chunk_index=len(chunks),
                            metadata=meta,
                        )
                    )

            if chunks:
                self.last_status = "ocr_success"
                return chunks
            else:
                self.last_status = "image_only_no_text"
                logger.warning(f"Image-only PDF, no extractable text found via OCR: {file_path}")
                return []

        except Exception as ocr_err:
            self.last_status = "ocr_failed"
            self.last_error = str(ocr_err)
            logger.warning(f"OCR fallback failed for {file_path}: {ocr_err}")
            return []

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
