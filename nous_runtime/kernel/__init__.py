# -*- coding: utf-8 -*-
"""Deprecated Python compatibility models.

This package is not the APEIR Kernel and has no execution authority. New
product code must use the Rust Kernel through compat.nki_client. These
exports remain temporarily available for nous.*.v1 compatibility.
"""

from __future__ import annotations

from nous_runtime.kernel.object_model import (
    Condition,
    Health,
    NousObject,
    ObjectMetadata,
    Phase,
)
from nous_runtime.kernel.error_codes import (
    ErrorCode,
    NousResult,
    is_retryable,
    severity,
)
from nous_runtime.kernel.identity import (
    CapabilityGrant,
    GrantScope,
    NodeConnectivity,
    NodeIdentity,
    NodeRole,
    SecretRef,
    UserIdentity,
    NODE_CONNECTIVITY_TRANSITIONS,
)
from nous_runtime.kernel.state_machine import (
    Checkpoint,
    InvalidTransitionError,
    Lease,
    StateMachine,
    TransitionRecord,
)
from nous_runtime.kernel.registry_base import (
    RegistryBase,
    RegistryEvent,
)
from nous_runtime.kernel.node import (
    Node,
    NodeCapabilities,
    NodeResources,
)
from nous_runtime.kernel.task import (
    ExecutionTicket,
    Task,
    TaskBudget,
    TaskFingerprint,
    TaskPhase,
    TASK_TRANSITIONS,
    is_task_active,
    is_task_terminal,
)
from nous_runtime.kernel.config import (
    NousConfig,
    get_config,
    reload_config,
)
from nous_runtime.kernel.checkpoint_store import (
    CheckpointStore,
    CheckpointRecord,
)
from nous_runtime.kernel.server import (
    NousServer,
    ServerHealth,
)
from nous_runtime.kernel.resource_model import (
    ResourceVector,
    ResourceLimits,
    ResourceDomain,
    ResourceLease,
    ResourceClaim,
    ResourceSlice,
    PriorityClass,
    PreemptionPolicy,
)
from nous_runtime.kernel.device_model import (
    Device,
    DeviceSpec,
    DeviceStatus,
    DevicePhase,
    DeviceClass,
    DeviceType,
    DeviceRegistry,
    TopologyLink,
    DEVICE_CLASS_CPU,
    DEVICE_CLASS_NVIDIA_CUDA,
    DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM,
    DEVICE_CLASS_NVIDIA_JETSON,
    DEVICE_CLASS_AMD_ROCM,
    DEVICE_CLASS_INTEL_OPENVINO,
    DEVICE_CLASS_QUALCOMM_QNN,
    DEVICE_CLASS_APPLE_METAL,
    DEVICE_CLASS_REMOTE_LLM,
    DEVICE_CLASS_REMOTE_COMPUTE,
)
from nous_runtime.kernel.hardware_discovery import (
    discover_all_devices,
    discover_cpu_devices,
    discover_nvidia_devices,
    build_resource_slices,
)
from nous_runtime.kernel.sandbox import (
    ProcessSandbox,
    SandboxPolicy,
    SandboxResult,
)

__all__ = [
    # Object model
    "Condition",
    "Health",
    "NousObject",
    "ObjectMetadata",
    "Phase",
    # Error codes
    "ErrorCode",
    "NousResult",
    "is_retryable",
    "severity",
    # Identity
    "CapabilityGrant",
    "GrantScope",
    "NodeConnectivity",
    "NodeIdentity",
    "NodeRole",
    "SecretRef",
    "UserIdentity",
    "NODE_CONNECTIVITY_TRANSITIONS",
    # State machine
    "Checkpoint",
    "InvalidTransitionError",
    "Lease",
    "StateMachine",
    "TransitionRecord",
    # Registry
    "RegistryBase",
    "RegistryEvent",
    # Node
    "Node",
    "NodeCapabilities",
    "NodeResources",
    # Task
    "ExecutionTicket",
    "Task",
    "TaskBudget",
    "TaskFingerprint",
    "TaskPhase",
    "TASK_TRANSITIONS",
    "is_task_active",
    "is_task_terminal",
    # Config
    "NousConfig",
    "get_config",
    "reload_config",
    # Persistence
    "CheckpointStore",
    "CheckpointRecord",
    # Server
    "NousServer",
    "ServerHealth",
    # Resource model (RC6)
    "ResourceVector",
    "ResourceLimits",
    "ResourceDomain",
    "ResourceLease",
    "ResourceClaim",
    "ResourceSlice",
    "PriorityClass",
    "PreemptionPolicy",
    # Device model (RC6)
    "Device",
    "DeviceSpec",
    "DeviceStatus",
    "DevicePhase",
    "DeviceClass",
    "DeviceType",
    "DeviceRegistry",
    "TopologyLink",
    "DEVICE_CLASS_CPU",
    "DEVICE_CLASS_NVIDIA_CUDA",
    "DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM",
    "DEVICE_CLASS_NVIDIA_JETSON",
    "DEVICE_CLASS_AMD_ROCM",
    "DEVICE_CLASS_INTEL_OPENVINO",
    "DEVICE_CLASS_QUALCOMM_QNN",
    "DEVICE_CLASS_APPLE_METAL",
    "DEVICE_CLASS_REMOTE_LLM",
    "DEVICE_CLASS_REMOTE_COMPUTE",
    # Hardware discovery (RC6)
    "discover_all_devices",
    "discover_cpu_devices",
    "discover_nvidia_devices",
    "build_resource_slices",
    # Sandbox (RC6)
    "ProcessSandbox",
    "SandboxPolicy",
    "SandboxResult",
]
