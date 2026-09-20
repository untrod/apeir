# -*- coding: utf-8 -*-
"""
Provider base -re-exports and extends nous_core.provider.Provider.

The Provider is the fundamental abstraction for any component that
executes capabilities. Models, devices, storage backends, and external
services are all Providers.

Usage:
    from nous_runtime.provider.base import Provider, register_adapter

    class MyProvider(Provider):
        def list_capabilities(self) -> list[str]:
            return ["my.domain.action"]

        def invoke(self, capability_id: str, **params) -> dict:
            return {"ok": True, "result": "done"}

        def health(self) -> dict:
            return {"status": "ok"}

    register_adapter(MyProvider())
"""

from __future__ import annotations

from nous_runtime.compat.provider import (
    Provider,
    register_adapter,
    unregister_adapter,
    get_provider,
    list_providers,
    invoke_via_provider,
    invoke_via_provider_observation,
)

__all__ = [
    "Provider",
    "register_adapter",
    "unregister_adapter",
    "get_provider",
    "list_providers",
    "invoke_via_provider",
    "invoke_via_provider_observation",
]
