"""Provider service facade used by public CLI and SDK surfaces."""

from __future__ import annotations

from typing import Any

from nous_runtime.provider.base import (
    Provider,
    clear_providers,
    get_provider,
    invoke_via_provider,
    invoke_via_provider_observation,
    list_providers,
    register_adapter,
    unregister_adapter,
)


def list_provider_summaries() -> list[dict[str, Any]]:
    """List providers with public metadata and health summaries."""
    from nous_runtime.provider.registry import registry

    return registry.list_all()


def provider_health_summary() -> dict[str, Any]:
    """Return aggregated provider health."""
    from nous_runtime.provider.registry import registry

    return registry.health_all()


__all__ = [
    "Provider",
    "clear_providers",
    "register_adapter",
    "unregister_adapter",
    "get_provider",
    "list_providers",
    "list_provider_summaries",
    "provider_health_summary",
    "invoke_via_provider",
    "invoke_via_provider_observation",
]
