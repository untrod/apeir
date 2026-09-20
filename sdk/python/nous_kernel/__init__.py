"""Public Python client surface for the Nous Foundation kernel."""

from compat.nki_client import (
    NKIClient,
    NKIError,
    NKIRequest,
    NKI_VERSION,
    CompatibilityFacade,
)

__all__ = [
    "CompatibilityFacade",
    "NKIClient",
    "NKIError",
    "NKIRequest",
    "NKI_VERSION",
]

__version__ = "0.1.0"
