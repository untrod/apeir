"""Canonical exception hierarchy for the Nous Runtime foundation."""

from __future__ import annotations


class NousError(Exception):
    """Base exception for errors raised by Nous Runtime."""


class ConfigurationError(NousError, ValueError):
    """Raised when Runtime configuration or input is invalid."""


class ProviderError(NousError, ValueError):
    """Raised when a provider cannot be registered or used."""


class CapabilityError(NousError, LookupError):
    """Raised when a capability cannot be resolved or executed."""


class TaskError(NousError, ValueError):
    """Raised when a task is invalid or cannot proceed."""


class RuntimeStateError(NousError, ValueError):
    """Raised when Runtime state access or a transition is invalid."""


class ArtifactError(NousError, ValueError):
    """Raised when an artifact is invalid or cannot be registered."""


class DeviceError(NousError, ValueError):
    """Raised when a device manifest or device operation is invalid."""


__all__ = [
    "ArtifactError",
    "CapabilityError",
    "ConfigurationError",
    "DeviceError",
    "NousError",
    "ProviderError",
    "RuntimeStateError",
    "TaskError",
]
