"""Process lifecycle for the APEIR Distribution.

This module coordinates user-space services. It is deliberately separate
from the authoritative Rust Kernel: it cannot mint permits, leases, journal
records, or Kernel state.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.runtime.bootstrap import NousRuntime

log = logging.getLogger("apeir.runtime")

# Stable trace phase retained for the Runtime Pipeline public contract.
RECEIVED = "received"


@dataclass
class RuntimeStatus:
    running: bool = False
    version: str = __import__("nous_runtime.version", fromlist=["__version__"]).__version__
    uptime_seconds: float = 0.0
    providers: int = 0
    capabilities: int = 0
    packs: int = 0
    devices: int = 0
    events_total: int = 0
    jobs_pending: int = 0
    demo_mode: bool = False
    errors: list[str] = field(default_factory=list)


class DistributionRuntime:
    """Own APEIR's user-space service lifecycle.

    Effect authorization remains exclusively in the separately versioned
    APEIR Kernel. Starting this object only prepares databases, registries,
    providers, and the model gateway.
    """

    def __init__(self) -> None:
        self._started = False
        self._start_time = 0.0
        self._status = RuntimeStatus()
        self._runtime: NousRuntime | None = None

    def start(
        self,
        demo_mode: bool = False,
        config_overrides: dict[str, Any] | None = None,
    ) -> RuntimeStatus:
        del config_overrides
        if self._started:
            return self.status()
        self._start_time = time.time()
        errors: list[str] = []
        if demo_mode or os.environ.get("NOUS_DEMO_MODE") == "1":
            os.environ["NOUS_DEMO_MODE"] = "1"
            self._status.demo_mode = True
        for name, operation in (
            ("migrations", "run_migrations"),
            ("capabilities", "seed_capabilities"),
            ("devices", "sync_legacy_devices"),
            ("jobs", "recover_stale_jobs"),
        ):
            try:
                from nous_runtime.services import lifecycle

                value = getattr(lifecycle, operation)()
                if name == "capabilities":
                    self._status.capabilities = int(value or 0)
                elif name == "devices":
                    self._status.devices = int(value or 0)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                log.error("Distribution startup step %s failed: %s", name, exc)
        try:
            from nous_runtime.services.lifecycle import start_event_dispatcher

            start_event_dispatcher(interval=5.0)
        except Exception as exc:
            errors.append(f"dispatcher: {exc}")
        self._runtime = NousRuntime.bootstrap()
        self._started = True
        self._status.running = True
        self._status.errors = errors + list(self._runtime.warnings)
        return self.status()

    def stop(self) -> None:
        if not self._started:
            return
        try:
            from nous_runtime.services.lifecycle import stop_event_dispatcher

            stop_event_dispatcher()
        except Exception:
            pass
        if self._runtime is not None:
            self._runtime.stop()
        self._started = False
        self._status.running = False

    def status(self) -> RuntimeStatus:
        snapshot = self._runtime.snapshot() if self._runtime is not None else None
        self._status.running = bool(snapshot and snapshot.ready and self._started)
        self._status.uptime_seconds = (
            time.time() - self._start_time if self._started else 0.0
        )
        self._status.providers = int(snapshot.provider_count if snapshot else 0)
        self._status.capabilities = self._count("count_capabilities")
        self._status.devices = self._count("count_devices")
        self._status.events_total = self._count("count_events")
        self._status.jobs_pending = self._count("count_pending_jobs")
        return self._status

    @staticmethod
    def _count(name: str) -> int:
        try:
            from nous_runtime.services import lifecycle

            return int(getattr(lifecycle, name)() or 0)
        except Exception:
            return 0


# Source-compatible name for callers that previously imported Runtime.
Runtime = DistributionRuntime

__all__ = ["DistributionRuntime", "RECEIVED", "Runtime", "RuntimeStatus"]
