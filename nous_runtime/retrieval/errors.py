"""Retrieval Fabric exception types."""

from nous_runtime.core.errors import NousError


class RetrievalError(NousError):
    """Base exception for retrieval failures."""


class RetrievalValidationError(RetrievalError, ValueError):
    """Raised when retrieval input violates the canonical contract."""


class RetrievalBackendError(RetrievalError, RuntimeError):
    """Raised when a backend cannot complete an operation."""


class RetrievalBackendNotFoundError(RetrievalBackendError, LookupError):
    """Raised when no backend is registered for a requested name."""
