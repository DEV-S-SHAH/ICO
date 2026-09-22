from typing import Optional, Type

from ico_cache.loaders.base import BaseLoader
from ico_cache.loaders.txt_loader import TXTLoader
from ico_cache.loaders.structured_loader import StructuredLoader
from ico_cache.loaders.code_loader import CodeLoader
from ico_cache.loaders.auto_loader import AutoLoader

__all__ = [
    "BaseLoader",
    "TXTLoader",
    "StructuredLoader",
    "CodeLoader",
    "AutoLoader",
]


def _register(module_name: str, class_name: str) -> None:
    """Best-effort optional loader import so missing deps don't break the package."""
    global_vars = globals()
    try:
        module = __import__(f"ico_cache.loaders.{module_name}", fromlist=[class_name])
        cls = getattr(module, class_name)
    except ImportError:
        global_vars[class_name] = None  # type: ignore[assignment]
        return
    global_vars[class_name] = cls
    __all__.append(class_name)


PDFLoader: Optional[Type[BaseLoader]] = None
HTMLLoader: Optional[Type[BaseLoader]] = None
ODFLoader: Optional[Type[BaseLoader]] = None
OfficeLoader: Optional[Type[BaseLoader]] = None
ImageLoader: Optional[Type[BaseLoader]] = None

_register("pdf_loader", "PDFLoader")
_register("html_loader", "HTMLLoader")
_register("odf_loader", "ODFLoader")
_register("office_loader", "OfficeLoader")
_register("image_loader", "ImageLoader")

from ico_cache.loaders.ocr import configure_ocr as configure_ocr  # noqa: E402  (re-exported helper)

__all__.append("configure_ocr")
