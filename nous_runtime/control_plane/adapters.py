# -*- coding: utf-8 -*-
"""
Control Plane Adapters — map existing runtime services to Control Plane API types.

These adapters ensure the Control Plane never reaches into internal
data structures directly. All data flows through typed adapter functions.
"""

from __future__ import annotations

from typing import Any


def adapt_runtime_status() -> dict[str, Any]:
    """Adapt Runtime().status() to RuntimeStatusResponse."""
    try:
        from nous_runtime.runtime.lifecycle import Runtime
        s = Runtime().status()
        return {
            "version": s.version,
            "running": s.running,
            "uptime_seconds": s.uptime_seconds,
            "demo_mode": s.demo_mode,
            "providers_count": s.providers,
            "capabilities_count": s.capabilities,
            "nodes_count": 0,  # populated by node adapter
            "tasks_pending": s.jobs_pending,
            "tasks_running": 0,  # populated by task adapter
            "workspace_path": "",
            "errors": s.errors or [],
        }
    except Exception:
        return {
            "version": "unknown", "running": False, "uptime_seconds": 0,
            "demo_mode": False, "providers_count": 0, "capabilities_count": 0,
            "nodes_count": 0, "tasks_pending": 0, "tasks_running": 0,
            "workspace_path": "", "errors": ["Cannot get runtime status"],
        }


def adapt_nodes_to_response(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt raw node dicts to NodeResponse schema."""
    result = []
    for n in nodes:
        result.append({
            "node_id": n.get("node_id", ""),
            "node_name": n.get("node_name", ""),
            "node_role": n.get("node_role", "personal_node"),
            "platform_os": n.get("platform_os", ""),
            "platform_arch": n.get("platform_arch", ""),
            "platform_hostname": n.get("platform_hostname", ""),
            "runtime_tier": n.get("runtime_tier", "full"),
            "word_size_bits": n.get("word_size_bits", 64),
            "online": n.get("online", False),
            "enabled": n.get("enabled", True),
            "capabilities": n.get("capabilities", []),
            "resources": _adapt_resources(n.get("resources", {})),
            "current_tasks": n.get("current_tasks", 0),
            "max_concurrent_tasks": n.get("max_concurrent_tasks", 1),
            "resource_reservation_pct": n.get("resource_reservation_pct", 0.0),
            "accept_tasks": n.get("accept_tasks", True),
            "tags": n.get("tags", []),
            "is_master": n.get("is_master", False),
            "last_heartbeat": n.get("last_heartbeat"),
            "registered_at": n.get("registered_at"),
            "runtime_version": n.get("runtime_version"),
            "credential_id": _mask_credential(n.get("credential_id")),
        })
    return result


def adapt_models_to_response(models: list[Any]) -> list[dict[str, Any]]:
    """Adapt ModelDescriptor instances to ModelResponse schema."""
    result = []
    for m in models:
        item = {}
        # Handle both dict and object inputs
        if isinstance(m, dict):
            item = {
                "model_id": m.get("model_id", m.get("id", "")),
                "display_name": m.get("display_name", m.get("name", "")),
                "provider_id": m.get("provider_id", ""),
                "endpoint_type": m.get("endpoint_type", "CLOUD_API"),
                "modalities": m.get("modalities", []),
                "capabilities": m.get("capabilities", []),
                "context_length": m.get("context_length", 8192),
                "tool_calling": m.get("tool_calling", False),
                "structured_output": m.get("structured_output", False),
                "reasoning_level": m.get("reasoning_level", "NONE"),
                "coding_level": m.get("coding_level", "NONE"),
                "vision_level": m.get("vision_level", "NONE"),
                "latency_level": m.get("latency_level", "NONE"),
                "cost_level": m.get("cost_level", "NONE"),
                "privacy_class": m.get("privacy_class", "STANDARD"),
                "is_local": m.get("is_local", False),
                "availability": m.get("availability", True),
                "health_status": m.get("health_status", "unknown"),
            }
        else:
            item = {
                "model_id": getattr(m, 'model_id', ''),
                "display_name": getattr(m, 'display_name', ''),
                "provider_id": getattr(m, 'provider_id', ''),
                "endpoint_type": str(getattr(m, 'endpoint_type', 'CLOUD_API')),
                "modalities": list(getattr(m, 'modalities', [])),
                "capabilities": list(getattr(m, 'capabilities', [])),
                "context_length": getattr(m, 'context_length', 8192),
                "tool_calling": getattr(m, 'tool_calling', False),
                "structured_output": getattr(m, 'structured_output', False),
                "reasoning_level": str(getattr(m, 'reasoning_level', 'NONE')),
                "coding_level": str(getattr(m, 'coding_level', 'NONE')),
                "vision_level": str(getattr(m, 'vision_level', 'NONE')),
                "latency_level": str(getattr(m, 'latency_level', 'NONE')),
                "cost_level": str(getattr(m, 'cost_level', 'NONE')),
                "privacy_class": str(getattr(m, 'privacy_class', 'STANDARD')),
                "is_local": getattr(m, 'is_local', False),
                "availability": getattr(m, 'availability', True),
                "health_status": "unknown",
            }
        result.append(item)
    return result


def adapt_providers_to_response(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt raw provider dicts to ProviderResponse schema."""
    result = []
    for p in providers:
        result.append({
            "provider_id": p.get("id", p.get("provider_id", "")),
            "name": p.get("name", ""),
            "api_base_url": p.get("api_base_url"),
            "credential_ref": _mask_credential(p.get("credential_ref")),
            "capabilities": p.get("capabilities", []),
            "models_count": p.get("models_count", 0),
            "health_status": p.get("health", {}).get("status", "unknown"),
            "last_health_check": p.get("last_health_check"),
            "enabled": p.get("enabled", True),
            "metadata": p.get("metadata", {}),
        })
    return result


# Helpers

def _adapt_resources(resources: dict[str, Any] | None) -> dict[str, Any] | None:
    if not resources:
        return None
    return {
        "cpu_cores": resources.get("cpu_cores"),
        "cpu_percent": resources.get("cpu_percent"),
        "memory_mb": resources.get("memory_mb"),
        "memory_percent": resources.get("memory_percent"),
        "gpu_name": resources.get("gpu_name"),
        "gpu_memory_mb": resources.get("gpu_memory_mb"),
        "disk_total_mb": resources.get("disk_total_mb"),
        "disk_percent": resources.get("disk_percent"),
        "network_status": resources.get("network_status"),
    }


def _mask_credential(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("env:"):
        return value[:4] + "****"
    if value.startswith("secret:"):
        return value[:7] + "****"
    if value.startswith("keyring:"):
        return value[:8] + "****"
    if len(value) > 4:
        return value[:4] + "****"
    return "****"
