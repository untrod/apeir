"""Capability query service used by public runtime surfaces."""

from __future__ import annotations

from typing import Any


def list_capabilities(category: str = "", enabled_only: bool = False) -> list[dict[str, Any]]:
    """List registered capabilities through the runtime service boundary."""
    try:
        from nous_runtime.capability import list_capabilities as _list_capabilities

        return _list_capabilities(category=category, enabled_only=enabled_only)
    except Exception:
        return []


def get_capability(name: str) -> dict[str, Any] | None:
    """Return one registered capability by name."""
    try:
        from nous_runtime.capability import get_capability as _get_capability

        return _get_capability(name)
    except Exception:
        return None

