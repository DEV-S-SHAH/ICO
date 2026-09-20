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

try:
    from ico_cache.loaders.pdf_loader import PDFLoader
    __all__.append("PDFLoader")
except ImportError:
    PDFLoader = None

try:
    from ico_cache.loaders.html_loader import HTMLLoader
    __all__.append("HTMLLoader")
except ImportError:
    HTMLLoader = None

