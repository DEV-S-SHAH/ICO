"""Image loader: OCR raster images (png, jpg, tiff, bmp, gif, webp)."""
import logging
import os
from typing import List, Optional

from .base import BaseLoader, Chunk
from .ocr import ocr_enabled, ocr_image
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.image_loader")


class ImageLoader(BaseLoader):
    """
    Extracts text from raster images via OCR (pytesseract).

    Files are opened by content, so any format Pillow can decode works, and OCR
    applies uniformly to scanned pages, screenshots, and photos.
    """

    def __init__(self, schema: Optional[MetadataSchema] = None, languages: Optional[str] = None):
        self.schema = schema
        self.languages = languages
        self.last_status: Optional[str] = None
        self.last_error: Optional[str] = None

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        self.last_status = None
        self.last_error = None

        if not os.path.exists(file_path):
            self.last_status = "file_not_found"
            logger.warning("File not found: %s", file_path)
            return []
        if os.path.getsize(file_path) == 0:
            self.last_status = "empty_file"
            return []
        if not ocr_enabled():
            self.last_status = "ocr_disabled"
            return []

        chunks = ocr_image(
            file_path,
            schema=effective_schema,
            source_file=file_path,
            languages=self.languages,
        )
        if chunks:
            self.last_status = "ocr_success"
        else:
            self.last_status = "image_only_no_text"
            logger.warning("Image contains no OCR-able text: %s", file_path)
        return chunks

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
