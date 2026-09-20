# -*- coding: utf-8 -*-
"""
Provider / Adapter System — standardized external capability interface.

Every external system (GPT, Claude, PC Agent, Phone, ESP32) is a Provider.
A Provider does exactly three things:
  1. list_capabilities() — declare what it can do
  2. invoke(capability_id, **params) — execute a capability
  3. health() — report status

This is the interface that future robots, vehicles, and space equipment implement.

Usage:
  from nous_core.provider import Provider, register_adapter, get_provider

  class GPTProvider(Provider):
      def list_capabilities(self): return ["model.reason", "model.code"]
      def invoke(self, cap_id, **params): ...
      def health(self): return {"status": "ok"}

  register_adapter(GPTProvider())
"""

from __future__ import annotations

import logging as _logging
import os as _os
import time as _time_module
from abc import ABC, abstractmethod
from typing import Any



def _make_observation(status: str, capability_id: str, data=None, errors=None,
                      duration_ms: float = 0.0, metadata=None):
    from nous_runtime.planner.observation import Observation

    if status == "success":
        return Observation.success(
            "provider.invoke",
            data or {},
            capability=capability_id,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
    return Observation.failure(
        "provider.invoke",
        errors or ["provider invocation failed"],
        capability=capability_id,
        duration_ms=duration_ms,
        metadata=metadata or {},
    )

_log = _logging.getLogger("nous_core.provider")


# Standard Provider Interface

class Provider(ABC):
    """Base class for all providers. Implement these three methods."""

    provider_id: str = ""
    provider_name: str = ""

    @abstractmethod
    def list_capabilities(self) -> list[str]:
        """Return list of capability IDs this provider handles."""
        ...

    @abstractmethod
    def invoke(self, capability_id: str, **params) -> dict:
        """Execute a capability. Must not raise; return {"ok": False, "error": ...}."""
        ...

    @abstractmethod
    def health(self) -> dict:
        """Return health status: {"status": "ok"|"degraded"|"down", ...}."""
        ...

    def on_register(self):
        """Called after registration. Override for init logic."""
        pass

    def on_unregister(self):
        """Called before removal. Override for cleanup."""
        pass


# Registry

_providers: dict[str, Provider] = {}
_provider_lock = __import__("threading").Lock()


def _intelligence_disabled() -> bool:
    return _os.environ.get("NOUS_NO_INTELLIGENCE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def register_adapter(provider: Provider) -> bool:
    """Register a provider adapter. Returns True on success."""
    if _intelligence_disabled():
        _log.info("Provider registration blocked by no-intelligence mode")
        return False
    pid = provider.provider_id
    if not pid:
        _log.error("Provider has no provider_id")
        return False
    with _provider_lock:
        _providers[pid] = provider
    try:
        provider.on_register()
    except Exception as e:
        _log.warning("Provider %s on_register failed: %s", pid, e)
    _log.info("Provider registered: %s (%s)", pid, provider.provider_name)

    # Register declared capabilities
    caps = provider.list_capabilities()
    for cap_id in caps:
        try:
            from .capability import register_capability
            register_capability(cap_id, provider=pid)
        except Exception as e:
            _log.warning("Failed to register capability %s for provider %s: %s", cap_id, pid, e)

    return True


def unregister_adapter(provider_id: str) -> bool:
    """Remove a provider and only the capabilities it still owns."""
    with _provider_lock:
        prov = _providers.pop(provider_id, None)
    if prov:
        try:
            from .capability import get_capability, unregister_capability

            for capability_id in prov.list_capabilities():
                record = get_capability(capability_id)
                if record is not None and record.get("provider") == provider_id:
                    unregister_capability(capability_id)
        except Exception as exc:
            _log.warning("Failed to clean capabilities for provider %s: %s", provider_id, exc)
        try:
            prov.on_unregister()
        except Exception:
            pass
        return True
    return False


def get_provider(provider_id: str) -> Provider | None:
    """Get a registered provider by ID."""
    if _intelligence_disabled():
        return None
    return _providers.get(provider_id)


def list_providers() -> list[dict[str, Any]]:
    """List all registered providers with status."""
    if _intelligence_disabled():
        return []
    result = []
    for pid, prov in _providers.items():
        try:
            h = prov.health()
        except Exception:
            h = {"status": "unknown"}
        result.append({
            "provider_id": pid,
            "name": prov.provider_name,
            "capabilities": prov.list_capabilities(),
            "health": h,
        })
    return result


def invoke_via_provider_observation(provider_id: str, capability_id: str, payload: dict):
    """Invoke a provider and return a structured Observation."""
    if _intelligence_disabled():
        return _make_observation(
            "failed",
            capability_id,
            errors=["Intelligence providers are disabled by runtime mode"],
            metadata={
                "provider_id": provider_id,
                "error_code": "NOUS_INTELLIGENCE_DISABLED",
            },
        )
    try:
        from nous_runtime.intelligence.reliability.executor import execute_provider_observation

        obs = execute_provider_observation(provider_id, capability_id, payload=payload)
        obs.metadata.setdefault("compatibility_path", "remote_terminal.nous_core.provider.invoke_via_provider_observation")
        obs.metadata.setdefault("deprecated_path", True)
        obs.metadata.setdefault("diagnostic", "Compatibility provider path routed through canonical reliability executor.")
        return obs
    except Exception as compat_error:
        _log.warning("Canonical provider executor unavailable; using deprecated fallback path: %s", compat_error)
    started = _time_module.time()
    prov = get_provider(provider_id)
    metadata = {
        "provider_id": provider_id,
        "provider_name": getattr(prov, "provider_name", provider_id) if prov else provider_id,
        "error_code": "",
    }
    if not prov:
        metadata["error_code"] = "NOUS_PROVIDER_NOT_FOUND"
        return _make_observation(
            "failed",
            capability_id,
            errors=[f"Provider '{provider_id}' not found"],
            duration_ms=0.0,
            metadata=metadata,
        )

    try:
        result = prov.invoke(capability_id, **payload)
    except TypeError as e:
        try:
            result = prov.invoke(capability_id, payload)
        except Exception:
            metadata["error_code"] = "NOUS_PROVIDER_INVOKE_FAILED"
            duration = int((_time_module.time() - started) * 1000)
            return _make_observation(
                "failed",
                capability_id,
                errors=[str(e)],
                duration_ms=duration,
                metadata=metadata,
            )
    except Exception as e:
        metadata["error_code"] = "NOUS_PROVIDER_INVOKE_FAILED"
        duration = int((_time_module.time() - started) * 1000)
        return _make_observation(
            "failed",
            capability_id,
            errors=[str(e)],
            duration_ms=duration,
            metadata=metadata,
        )

    duration = int((_time_module.time() - started) * 1000)
    if hasattr(result, "to_dict") and getattr(result, "status", None):
        result.duration_ms = result.duration_ms or duration
        result.metadata.setdefault("provider_id", provider_id)
        result.metadata.setdefault("provider_name", metadata["provider_name"])
        return result

    ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
    if ok:
        return _make_observation(
            "success",
            capability_id,
            data={"result": result},
            duration_ms=duration,
            metadata=metadata,
        )

    metadata["error_code"] = "NOUS_PROVIDER_RESULT_FAILED"
    error = result.get("error", "provider invocation failed") if isinstance(result, dict) else "provider invocation failed"
    return _make_observation(
        "failed",
        capability_id,
        errors=[error],
        duration_ms=duration,
        metadata=metadata,
    )


def invoke_via_provider(provider_id: str, capability_id: str, payload: dict) -> dict:
    """Invoke a capability through its registered provider."""
    obs = invoke_via_provider_observation(provider_id, capability_id, payload)
    metadata = obs.metadata or {}
    if obs.status == "success":
        result = obs.data.get("result", obs.data) if isinstance(obs.data, dict) else {"ok": True}
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        else:
            result = dict(result)
            result.setdefault("ok", True)
    else:
        result = {
            "ok": False,
            "error": "; ".join(obs.errors) if obs.errors else "provider invocation failed",
            "_provider_error_code": metadata.get("error_code", ""),
        }
    result["_provider_duration_ms"] = int(obs.duration_ms)
    return result
