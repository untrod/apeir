"""Normalized extension contracts and compatibility adapters.

Importing an extension never executes its code and never grants a capability;
execution remains owned by the Kernel/NKI governance path.
"""

from nous_runtime.extensions.adapters import ExtensionInspector
from nous_runtime.extensions.models import (
    CapabilityRequest,
    CompatibilityLevel,
    ExtensionManifest,
    SkillSpec,
    ToolSpec,
)
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.extensions.permissions import ExtensionPermissionService, PermissionDiff
from nous_runtime.extensions.executor import (
    AdapterResult,
    ExtensionExecutionError,
    ExtensionExecutionResult,
    UnifiedExtensionExecutor,
)
from nous_runtime.extensions.openapi import (
    OpenApiExecutionAdapter,
    OpenApiExecutionError,
    OpenApiExecutionPolicy,
)
from nous_runtime.extensions.mcp_sdk import McpSdkExecutionAdapter, McpSdkExecutionError
from nous_runtime.extensions.exporter import (
    ExportCompatibility,
    ExportLossReport,
    ExtensionExportError,
    ExtensionExporter,
    assess_export_compatibility,
    canonical_semantics,
)

__all__ = [
    "CapabilityRequest",
    "CompatibilityLevel",
    "ExtensionInspector",
    "ExtensionManifest",
    "ExtensionRegistry",
    "ExtensionPermissionService",
    "PermissionDiff",
    "AdapterResult",
    "ExtensionExecutionError",
    "ExtensionExecutionResult",
    "UnifiedExtensionExecutor",
    "OpenApiExecutionAdapter",
    "OpenApiExecutionError",
    "OpenApiExecutionPolicy",
    "McpSdkExecutionAdapter",
    "McpSdkExecutionError",
    "ExportCompatibility",
    "ExportLossReport",
    "ExtensionExportError",
    "ExtensionExporter",
    "assess_export_compatibility",
    "canonical_semantics",
    "SkillSpec",
    "ToolSpec",
]
