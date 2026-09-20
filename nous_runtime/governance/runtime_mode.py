# -*- coding: utf-8 -*-
"""Governance runtime mode resolution and fail-closed policy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class GovernanceRuntimeMode(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    COMPATIBILITY = "compatibility"
    STRICT = "strict"
    PRODUCTION = "production"


@dataclass(frozen=True)
class GovernanceModePolicy:
    mode: GovernanceRuntimeMode
    fail_closed: bool
    compatibility_bypass_allowed: bool
    audit_required: bool


def parse_runtime_mode(value: str | GovernanceRuntimeMode | None) -> GovernanceRuntimeMode | None:
    """Parse a runtime mode value. Returns None for an unset value."""
    if value is None:
        return None
    if isinstance(value, GovernanceRuntimeMode):
        return value
    normalized = str(value).strip().lower().replace("-", "_")
    aliases = {
        "dev": "development",
        "prod": "production",
        "compat": "compatibility",
    }
    normalized = aliases.get(normalized, normalized)
    for mode in GovernanceRuntimeMode:
        if mode.value == normalized:
            return mode
    raise ValueError(f"Unknown governance runtime mode: {value}")


def resolve_runtime_mode(*, surface: str = "local_cli") -> GovernanceRuntimeMode:
    """Resolve the active governance mode for a runtime surface."""
    explicit = parse_runtime_mode(os.environ.get("NOUS_RUNTIME_MODE"))
    if explicit is not None:
        return explicit

    env = os.environ.get("NOUS_ENV", "").strip().lower()
    if env == "production":
        return GovernanceRuntimeMode.PRODUCTION
    if env == "test":
        return GovernanceRuntimeMode.TEST

    if surface in {"server", "api", "control_plane"}:
        return GovernanceRuntimeMode.PRODUCTION
    return GovernanceRuntimeMode.DEVELOPMENT


def mode_policy(mode: GovernanceRuntimeMode | str | None = None, *, surface: str = "local_cli") -> GovernanceModePolicy:
    """Return enforcement policy for the resolved mode."""
    resolved = parse_runtime_mode(mode) or resolve_runtime_mode(surface=surface)
    fail_closed = resolved in {GovernanceRuntimeMode.STRICT, GovernanceRuntimeMode.PRODUCTION}
    return GovernanceModePolicy(
        mode=resolved,
        fail_closed=fail_closed,
        compatibility_bypass_allowed=resolved in {
            GovernanceRuntimeMode.DEVELOPMENT,
            GovernanceRuntimeMode.TEST,
            GovernanceRuntimeMode.COMPATIBILITY,
        },
        audit_required=resolved in {
            GovernanceRuntimeMode.COMPATIBILITY,
            GovernanceRuntimeMode.STRICT,
            GovernanceRuntimeMode.PRODUCTION,
        },
    )


def should_fail_closed(mode: GovernanceRuntimeMode | str | None = None, *, surface: str = "local_cli") -> bool:
    """True when side-effecting execution must be denied on governance failure."""
    return mode_policy(mode, surface=surface).fail_closed
