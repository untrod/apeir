# -*- coding: utf-8 -*-
"""
Control Plane Recovery — crash resilience and state restoration.

Integrates with the existing Daemon recovery system and adds
Control-Plane-specific recovery policies:
- In-flight task recovery on restart
- WebSocket event backfill
- UI session persistence
- Safe mode boot
- Corrupted state diagnosis
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

log = logging.getLogger("nous.control_plane.recovery")


class RecoveryAction(str, Enum):
    NONE = "NONE"
    REINITIALIZE = "REINITIALIZE"
    RESTORE_TASKS = "RESTORE_TASKS"
    RESTORE_EVENTS = "RESTORE_EVENTS"
    REBUILD_INDEX = "REBUILD_INDEX"
    SAFE_MODE = "SAFE_MODE"
    FULL_RESET = "FULL_RESET"


class CrashRecord:
    """Record of a runtime crash for diagnosis."""
    def __init__(self, crash_id: str, timestamp: str, error: str, stack_trace: str = ""):
        self.crash_id = crash_id
        self.timestamp = timestamp
        self.error = error
        self.stack_trace = stack_trace
        self.recovery_action: RecoveryAction = RecoveryAction.NONE
        self.recovery_success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "crash_id": self.crash_id,
            "timestamp": self.timestamp,
            "error": self.error,
            "stack_trace": self.stack_trace,
            "recovery_action": self.recovery_action.value,
            "recovery_success": self.recovery_success,
        }


class ControlPlaneRecovery:
    """
    Crash recovery and state restoration for the Control Plane.

    Recovery policies:
    1. Crash detection: monitors RuntimeState
    2. Crash log: persists crash records to JSONL
    3. Backoff: exponential, 1s → 60s max, 5 crashes/300s = permanent stop
    4. State restoration: recovers in-flight tasks, events, UI sessions
    5. Safe mode: minimal boot with diagnostics
    """

    _instance: ControlPlaneRecovery | None = None

    def __init__(self):
        self._crash_log: list[CrashRecord] = []
        self._crash_count: int = 0
        self._crash_window_start: float = 0.0
        self._crash_window_max: int = 5
        self._crash_window_seconds: float = 300.0
        self._backoff_base: float = 1.0
        self._backoff_max: float = 60.0
        self._permanent_stop: bool = False
        self._crash_log_path: str = ""

    @classmethod
    def get(cls) -> ControlPlaneRecovery:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, workspace_path: str):
        """Initialize recovery with workspace path for crash log persistence."""
        self._crash_log_path = os.path.join(workspace_path, ".nous", "crash_log.jsonl")
        os.makedirs(os.path.dirname(self._crash_log_path), exist_ok=True)
        self._load_crash_log()

    def record_crash(self, error: str, stack_trace: str = "") -> CrashRecord:
        """
        Record a crash for diagnosis.

        Returns the CrashRecord and updates the backoff state.
        """
        import uuid
        crash_id = f"crash_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        record = CrashRecord(crash_id, now, error, stack_trace)

        # Update crash window
        current_time = time.monotonic()
        if current_time - self._crash_window_start > self._crash_window_seconds:
            # Reset window
            self._crash_window_start = current_time
            self._crash_count = 0

        self._crash_count += 1
        self._crash_log.append(record)
        self._persist_crash(record)

        # Check if permanent stop needed
        if self._crash_count >= self._crash_window_max:
            self._permanent_stop = True
            log.critical(
                "Permanent stop: %d crashes in %d seconds",
                self._crash_count, self._crash_window_seconds,
            )
            record.recovery_action = RecoveryAction.FULL_RESET
        else:
            record.recovery_action = self._determine_recovery_action(error)

        return record

    def should_restart(self) -> bool:
        """Determine whether to attempt a restart."""
        if self._permanent_stop:
            return False
        return True

    def get_backoff_delay(self) -> float:
        """Get the backoff delay before next restart attempt."""
        delay = min(self._backoff_base * (2 ** (self._crash_count - 1)), self._backoff_max)
        return delay

    def recover_in_flight_tasks(self) -> dict[str, Any]:
        """
        Recover tasks that were in-flight when the crash occurred.

        Scans the task store for tasks in non-terminal states and attempts
        to restore them to a recoverable state.
        """
        recovered = []
        failed = []
        try:
            from nous_runtime.task.manager import TaskManager
            manager = TaskManager()
            all_tasks = manager.list()

            active_states = {"RUNNING", "ANALYZING", "PLANNING", "PREPARING",
                            "VERIFYING", "PAUSED", "WAITING_FOR_RESOURCE",
                            "WAITING_FOR_INPUT", "RECOVERING"}

            for task in all_tasks:
                task_status = task.status.value if hasattr(task.status, 'value') else str(task.status)
                if task_status in active_states:
                    try:
                        # Transition to RECOVERING so the user knows
                        manager.transition(task.id, "RECOVERING")
                        recovered.append({
                            "task_id": task.id,
                            "title": task.name,
                            "previous_status": task_status,
                        })
                    except Exception:
                        failed.append({
                            "task_id": task.id,
                            "error": "Failed to transition to RECOVERING",
                        })

            log.info("Recovered %d tasks, %d failed to recover", len(recovered), len(failed))
        except ImportError:
            log.warning("Task manager not available for recovery")

        return {
            "recovered": len(recovered),
            "failed": len(failed),
            "recovered_tasks": recovered,
            "failed_tasks": failed,
        }

    def recover_events(self, since_sequence: int = 0) -> dict[str, Any]:
        """
        Recover events for WebSocket backfill.

        Returns events since the given sequence number so clients
        can catch up after a disconnect.
        """
        try:
            from nous_runtime.control_plane.websocket import WebSocketEventBridge
            bridge = WebSocketEventBridge.get()
            backfill = bridge.get_backfill(since_sequence)
            return {
                "ok": True,
                "events": len(backfill),
                "since_sequence": since_sequence,
                "latest_sequence": backfill[-1]["sequence"] if backfill else since_sequence,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def safe_mode_boot(self) -> dict[str, Any]:
        """
        Boot in safe mode: minimal functionality, diagnostic output.

        Safe mode disables:
        - Auto-recovery of in-flight tasks
        - Provider auto-connection
        - WebSocket event bridge
        - Background daemon features

        Safe mode enables:
        - Inspector and diagnostics
        - Log viewer
        - Configuration repair
        - Database repair
        """
        os.environ["NOUS_SAFE_MODE"] = "1"
        os.environ["NOUS_DEMO_MODE"] = "1"

        diagnostics = self._run_diagnostics()

        return {
            "mode": "safe",
            "message": "Running in safe mode — limited functionality",
            "diagnostics": diagnostics,
            "available_actions": [
                "inspect snapshot",
                "view logs",
                "validate config",
                "repair database",
                "reset workspace",
            ],
        }

    def diagnose_corruption(self) -> dict[str, Any]:
        """Diagnose potential data corruption."""
        issues = []

        # Check database
        try:
            from nous_runtime.compat.db import get_db
            db = get_db()
            result = db.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                issues.append({"component": "database", "severity": "critical",
                              "message": f"Database integrity check failed: {result[0]}"})
        except Exception as e:
            issues.append({"component": "database", "severity": "error",
                          "message": f"Cannot access database: {e}"})

        # Check workspace
        try:
            from nous_runtime.kernel.config import get_config
            config = get_config()
            data_dir = config.data_dir or ""
            if data_dir and not os.path.isdir(data_dir):
                issues.append({"component": "workspace", "severity": "error",
                              "message": f"Data directory missing: {data_dir}"})
        except Exception as e:
            issues.append({"component": "workspace", "severity": "error",
                          "message": f"Config error: {e}"})

        severity = "ok"
        if any(i["severity"] == "critical" for i in issues):
            severity = "critical"
        elif any(i["severity"] == "error" for i in issues):
            severity = "error"
        elif issues:
            severity = "warning"

        return {"severity": severity, "issues": issues, "safe_mode_recommended": severity in ("critical", "error")}

    # Internal

    def _determine_recovery_action(self, error: str) -> RecoveryAction:
        """Determine the appropriate recovery action based on error type."""
        error_lower = error.lower()
        if "database" in error_lower or "sqlite" in error_lower or "corrupt" in error_lower:
            return RecoveryAction.REBUILD_INDEX
        if "task" in error_lower or "state" in error_lower:
            return RecoveryAction.RESTORE_TASKS
        if "event" in error_lower or "bus" in error_lower:
            return RecoveryAction.RESTORE_EVENTS
        return RecoveryAction.REINITIALIZE

    def _run_diagnostics(self) -> list[dict[str, Any]]:
        """Run system diagnostics."""
        findings = []
        # Check Python version
        import sys
        if sys.version_info < (3, 10):
            findings.append({"code": "PYTHON_VERSION", "severity": "critical",
                           "message": f"Python {sys.version} < 3.10 required"})

        # Check required imports
        required_modules = ["nous_runtime.runtime.lifecycle", "nous_runtime.api.routes"]
        for mod in required_modules:
            try:
                __import__(mod)
            except ImportError as e:
                findings.append({"code": "IMPORT_ERROR", "severity": "critical",
                               "message": f"Cannot import {mod}: {e}"})

        return findings

    def _load_crash_log(self):
        """Load crash log from disk."""
        if not self._crash_log_path or not os.path.exists(self._crash_log_path):
            return
        try:
            with open(self._crash_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            record = CrashRecord(
                                data.get("crash_id", ""),
                                data.get("timestamp", ""),
                                data.get("error", ""),
                                data.get("stack_trace", ""),
                            )
                            record.recovery_action = RecoveryAction(data.get("recovery_action", "NONE"))
                            record.recovery_success = data.get("recovery_success", False)
                            self._crash_log.append(record)
                        except (json.JSONDecodeError, ValueError):
                            pass
        except OSError:
            pass

    def _persist_crash(self, record: CrashRecord):
        """Append a crash record to the crash log file."""
        if not self._crash_log_path:
            return
        try:
            with open(self._crash_log_path, "a") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass
