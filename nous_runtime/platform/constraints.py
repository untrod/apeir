# -*- coding: utf-8 -*-
"""
Platform constraints — capability filtering, scheduler exclusion rules,
and optional dependency paths for multi-architecture deployments.

All Scheduler hard-constraint pre-filtering MUST go through the functions
in this module before any evidence/cost/latency-based selection.
"""

from __future__ import annotations

import logging

from nous_runtime.platform.models import (
    Architecture,
    LITE_NODE_ALWAYS_ALLOWED,
    LITE_NODE_RESTRICTED_CAPABILITIES,
    RuntimeTier,
)

_log = logging.getLogger("nous.platform.constraints")


# Scheduler hard-constraint filter

def platform_hard_filter(
    node_arch: Architecture,
    node_tier: RuntimeTier,
    requested_capabilities: list[str],
) -> list[str]:
    """
    Hard-constraint pre-filter for the Scheduler.

    This MUST be called BEFORE any evidence-based, cost-based, or latency-based
    selection. Lite nodes are excluded from capabilities they cannot execute.

    Returns the list of capabilities the node CAN execute.
    """
    if node_tier == RuntimeTier.FULL:
        return requested_capabilities

    # Lite tier: strictly filter
    allowed = []
    for cap in requested_capabilities:
        if cap in LITE_NODE_RESTRICTED_CAPABILITIES:
            _log.debug("Lite node %s excluded from capability: %s", node_arch.value, cap)
            continue
        if cap in LITE_NODE_ALWAYS_ALLOWED:
            allowed.append(cap)
    return allowed


def is_node_eligible_for_capability(
    node_arch: Architecture,
    node_tier: RuntimeTier,
    capability_id: str,
) -> bool:
    """Quick eligibility check for a single node/capability pair."""
    if node_tier == RuntimeTier.FULL:
        return True
    return capability_id not in LITE_NODE_RESTRICTED_CAPABILITIES


def filter_eligible_nodes(
    nodes: list[dict],  # Each dict must have 'arch' and 'tier' keys
    capability_id: str,
) -> list[dict]:
    """
    From a list of node dicts, return only those eligible for a capability.

    Node dict format: {'node_id': str, 'arch': Architecture, 'tier': RuntimeTier, ...}
    """
    return [
        n for n in nodes
        if is_node_eligible_for_capability(
            n.get("arch", Architecture.AMD64),
            n.get("tier", RuntimeTier.FULL),
            capability_id,
        )
    ]


# Optional dependency paths

def get_optional_dependency_mapping() -> dict[str, dict[str, str]]:
    """
    Return a mapping: {package_name: {arch: fallback_action}}
    Where fallback_action is one of: 'install', 'remote', 'disable', 'alternative:{pkg}'

    Heavy dependencies get 'disable' on ARMv7, 'remote' on ARM64 without GPU.
    """
    mapping: dict[str, dict[str, str]] = {
        # Local LLM inference
        "llama-cpp-python": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "ollama": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "vllm": {
            "amd64": "install",   # Requires CUDA GPU
            "arm64": "disable",   # No CUDA on most ARM64
            "armv7": "disable",
            "armv6": "disable",
        },
        "torch": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "torchvision": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        # Vector DB
        "chromadb": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        # Embeddings
        "sentence-transformers": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "fastembed": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        # Speech
        "whisper": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "edge-tts": {
            "amd64": "install",
            "arm64": "remote",   # Remote TTS service
            "armv7": "remote",
            "armv6": "remote",
        },
        # Desktop
        "tauri": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        "pywebview": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
        # Heavy agent runtime
        "nous-agent-runtime": {
            "amd64": "install",
            "arm64": "install",
            "armv7": "disable",
            "armv6": "disable",
        },
    }
    return mapping


def get_dependency_fallback(
    package_name: str,
    arch: Architecture,
) -> str:
    """
    Get the fallback action for a package on a given architecture.
    Returns: 'install', 'remote', 'disable', or 'alternative:{pkg}'.
    """
    mapping = get_optional_dependency_mapping()
    pkg_map = mapping.get(package_name, {})
    return pkg_map.get(arch.value, "install")


# Build target generation

BUILD_TARGETS = {
    "linux-amd64-gnu-64-full": {
        "os": "linux",
        "arch": "amd64",
        "abi": "gnu",
        "tier": "full",
        "description": "Linux x86_64 — Server Primary, Desktop, CUDA",
    },
    "linux-arm64-gnu-64-full": {
        "os": "linux",
        "arch": "arm64",
        "abi": "gnu",
        "tier": "full",
        "description": "Linux ARM64 — Server Primary, Jetson Edge Worker",
    },
    "windows-amd64-msvc-64-full": {
        "os": "windows",
        "arch": "amd64",
        "abi": "msvc",
        "tier": "full",
        "description": "Windows x86_64 — Desktop, CUDA GPU Worker",
    },
    "windows-arm64-msvc-64-full": {
        "os": "windows",
        "arch": "arm64",
        "abi": "msvc",
        "tier": "full",
        "description": "Windows ARM64 — Surface Pro, Snapdragon X",
    },
    "linux-armv7-gnueabihf-32-lite": {
        "os": "linux",
        "arch": "armv7",
        "abi": "gnueabihf",
        "tier": "lite",
        "description": "Linux ARMv7 Lite — Raspberry Pi 3/4, Edge sensors",
    },
}

TIER1_TARGETS = [t for t, info in BUILD_TARGETS.items() if info["tier"] == "full"]
TIER2_TARGETS = [t for t, info in BUILD_TARGETS.items() if info["tier"] == "lite"]
