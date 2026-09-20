# -*- coding: utf-8 -*-
"""
Nous Platform Service — Unified architecture/ABI/word-size/tier abstraction.

All platform introspection flows through this module. No other module may
use ``platform``, ``os.uname``, ``sys.maxsize``, or inline ``# if arm``
checks directly — they must go through PlatformService.

Tier system:
  - Tier 1 (full):  amd64, arm64  — Server Primary, full desktop, local LLM
  - Tier 2 (lite):  armv7, arm32  — Edge Worker, restricted capabilities only
"""

from nous_runtime.platform.models import (
    ABI,
    ALL_CAPABILITIES,
    Architecture,
    LITE_NODE_ALWAYS_ALLOWED,
    LITE_NODE_RESTRICTED_CAPABILITIES,
    PLATFORM_CAPABILITY_ALLOWLIST,
    PlatformInfo,
    RuntimeTier,
    WordSize,
)
from nous_runtime.platform.detector import detect_platform
from nous_runtime.platform.service import PlatformService, platform_service
from nous_runtime.platform.adapter import PlatformAdapter, get_platform_adapter, PlatformCapabilities
from nous_runtime.platform.constraints import (
    BUILD_TARGETS,
    TIER1_TARGETS,
    TIER2_TARGETS,
    filter_eligible_nodes,
    get_dependency_fallback,
    get_optional_dependency_mapping,
    is_node_eligible_for_capability,
    platform_hard_filter,
)

__all__ = [
    # Models
    "Architecture",
    "ABI",
    "WordSize",
    "RuntimeTier",
    "PlatformInfo",
    "ALL_CAPABILITIES",
    "LITE_NODE_ALWAYS_ALLOWED",
    "LITE_NODE_RESTRICTED_CAPABILITIES",
    "PLATFORM_CAPABILITY_ALLOWLIST",
    # Detection
    "detect_platform",
    # Service
    "PlatformService",
    "platform_service",
    # Adapter (backward compat)
    "PlatformAdapter",
    "get_platform_adapter",
    "PlatformCapabilities",
    # Constraints
    "platform_hard_filter",
    "is_node_eligible_for_capability",
    "filter_eligible_nodes",
    "get_optional_dependency_mapping",
    "get_dependency_fallback",
    "BUILD_TARGETS",
    "TIER1_TARGETS",
    "TIER2_TARGETS",
]
