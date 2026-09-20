# -*- coding: utf-8 -*-
"""APEIR Distribution Python API.

The package root intentionally stays lightweight. Importing any
`nous_runtime.*` submodule should not eagerly load optional subsystems such as
packs, providers, or learning modules. Public root re-exports are resolved
on demand via `__getattr__`.
"""

from __future__ import annotations

from nous_runtime.version import __version__

__all__ = [
    "__version__",
    "Provider",
    "Envelope",
    "Runtime",
    "ProviderRegistry",
    "register_adapter",
    "unregister_adapter",
    "list_providers",
    "invoke_via_provider_observation",
    "CapabilityLifecycle",
    "PackManifest",
    "PackRegistry",
    "MasteryState",
    "SpacedRepetitionScheduler",
    "ProgressTracker",
    "record_experience",
    "experience_stats",
    "TraceContext",
    "ExecutionTimeline",
    "get_trace_id",
    "NousObject",
    "Phase",
    "Health",
    "Condition",
]


def __getattr__(name: str):
    if name == "Provider":
        from nous_runtime.compat.provider import Provider
        return Provider
    if name == "Envelope":
        from nous_runtime.compat.protocol import Envelope
        return Envelope
    if name == "Runtime":
        from nous_runtime.runtime.lifecycle import Runtime
        return Runtime
    if name == "ProviderRegistry":
        from nous_runtime.provider.registry import ProviderRegistry
        return ProviderRegistry
    if name in {
        "register_adapter",
        "unregister_adapter",
        "list_providers",
        "invoke_via_provider_observation",
    }:
        from nous_runtime.provider import base
        return getattr(base, name)
    if name == "CapabilityLifecycle":
        from nous_runtime.capability.lifecycle import CapabilityLifecycle
        return CapabilityLifecycle
    if name == "PackManifest":
        from nous_runtime.pack.manifest import PackManifest
        return PackManifest
    if name == "PackRegistry":
        from nous_runtime.pack.registry import PackRegistry
        return PackRegistry
    if name in {"MasteryState", "SpacedRepetitionScheduler", "ProgressTracker"}:
        from nous_runtime.learning import state
        return getattr(state, name)
    if name == "record_experience":
        from nous_runtime.learning.experience import record
        return record
    if name == "experience_stats":
        from nous_runtime.learning.experience import stats
        return stats
    if name in {"TraceContext", "ExecutionTimeline", "get_trace_id"}:
        from nous_runtime.kernel import tracing
        return getattr(tracing, name)
    if name in {"NousObject", "Phase", "Health", "Condition"}:
        from nous_runtime.kernel import object_model
        return getattr(object_model, name)
    raise AttributeError(f"module 'nous_runtime' has no attribute {name!r}")
