"""Process-wide LLM-off mode for the Track R reality baseline."""

from __future__ import annotations

import os
from typing import Any


ENV_NAME = "NOUS_NO_INTELLIGENCE"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def no_intelligence_enabled() -> bool:
    return os.environ.get(ENV_NAME, "").strip().lower() in _TRUE_VALUES


def activate_no_intelligence() -> None:
    """Disable and remove model providers for the lifetime of this process."""

    os.environ[ENV_NAME] = "1"
    from nous_runtime.compat.provider import _providers, unregister_adapter

    for provider_id in list(_providers):
        unregister_adapter(provider_id)
    from nous_runtime.model_runtime.factory import gateway_service

    gateway_service.clear()


def reality_baseline_status() -> dict[str, Any]:
    """Return honest Runtime/Kernel state while all intelligence is disabled."""

    activate_no_intelligence()
    from nous_runtime.api.kernel_status import kernel_status
    from nous_runtime.runtime.bootstrap import NousRuntime

    runtime = NousRuntime.bootstrap(no_intelligence=True, force=True)
    snapshot = runtime.snapshot()
    kernel = kernel_status(cache_seconds=0.0)
    return {
        "mode": "no-intelligence",
        "intelligence_providers": snapshot.provider_count,
        "runtime": "healthy" if snapshot.ready else snapshot.state.value,
        "kernel": "healthy" if kernel.get("ready") else str(kernel.get("state") or "unhealthy").lower(),
        "kernel_ready": bool(kernel.get("ready")),
    }


__all__ = [
    "ENV_NAME",
    "activate_no_intelligence",
    "no_intelligence_enabled",
    "reality_baseline_status",
]
