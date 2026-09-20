# -*- coding: utf-8 -*-
"""
Control Plane Lifecycle — sidecar process management integration points.

The Control Plane exposes lifecycle hooks that the Tauri sidecar manager
calls to coordinate startup, health checking, and shutdown. These hooks
integrate with the existing DaemonService and Runtime infrastructure.

Lifecycle contract:
1. Tauri starts → launches Python sidecar → ControlPlaneLifecycle.start()
2. Health check → GET /api/v1/health → ControlPlaneLifecycle.health()
3. Tauri closing → ControlPlaneLifecycle.shutdown() → graceful stop
4. Crash detected → ControlPlaneLifecycle.recover() → restart decision
"""

from __future__ import annotations

import logging
import os
import threading
import time
from enum import Enum
from typing import Any, Callable

log = logging.getLogger("nous.control_plane.lifecycle")


class LifecycleState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    CRASHED = "CRASHED"
    RECOVERING = "RECOVERING"


class ControlPlaneLifecycle:
    """
    Manages the lifecycle of the Control Plane within the sidecar process.

    Coordinates:
    - Runtime startup
    - Health monitoring
    - Graceful shutdown (with in-flight task check)
    - Crash detection and recovery
    - Port allocation
    - Session token rotation
    """

    _instance: ControlPlaneLifecycle | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._state = LifecycleState.STOPPED
        self._port: int = 0
        self._host: str = "127.0.0.1"
        self._start_time: float = 0.0
        self._on_state_change: list[Callable[[LifecycleState, LifecycleState], None]] = []
        self._shutdown_timeout: float = 30.0  # seconds to wait for in-flight tasks
        self._health_check_interval: float = 5.0
        self._health_thread: threading.Thread | None = None
        self._runtime: Any = None

    @classmethod
    def get(cls) -> ControlPlaneLifecycle:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def uptime_seconds(self) -> float:
        if self._start_time == 0:
            return 0.0
        return time.monotonic() - self._start_time

    # State transitions

    def _transition(self, target: LifecycleState):
        old = self._state
        self._state = target
        log.info("Control Plane lifecycle: %s → %s", old, target)
        for callback in self._on_state_change:
            try:
                callback(old, target)
            except Exception:
                pass

    def on_state_change(self, callback: Callable[[LifecycleState, LifecycleState], None]):
        """Register a callback for state transitions."""
        self._on_state_change.append(callback)

    # Lifecycle operations

    def start(self, port: int = 0, host: str = "127.0.0.1") -> dict[str, Any]:
        """
        Start the Control Plane.

        Args:
            port: Port to bind. 0 = random available port.
            host: Bind address. Default 127.0.0.1.

        Returns:
            Startup result with port, token, and health status.
        """
        if self._state == LifecycleState.RUNNING:
            return {"ok": True, "state": self._state, "port": self._port, "message": "Already running"}

        self._transition(LifecycleState.STARTING)
        self._host = host

        try:
            # Allocate port
            self._port = port or self._find_free_port()
            os.environ["NOUS_SERVER_PORT"] = str(self._port)
            os.environ["NOUS_SERVER_HOST"] = host

            # Generate session token
            from nous_runtime.control_plane.auth import ControlPlaneAuth
            auth = ControlPlaneAuth.get()
            auth.generate()

            # Start runtime
            from nous_runtime.runtime.lifecycle import Runtime
            self._runtime = Runtime()
            self._runtime.start()

            # Start the HTTP server
            from nous_runtime.api.server import start_server
            start_server(host=self._host, port=self._port)

            # Start WebSocket event bridge
            from nous_runtime.control_plane.websocket import WebSocketEventBridge
            WebSocketEventBridge.get().start()

            # Start health monitoring
            self._start_health_monitor()

            self._start_time = time.monotonic()
            self._transition(LifecycleState.RUNNING)

            log.info("Control Plane started on %s:%s", host, self._port)
            return {
                "ok": True,
                "state": self._state,
                "port": self._port,
                "host": self._host,
                "base_url": self.base_url,
                "token_file": auth.token_file,
                "health": self.health(),
            }
        except Exception as e:
            log.exception("Control Plane start failed")
            self._transition(LifecycleState.CRASHED)
            return {"ok": False, "state": self._state, "error": str(e)}

    def shutdown(self, force: bool = False) -> dict[str, Any]:
        """
        Gracefully shut down the Control Plane.

        Args:
            force: If True, skip in-flight task check and force shutdown.

        Returns:
            Shutdown result.
        """
        if self._state == LifecycleState.STOPPED:
            return {"ok": True, "message": "Already stopped"}

        self._transition(LifecycleState.STOPPING)

        # Check for in-flight tasks
        if not force:
            active_tasks = self._count_active_tasks()
            if active_tasks > 0:
                log.warning("Shutdown requested with %d active tasks", active_tasks)
                return {
                    "ok": False,
                    "error": "TASKS_IN_FLIGHT",
                    "message": f"{active_tasks} task(s) still running",
                    "active_tasks": active_tasks,
                    "advice": "Wait for tasks to complete, or use force=True",
                }

        try:
            # Stop health monitor
            self._stop_health_monitor()

            # Stop WebSocket bridge
            from nous_runtime.control_plane.websocket import WebSocketEventBridge
            WebSocketEventBridge.get().stop()

            # Graceful shutdown of runtime
            if self._runtime:
                self._runtime.stop()

            # Revoke session token
            from nous_runtime.control_plane.auth import ControlPlaneAuth
            ControlPlaneAuth.get().revoke()

            self._port = 0
            self._start_time = 0.0
            self._transition(LifecycleState.STOPPED)
            log.info("Control Plane shut down")

            return {"ok": True, "message": "Control Plane stopped"}
        except Exception as e:
            log.exception("Control Plane shutdown error")
            self._transition(LifecycleState.CRASHED)
            return {"ok": False, "error": str(e)}

    def health(self) -> dict[str, Any]:
        """Get current health status of the Control Plane."""
        checks = {}

        # Runtime health
        try:
            from nous_runtime.runtime.lifecycle import Runtime
            s = Runtime().status()
            checks["runtime"] = "ok" if s.running else "down"
        except Exception as e:
            checks["runtime"] = f"error: {e}"

        # Database health
        try:
            from nous_runtime.compat.db import get_db
            db = get_db()
            db.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"

        # Provider health
        try:
            from nous_runtime.provider.registry import ProviderRegistry
            health = ProviderRegistry().health_all()
            checks["providers"] = health.get("status", "unknown")
        except Exception as e:
            checks["providers"] = f"error: {e}"

        # Workspace health
        try:
            from nous_runtime.kernel.config import get_config
            config = get_config()
            data_dir = config.data_dir or ""
            if data_dir and os.path.isdir(data_dir):
                checks["workspace"] = "ok"
            else:
                checks["workspace"] = "degraded"
        except Exception:
            checks["workspace"] = "degraded"

        overall = "ok"
        if any(v != "ok" for v in checks.values()):
            if any("error" in str(v) for v in checks.values()):
                overall = "down"
            else:
                overall = "degraded"

        return {
            "status": overall,
            "runtime": checks.get("runtime", "unknown"),
            "database": checks.get("database", "unknown"),
            "providers": checks.get("providers", "unknown"),
            "workspace": checks.get("workspace", "unknown"),
            "system": {
                "uptime_seconds": self.uptime_seconds,
                "state": self._state,
                "port": self._port,
            },
            "checks": checks,
        }

    def recover(self) -> dict[str, Any]:
        """Attempt recovery after a crash."""
        self._transition(LifecycleState.RECOVERING)
        try:
            # Attempt runtime reinitialization
            if self._runtime:
                try:
                    self._runtime.stop()
                except Exception:
                    pass

            from nous_runtime.runtime.lifecycle import Runtime
            self._runtime = Runtime()
            self._runtime.start()

            self._transition(LifecycleState.RUNNING)
            log.info("Control Plane recovered successfully")
            return {"ok": True, "state": self._state, "message": "Recovered"}
        except Exception as e:
            log.exception("Control Plane recovery failed")
            self._transition(LifecycleState.CRASHED)
            return {"ok": False, "state": self._state, "error": str(e)}

    # Internal

    def _find_free_port(self) -> int:
        """Find a random free port on loopback."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _count_active_tasks(self) -> int:
        """Count currently running tasks."""
        try:
            from nous_runtime.task.manager import TaskManager
            tasks = TaskManager().list()
            active_states = {"RUNNING", "ANALYZING", "PLANNING", "PREPARING", "VERIFYING", "RECOVERING"}
            return sum(1 for t in tasks if t.status.value in active_states)
        except Exception:
            return 0

    def _start_health_monitor(self):
        """Start background health monitoring."""
        if self._health_thread and self._health_thread.is_alive():
            return

        def _monitor():
            while self._state in (LifecycleState.RUNNING, LifecycleState.DEGRADED):
                time.sleep(self._health_check_interval)
                try:
                    h = self.health()
                    if h["status"] == "down":
                        self._transition(LifecycleState.DEGRADED)
                    elif h["status"] == "ok" and self._state == LifecycleState.DEGRADED:
                        self._transition(LifecycleState.RUNNING)
                except Exception:
                    pass

        self._health_thread = threading.Thread(target=_monitor, daemon=True)
        self._health_thread.start()

    def _stop_health_monitor(self):
        """Stop the health monitor thread."""
        self._health_thread = None
