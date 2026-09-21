"""Exceptions for intelligent_cache."""


class IntelligentCacheError(Exception):
    """Base exception for all intelligent_cache errors."""
    pass


class BackendError(IntelligentCacheError):
    """Raised when a storage backend operation fails."""
    pass


class BackendConnectionError(BackendError):
    """Raised when connecting to a backend service fails."""
    pass


class EmbeddingError(IntelligentCacheError):
    """Raised when embedding generation fails."""
    pass


class InvalidationError(IntelligentCacheError):
    """Raised when cache invalidation fails."""
    pass


class ConfigurationError(IntelligentCacheError):
    """Raised when configuration is invalid."""
    pass
