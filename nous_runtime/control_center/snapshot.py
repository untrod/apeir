"""Server-authoritative, read-only Runtime dashboard snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RuntimeDashboard:
    """Compose bounded views without owning or mutating Runtime state."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        status_loader=None,
        health_loader=None,
        inspector_loader=None,
        metrics_loader=None,
        event_metrics_loader=None,
    ) -> None:
        self.root = str(Path(root).resolve())
        self._status_loader = status_loader
        self._health_loader = health_loader
        self._inspector_loader = inspector_loader
        self._metrics_loader = metrics_loader
        self._event_metrics_loader = event_metrics_loader

    def snapshot(self) -> dict[str, Any]:
        status = self._load_status()
        health = self._load_health()
        inspector = self._load_inspector()
        runtime_metrics = self._load_metrics()
        event_metrics = self._load_event_metrics()
        tasks = list(inspector.get("tasks") or ())[:50]
        observations = list(inspector.get("observations") or ())[-50:]
        devices = list(inspector.get("devices") or ())[:50]
        findings = list(inspector.get("findings") or ())[:50]
        runtime_errors = list((inspector.get("runtime") or {}).get("errors") or ())[:20]
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "server_authoritative": True,
            "runtime": status,
            "health": health,
            "metrics": {"runtime": runtime_metrics, "events": event_metrics},
            "missions": tasks,
            "timeline": observations,
            "decisions": [],
            "nodes": [
                {
                    "node_id": item.get("device_id", ""),
                    "name": item.get("name", ""),
                    "type": item.get("device_type", "unknown"),
                    "online": bool(item.get("online", False)),
                    "capabilities": list(item.get("capabilities") or ()),
                    "last_seen": item.get("last_seen", ""),
                }
                for item in devices
            ],
            "alerts": findings + [
                {"severity": "error", "component": "runtime", "message": str(error)}
                for error in runtime_errors
            ],
            "controls": {
                "execution_endpoint": "/api/runtime/run",
                "chat_endpoint": "/api/chat",
                "authenticated": True,
                "governed": True,
                "client_state_authoritative": False,
            },
            "limits": {"missions": 50, "timeline": 50, "nodes": 50, "alerts": 70},
        }

    def _load_status(self) -> dict[str, Any]:
        if self._status_loader is None:
            from nous_runtime.api.routes import handle_status

            self._status_loader = handle_status
        return self._safe_mapping(self._status_loader)

    def _load_health(self) -> dict[str, Any]:
        if self._health_loader is None:
            from nous_runtime.api.routes import handle_health

            self._health_loader = handle_health
        return self._safe_mapping(self._health_loader)

    def _load_inspector(self) -> dict[str, Any]:
        if self._inspector_loader is None:
            from nous_runtime.inspector import snapshot

            self._inspector_loader = snapshot
        value = self._safe_value(self._inspector_loader, {})
        return value.to_dict() if hasattr(value, "to_dict") else dict(value or {})

    def _load_metrics(self) -> dict[str, Any]:
        if self._metrics_loader is None:
            from nous_runtime.monitoring.metrics import MetricsCollector

            self._metrics_loader = lambda: MetricsCollector(self.root).snapshot()
        return self._safe_mapping(self._metrics_loader)

    def _load_event_metrics(self) -> dict[str, Any]:
        if self._event_metrics_loader is None:
            from nous_runtime.events.stream import EventStream

            self._event_metrics_loader = lambda: EventStream(self.root).get_stats()
        return self._safe_mapping(self._event_metrics_loader)

    @classmethod
    def _safe_mapping(cls, loader) -> dict[str, Any]:
        return dict(cls._safe_value(loader, {}) or {})

    @staticmethod
    def _safe_value(loader, fallback):
        try:
            return loader()
        except Exception as exc:
            return {"ok": False, "error": str(exc)} if isinstance(fallback, dict) else fallback


def control_center_snapshot(root: str | Path = ".") -> dict[str, Any]:
    return RuntimeDashboard(root).snapshot()
