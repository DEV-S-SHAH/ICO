from .core.cache_engine import CacheEngine, CacheEngine as ICOCache
from .core.config import ICOConfig
from .loaders.auto_loader import ingest, AutoLoader

__version__ = "1.0.5"

__all__ = ["CacheEngine", "ICOCache", "ICOConfig", "ingest", "AutoLoader", "__version__"]
