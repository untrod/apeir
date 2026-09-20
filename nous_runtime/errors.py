"""Public exception hierarchy for Nous Runtime.

The historical import path remains supported while foundation exceptions live
in :mod:`nous_runtime.core.errors`.
"""

from __future__ import annotations


from nous_runtime.core.errors import (
    ArtifactError,
    CapabilityError,
    ConfigurationError,
    NousError,
    ProviderError,
    RuntimeStateError,
    TaskError,
)


class NousRuntimeError(NousError):
    """Raised when runtime execution cannot proceed."""


class GovernanceError(NousError):
    """Raised when an operation is not authorized or cannot be audited."""


class ContextError(NousError):
    """Raised when context loading, packing, or restoration fails."""


class AgentError(NousError):
    """Raised when an agent cannot register, bind, or execute."""


class DeploymentError(NousError):
    """Raised when deployment, packaging, or platform validation fails."""


__all__ = [
    "AgentError",
    "ArtifactError",
    "CapabilityError",
    "ConfigurationError",
    "ContextError",
    "DeploymentError",
    "GovernanceError",
    "NousError",
    "NousRuntimeError",
    "ProviderError",
    "RuntimeStateError",
    "TaskError",
]
