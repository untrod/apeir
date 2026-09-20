# -*- coding: utf-8 -*-
"""
Provider Registry -singleton registry with lifecycle hooks and health aggregation.

Wraps nous_core.provider's _providers dict with additional capabilities:
- Lifecycle hooks: on_register, on_unregister
- Health aggregation across all providers
- Provider discovery and validation
"""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.core.errors import ProviderError
from nous_runtime.compat.provider import (
    Provider,
    register_adapter,
    unregister_adapter,
    list_providers,
    get_provider,
)

log = logging.getLogger("nous.provider.registry")


class ProviderRegistry:
    """
    Singleton registry for Provider instances.

    Wraps the existing nous_core.provider functions with:
    - Lifecycle event emission
    - Type validation (isinstance check against Provider ABC)
    - Aggregated health checks
    """

    _instance: "ProviderRegistry | None" = None

    def __new__(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._hooks_registered = False
        return cls._instance

    def install(self, provider: Provider) -> str:
        """
        Register a provider adapter.

        Args:
            provider: A Provider subclass instance.

        Returns:
            The provider name.

        Raises:
            TypeError: If provider does not implement the Provider ABC.
        """
        if not isinstance(provider, Provider):
            raise TypeError(
                f"{type(provider).__name__} must be a Provider subclass"
            )
        if not register_adapter(provider):
            raise ProviderError("provider registration failed")
        provider_id = provider.provider_id
        provider_name = provider.provider_name or provider_id
        log.info("Provider installed: %s (%s)", provider_name, provider_id)
        self._emit_lifecycle("provider.installed", provider_name)
        return provider_id

    def remove(self, provider_id: str) -> None:
        """Unregister a provider."""
        unregister_adapter(provider_id)
        log.info("Provider removed: %s", provider_id)
        self._emit_lifecycle("provider.removed", provider_id)

    def get(self, provider_id: str) -> Provider | None:
        """Get a provider by ID."""
        return get_provider(provider_id)

    def list_all(self) -> list[dict[str, Any]]:
        """List all registered providers with metadata."""
        providers = list_providers()
        return [
            {
                "id": p.get("provider_id", "?"),
                "name": p.get("name", "?"),
                "capabilities": p.get("capabilities", []),
                "health": p.get("health", {"status": "unknown"}),
            }
            for p in providers
        ]

    def health_all(self) -> dict[str, Any]:
        """
        Aggregate health across all providers.

        Returns:
            {"status": "ok|degraded|down", "providers": {...}, "summary": {...}}
        """
        providers = list_providers()
        results = {}
        ok = warn = down = 0

        for p in providers:
            pid = p.get("provider_id", "?")
            h = p.get("health", {"status": "unknown"})
            results[pid] = h
            status = h.get("status", "unknown")
            if status == "ok":
                ok += 1
            elif status in ("degraded", "warning"):
                warn += 1
            else:
                down += 1

        if down > 0:
            overall = "down"
        elif warn > 0:
            overall = "degraded"
        else:
            overall = "ok"

        return {
            "status": overall,
            "providers": results,
            "summary": {"total": len(providers), "ok": ok, "degraded": warn, "down": down},
        }

    @staticmethod
    def _safe_health(provider: Provider) -> dict[str, Any]:
        try:
            return provider.health()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _emit_lifecycle(event_type: str, provider_name: str) -> None:
        try:
            from nous_runtime.compat.events import emit_event
            emit_event(event_type, source="provider_registry", payload={"provider": provider_name})
        except Exception:
            pass


# Module-level convenience
registry = ProviderRegistry()
