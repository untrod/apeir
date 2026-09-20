# -*- coding: utf-8 -*-
"""Centralized version authority for APEIR Distribution.

This is the SINGLE SOURCE OF TRUTH for all version strings across the
entire distribution — Python package, desktop app, VS Code extension,
SDK, API server, protocol, and all schema versions.

Import pattern:
    from nous_runtime._version import __version__

Do NOT hardcode version strings anywhere else. Use this module or one of
the typed re-exports in `nous_runtime.version`.

Release versions change only through the version-consistency check in
``scripts/ci/verify_release_versions.py``.
"""

from __future__ import annotations

# Canonical version
__version__ = "0.1.0-rc1"

# Typed version tuple
VERSION_TUPLE = (0, 1, 0, "rc", 1)

# Canonical schema version (used by schema_registry.py)
CANONICAL_SCHEMA_VERSION = "1.0.0"
CANONICAL_SCHEMA_VERSION_SHORT = "1.0"

# Protocol version (used by connectivity layer)
PROTOCOL_VERSION = "1.0"

# API version string (used by server.py)
API_SERVER_VERSION = "ApeirRuntimeAPI/1.0"

# Display helpers

def canonical() -> str:
    """Return the canonical version string, e.g. '1.0.0-rc1'."""
    return __version__


def short() -> str:
    """Return the short release tag, e.g. '1.0.0-rc.1'."""
    return "0.1.0-rc1"


def release() -> str:
    """Return the target stable version, e.g. '1.0.0'."""
    return "0.1.0"


def is_rc() -> bool:
    """Return True while we are in the release-candidate phase."""
    return "rc" in __version__


def is_stable() -> bool:
    """Return True only after final v1.0.0 stable promotion."""
    return __version__ == "0.1.0"
