"""Runtime identity definition for the Nous persona layer."""

from __future__ import annotations

from dataclasses import dataclass

from nous_runtime.version import __version__

_DESCRIPTION = (
    "Nous Runtime is an open-source AI runtime that coordinates models, "
    "tools, memory, and devices. It presents one consistent runtime "
    "identity while delegating execution to configurable model providers."
)


@dataclass(frozen=True)
class RuntimeIdentity:
    """Stable identity presented to users regardless of the active model."""

    name: str = "Nous Runtime"
    description: str = _DESCRIPTION
    version: str = __version__


_IDENTITY = RuntimeIdentity()


def get_identity() -> RuntimeIdentity:
    """Return the singleton runtime identity."""
    return _IDENTITY
