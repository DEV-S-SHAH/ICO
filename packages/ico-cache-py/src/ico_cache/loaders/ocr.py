"""Universal OCR engine shared by all loaders.

OCR is content-based, not extension-based: ``ocr_any`` sniffs the file's magic
bytes / decodability so scanned images and PDFs get OCR'd regardless of the
filename or dataset "type".

Configuration precedence:
  1. explicit ``configure_ocr(...)`` (e.g. from API settings)
  2. ``OCR_ENABLED`` / ``OCR_LANGUAGES`` / ``OCR_DPI`` environment variables
  3. built-in defaults (enabled, ``eng``, 200 dpi)
"""
import logging
import os
from typing import List, Optional

from ._common import make_chunk
from .base import Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.ocr")

_config: dict = {"enabled": None, "languages": None, "dpi": None}


def configure_ocr(
    enabled: Optional[bool] = None,
    languages: Optional[str] = None,
    dpi: Optional[int] = None,
) -> None:
    """Override OCR settings at runtime (used by the API layer)."""
    if enabled is not None:
        _config["enabled"] = bool(enabled)
    if languages is not None:
        _config["languages"] = str(languages)
    if dpi is not None:
        _config["dpi"] = int(dpi)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def ocr_enabled() -> bool:
    if _config["enabled"] is not None:
        return bool(_config["enabled"])
    return _env_bool("OCR_ENABLED", True)


def default_languages() -> str:
    return _config["languages"] or os.getenv("OCR_LANGUAGES", "eng")


def default_dpi() -> int:
    if _config["dpi"] is not None:
        return int(_config["dpi"])
    try:
        return int(os.getenv("OCR_DPI", "200"))
    except ValueError:
        return 200


def looks_like_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def is_image(path: str) -> bool:
    """True if PIL can decode the file (content-sniffed, extension-agnostic)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def _ocr_pil_image(img, languages: str):
    import pytesseract

    return (pytesseract.image_to_string(img, lang=languages) or "").strip()


def ocr_pdf(
    file_path: str,
    schema: Optional[MetadataSchema] = None,
    source_file: Optional[str] = None,
    languages: Optional[str] = None,
    dpi: Optional[int] = None,
) -> List[Chunk]:
    """OCR every page of a PDF via pdf2image + pytesseract.

    Conversion/OCR errors propagate so callers can distinguish "no text" from
    "OCR failed".
    """
    import pdf2image  # noqa: F401  (raises ImportError when unavailable)
    import pytesseract  # noqa: F401

    source_file = source_file or file_path
    lang = languages or default_languages()
    chunks: List[Chunk] = []
    images = pdf2image.convert_from_path(file_path, dpi=dpi or default_dpi())
    for i, img in enumerate(images):
        text = _ocr_pil_image(img, lang)
        if text:
            chunks.append(
                make_chunk(
                    text,
                    source_file,
                    f"Page {i + 1} (OCR)",
                    len(chunks),
                    "pdf_ocr",
                    schema,
                    {"extraction_method": "ocr", "ocr_languages": lang},
                )
            )
    return chunks


def ocr_image(
    file_path: str,
    schema: Optional[MetadataSchema] = None,
    source_file: Optional[str] = None,
    languages: Optional[str] = None,
) -> List[Chunk]:
    """OCR a single raster image. Returns [] on any failure."""
    if not ocr_enabled():
        return []
    try:
        from PIL import Image
        import pytesseract  # noqa: F401  (availability check for optional dep)
    except ImportError as e:  # pragma: no cover - depends on optional deps
        logger.warning("OCR dependencies unavailable for %s: %s", file_path, e)
        return []

    source_file = source_file or file_path
    lang = languages or default_languages()
    try:
        with Image.open(file_path) as img:
            text = _ocr_pil_image(img, lang)
    except Exception as e:
        logger.warning("Image OCR failed for %s: %s", file_path, e)
        return []

    if not text:
        return []
    return [
        make_chunk(
            text,
            source_file,
            "Image (OCR)",
            0,
            "image_ocr",
            schema,
            {"extraction_method": "ocr", "ocr_languages": lang},
        )
    ]


def ocr_any(
    file_path: str,
    schema: Optional[MetadataSchema] = None,
    source_file: Optional[str] = None,
    languages: Optional[str] = None,
    dpi: Optional[int] = None,
) -> List[Chunk]:
    """OCR a file by sniffing its content, independent of extension/type."""
    if not ocr_enabled() or not os.path.isfile(file_path):
        return []
    if looks_like_pdf(file_path):
        try:
            return ocr_pdf(file_path, schema=schema, source_file=source_file, languages=languages, dpi=dpi)
        except ImportError as e:  # pragma: no cover
            logger.warning("PDF OCR dependencies unavailable: %s", e)
            return []
        except Exception as e:
            logger.warning("PDF OCR failed for %s: %s", file_path, e)
            return []
    if is_image(file_path):
        return ocr_image(file_path, schema=schema, source_file=source_file, languages=languages)
    return []
