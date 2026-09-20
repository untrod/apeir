"""Errors raised by the unified model runtime."""

from __future__ import annotations

from nous_runtime.core.errors import CapabilityError, NousError, ProviderError


class ModelRuntimeError(NousError):
    """Base error for unified model runtime failures."""


class ModelRegistryError(ModelRuntimeError, ValueError):
    """Raised when model registry data is invalid or inconsistent."""


class ModelRoutingError(ModelRuntimeError, LookupError):
    """Raised when no safe route can satisfy a model request."""


class ModelResourceError(ModelRuntimeError):
    """Raised when an instance lease cannot be acquired or maintained."""


class ModelInvocationError(ModelRuntimeError):
    """Raised when a backend invocation fails."""


class ModelAdapterError(ModelInvocationError, ProviderError):
    """Raised when a backend adapter is missing or unhealthy."""


class ModelProviderResponseError(ModelAdapterError):
    """Structured failure returned by a model Provider boundary."""

    def __init__(
        self,
        message: str,
        *,
        provider_error_code: str = "",
        http_status: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_error_code = str(provider_error_code or "")
        self.http_status = int(http_status) if http_status is not None else None
        self.retryable = retryable


class ModelResolutionError(ModelRuntimeError, CapabilityError):
    """Raised when a capability installation plan cannot be resolved."""


__all__ = [
    "ModelAdapterError",
    "ModelInvocationError",
    "ModelProviderResponseError",
    "ModelRegistryError",
    "ModelResolutionError",
    "ModelResourceError",
    "ModelRoutingError",
    "ModelRuntimeError",
]
