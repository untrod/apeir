# -*- coding: utf-8 -*-
"""Truthful capability availability derived from executors and live providers."""

from __future__ import annotations

import logging
import shutil
from typing import Any


def _capability_view(cap: dict[str, Any], *, executor_type: str) -> dict[str, Any]:
    scope = {
        "provider": "kernel-model",
        "runtime": "runtime-service",
        "subprocess": "sandbox-subprocess",
        "node": "remote-node",
    }.get(executor_type, "unknown")
    return {
        "name": cap.get("name", "?"),
        "provider": cap.get("provider", "") or "(none)",
        "category": cap.get("category", ""),
        "risk": cap.get("risk", "low"),
        "description": cap.get("description", ""),
        "executor_type": executor_type,
        "execution_scope": scope,
        "authorization": (
            "explicit" if cap.get("requires_auth") or cap.get("privileged") else "none"
        ),
    }


def check_availability() -> dict[str, Any]:
    """Return truthful available/unavailable capability records and counts.

    Provider executors require a live provider that declares the capability.
    Subprocess executors require an immutable registered command and an installed
    executable. Node executors require a live execution node and therefore stay
    unavailable until node discovery is wired into this authority.
    """
    available: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    try:
        from nous_runtime.compat.capability import list_capabilities

        caps = list_capabilities()
    except Exception as exc:
        logging.warning("Failed to list capabilities: %s", exc)
        caps = []

    if not caps:
        return {
            "available": [],
            "unavailable": [],
            "summary": {"registered": 0, "available": 0, "unavailable": 0},
        }

    provider_health: dict[str, str] = {}
    provider_caps: dict[str, set[str]] = {}
    try:
        from nous_runtime.provider.registry import registry

        for provider_record in registry.list_all():
            provider_id = provider_record.get("id", provider_record.get("name", ""))
            provider_health[provider_id] = provider_record.get("health", {}).get("status", "unknown")
            provider_caps[provider_id] = set(provider_record.get("capabilities", []))
    except Exception as exc:
        logging.warning("Failed to query provider registry: %s", exc)

    for cap in caps:
        if not isinstance(cap, dict):
            continue
        name = cap.get("name", "?")
        provider = cap.get("provider", "")
        metadata = cap.get("metadata") if isinstance(cap.get("metadata"), dict) else {}
        executor_type = str(metadata.get("executor_type") or "provider").strip().lower()
        view = _capability_view(cap, executor_type=executor_type)

        if not cap.get("enabled", True):
            unavailable.append({**view, "availability_state": "unavailable", "reason": "capability is disabled"})
            continue

        if executor_type == "subprocess":
            command = metadata.get("command")
            if not command and metadata.get("executable"):
                command = [metadata["executable"], *metadata.get("args", [])]
            if not isinstance(command, list) or not command or not str(command[0]).strip():
                unavailable.append({**view, "availability_state": "unavailable", "reason": "subprocess command is not configured"})
                continue
            executable = str(command[0])
            resolved = shutil.which(executable)
            if not resolved:
                unavailable.append({**view, "availability_state": "unavailable", "reason": f"executable is not installed: {executable}"})
                continue
            available.append({**view, "availability_state": "requires_authorization", "executable": resolved})
            continue

        if executor_type == "runtime":
            service = str(metadata.get("service") or "")
            from nous_runtime.capability.runtime_executor import supports_runtime_capability
            if not supports_runtime_capability(name):
                unavailable.append({
                    **view,
                    "availability_state": "unavailable",
                    "reason": "built-in Runtime capability is not connected to the central dispatcher",
                })
                continue
            available.append({
                **view,
                "availability_state": "requires_authorization",
                "service": service,
                "kernel_traversed": False,
            })
            continue

        if executor_type == "node":
            unavailable.append({**view, "availability_state": "unavailable", "reason": "requires a connected execution node"})
            continue

        if not provider or provider not in provider_health:
            unavailable.append({**view, "availability_state": "unavailable", "reason": f"requires {provider or 'a'} provider"})
            continue

        health = provider_health[provider]
        if health == "down":
            unavailable.append({**view, "availability_state": "unavailable", "reason": f"provider {provider} is down"})
            continue

        declared = provider_caps.get(provider, set())
        if declared and not any(name == item or name.startswith(item.rstrip("*")) for item in declared):
            unavailable.append({**view, "availability_state": "unavailable", "reason": f"not declared by provider {provider}"})
            continue

        available.append({**view, "availability_state": "available", "kernel_traversed": True})

    available.sort(key=lambda item: (item.get("category", ""), item["name"]))
    unavailable.sort(key=lambda item: item["name"])
    return {
        "available": available,
        "unavailable": unavailable,
        "summary": {
            "registered": len(available) + len(unavailable),
            "available": len(available),
            "unavailable": len(unavailable),
            "requires_authorization": sum(
                item.get("availability_state") == "requires_authorization"
                for item in available
            ),
        },
    }
