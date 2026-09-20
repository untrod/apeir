# -*- coding: utf-8 -*-
"""Crash recovery and self-healing for the Nous Runtime daemon."""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.daemon.recovery")


@dataclass
class CrashRecord:
    timestamp: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    component: str = ""
    recovered: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "component": self.component,
            "recovered": self.recovered,
        }


class CrashRecovery:
    """Monitors components and attempts automatic recovery on failure.

    Implements:
    - Crash detection and recording
    - Automatic restart with exponential backoff
    - Crash log persistence
    - Recovery state tracking
    """

    MAX_CRASHES_PER_WINDOW = 5
    CRASH_WINDOW_SECONDS = 300  # 5 minutes
    INITIAL_BACKOFF = 1.0
    MAX_BACKOFF = 60.0

    def __init__(self, workspace: str = ""):
        self._workspace = Path(workspace) if workspace else Path.home() / ".nous"
        self._crash_log_path = self._workspace / "crash_log.jsonl"
        self._crash_history: list[CrashRecord] = []
        self._recovery_handlers: dict[str, callable] = {}
        self._consecutive_failures = 0
        self._last_crash_time = 0.0
        self._lock = threading.Lock()
        self._running = False

    def register_handler(
        self, component: str, handler: callable
    ) -> None:
        """Register a recovery handler for a component."""
        self._recovery_handlers[component] = handler

    def record_crash(
        self,
        error: Exception,
        component: str = "unknown",
    ) -> CrashRecord:
        """Record a crash and attempt recovery."""
        now = datetime.now(timezone.utc)
        record = CrashRecord(
            timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            error_type=type(error).__name__,
            error_message=str(error),
            traceback=traceback.format_exc(),
            component=component,
        )

        with self._lock:
            self._crash_history.append(record)
            self._consecutive_failures += 1
            self._last_crash_time = time.monotonic()
            self._persist_crash(record)

        _log.error(
            "Crash recorded [%s] in %s: %s",
            record.error_type,
            component,
            record.error_message,
        )

        # Attempt recovery
        handler = self._recovery_handlers.get(component)
        if handler:
            try:
                handler()
                record.recovered = True
                _log.info("Recovery handler for '%s' executed", component)
            except Exception as exc:
                _log.error("Recovery handler for '%s' failed: %s", component, exc)

        return record

    def should_restart(self) -> bool:
        """Check if the daemon should restart after a crash."""
        now = time.monotonic()
        with self._lock:
            if self._consecutive_failures == 0:
                return True
            # Clean old entries outside the window
            recent = [
                c for c in self._crash_history
                if now - self._parse_timestamp(c.timestamp) < self.CRASH_WINDOW_SECONDS
            ]
            if len(recent) >= self.MAX_CRASHES_PER_WINDOW:
                _log.critical(
                    "Too many crashes (%d) in %ds window. Not restarting.",
                    len(recent),
                    self.CRASH_WINDOW_SECONDS,
                )
                return False
            return True

    def get_backoff_delay(self) -> float:
        """Calculate exponential backoff delay."""
        delay = min(
            self.INITIAL_BACKOFF * (2 ** max(0, self._consecutive_failures - 1)),
            self.MAX_BACKOFF,
        )
        return delay

    def reset_failure_count(self) -> None:
        """Reset consecutive failure counter after stable period."""
        with self._lock:
            self._consecutive_failures = 0
            _log.info("Failure counter reset — daemon stable")

    def get_crash_history(
        self, limit: int = 20
    ) -> list[dict]:
        """Get recent crash records."""
        with self._lock:
            return [
                c.to_dict()
                for c in self._crash_history[-limit:]
            ]

    def get_status(self) -> dict[str, Any]:
        """Get recovery subsystem status."""
        with self._lock:
            return {
                "consecutive_failures": self._consecutive_failures,
                "total_crashes": len(self._crash_history),
                "last_crash": self._crash_history[-1].to_dict()
                if self._crash_history
                else None,
                "registered_handlers": list(self._recovery_handlers.keys()),
            }

    def _persist_crash(self, record: CrashRecord) -> None:
        """Append crash record to JSONL file."""
        import json
        try:
            self._workspace.mkdir(parents=True, exist_ok=True)
            with open(self._crash_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            _log.warning("Could not persist crash record: %s", exc)

    def _parse_timestamp(self, ts: str) -> float:
        """Parse ISO timestamp to epoch."""
        try:
            from datetime import datetime as dt
            return dt.strptime(
                ts, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return 0.0


# Built-in recovery handlers

def create_default_recovery(workspace: str = "") -> CrashRecovery:
    """Create a CrashRecovery with sensible defaults."""
    recovery = CrashRecovery(workspace)

    def recover_runtime() -> None:
        """Attempt to reinitialize the runtime after a crash."""
        try:
            from nous_runtime.runtime.lifecycle import Runtime
            rt = Runtime()
            _log.info("Runtime reinitialized: %s", rt.status().version)
        except Exception as exc:
            _log.error("Runtime recovery failed: %s", exc)
            raise

    def recover_database() -> None:
        """Attempt database reconnection after failure."""
        try:
            from nous_runtime.services.database import run_migrations
            run_migrations()
            _log.info("Database recovered successfully")
        except Exception as exc:
            _log.error("Database recovery failed: %s", exc)
            raise

    def recover_providers() -> None:
        """Re-register providers after failure."""
        try:
            from nous_runtime.cli.provider_setup import (
                load_providers_from_config,
            )
            load_providers_from_config()
            _log.info("Providers re-registered")
        except Exception as exc:
            _log.error("Provider recovery failed: %s", exc)
            raise

    recovery.register_handler("runtime", recover_runtime)
    recovery.register_handler("database", recover_database)
    recovery.register_handler("providers", recover_providers)

    return recovery


__all__ = ["CrashRecord", "CrashRecovery", "create_default_recovery"]
