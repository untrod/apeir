# -*- coding: utf-8 -*-
"""Health check and metrics collection for the Nous daemon."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

_log = logging.getLogger("nous.daemon.health")


@dataclass
class HealthStatus:
    healthy: bool = True
    components: dict[str, bool] = field(default_factory=dict)
    last_check: str = ""
    uptime_seconds: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "components": self.components,
            "last_check": self.last_check,
            "uptime_seconds": self.uptime_seconds,
            "metrics": self.metrics,
            "errors": self.errors[-10:],
        }


class HealthChecker:
    """Periodic health checker with component-level monitoring."""

    def __init__(self, interval_seconds: float = 30.0):
        self._interval = interval_seconds
        self._started_at = time.monotonic()
        self._checks: dict[str, Callable[[], bool]] = {}
        self._metric_collectors: dict[str, Callable[[], Any]] = {}
        self._last_status = HealthStatus()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def status(self) -> HealthStatus:
        with self._lock:
            return self._last_status

    def register_check(self, name: str, check_fn: Callable[[], bool]) -> None:
        """Register a named health check function."""
        self._checks[name] = check_fn

    def register_metric(self, name: str, collector: Callable[[], Any]) -> None:
        """Register a metric collector function."""
        self._metric_collectors[name] = collector

    def run_once(self) -> HealthStatus:
        """Execute all health checks and return status."""
        status = HealthStatus()
        status.last_check = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        status.uptime_seconds = time.monotonic() - self._started_at

        all_healthy = True
        errors: list[str] = []

        for name, check in self._checks.items():
            try:
                ok = check()
                status.components[name] = ok
                if not ok:
                    all_healthy = False
                    errors.append(f"Component '{name}' check failed")
            except Exception as exc:
                status.components[name] = False
                all_healthy = False
                errors.append(f"Component '{name}' error: {exc}")

        metrics: dict[str, Any] = {}
        for name, collector in self._metric_collectors.items():
            try:
                metrics[name] = collector()
            except Exception as exc:
                metrics[name] = f"collection_error: {exc}"

        status.healthy = all_healthy
        status.errors = errors
        status.metrics = metrics

        with self._lock:
            self._last_status = status

        return status

    def start(self) -> None:
        """Start periodic health checking in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        _log.info("Health checker started (interval=%ss)", self._interval)

    def stop(self) -> None:
        """Stop the health checker thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        _log.info("Health checker stopped")

    def _loop(self) -> None:
        while self._running:
            self.run_once()
            time.sleep(self._interval)


# Built-in checks

def create_default_checks(workspace: str = "") -> HealthChecker:
    """Create a HealthChecker with sensible defaults."""
    from pathlib import Path

    checker = HealthChecker(interval_seconds=30.0)
    ws = Path(workspace) if workspace else Path.home() / ".nous"

    # Check 1: Runtime can be imported
    def check_runtime_import() -> bool:
        try:
            from nous_runtime.runtime.lifecycle import Runtime  # noqa: F401
            return True
        except Exception:
            return False

    # Check 2: Workspace is accessible
    def check_workspace() -> bool:
        try:
            ws.mkdir(parents=True, exist_ok=True)
            test_file = ws / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False

    # Check 3: Database is accessible
    def check_database() -> bool:
        try:
            from nous_runtime.services.database import get_connection
            conn = get_connection()
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    # Metric: workspace size
    def collect_workspace_size() -> dict:
        try:
            total = sum(
                f.stat().st_size
                for f in ws.rglob("*")
                if f.is_file()
            )
            return {"size_mb": round(total / (1024 * 1024), 1)}
        except Exception:
            return {"size_mb": 0}

    # Metric: provider count
    def collect_provider_count() -> dict:
        try:
            from nous_runtime.provider.registry import ProviderRegistry
            providers = ProviderRegistry().list_all()
            return {"count": len(providers), "healthy": sum(1 for p in providers if p.get("health") == "healthy")}
        except Exception:
            return {"count": 0, "healthy": 0}

    checker.register_check("runtime_import", check_runtime_import)
    checker.register_check("workspace", check_workspace)
    checker.register_check("database", check_database)

    checker.register_metric("workspace_size", collect_workspace_size)
    checker.register_metric("provider_count", collect_provider_count)

    return checker


__all__ = ["HealthStatus", "HealthChecker", "create_default_checks"]
