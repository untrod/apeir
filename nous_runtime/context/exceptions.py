# -*- coding: utf-8 -*-
"""Context Runtime exceptions."""

from __future__ import annotations


class ContextError(Exception):
    """Base exception for Context Runtime."""


class ContextValidationError(ContextError, ValueError):
    """Context data validation failed."""


class ContextStoreError(ContextError):
    """Context persistence operation failed."""


class ContextProviderError(ContextError):
    """Context provider failed to collect data."""


class ContextBuildError(ContextError):
    """Context building pipeline failed."""


class ContextResolutionError(ContextError):
    """Context resolution (scoring/selection) failed."""


class ContextPermissionError(ContextError, PermissionError):
    """Access to context denied by governance."""


class ContextRestoreError(ContextError):
    """Context snapshot restore failed."""
