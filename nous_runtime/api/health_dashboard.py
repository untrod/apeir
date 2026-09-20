# -*- coding: utf-8 -*-
"""Health Dashboard API — aggregated system health for the desktop UI."""

from __future__ import annotations

import logging
import os
import platform
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.api.health_dashboard")


def ok(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _workspace() -> str:
    return os.environ.get("NOUS_WORKSPACE_ROOT", str(Path.home() / ".nous"))


def handle_health_dashboard() -> dict[str, Any]:
    """Aggregated health status for all subsystems."""
    try:
        components = {}

        # Runtime health
        try:
            import nous_runtime
            from nous_runtime.api.kernel_status import kernel_status
            kernel = kernel_status()
            components["runtime"] = {
                "healthy": True,
                "version": nous_runtime.__version__,
                "uptime": "unknown",
            }
            components["kernel"] = {"healthy": kernel["ready"], **kernel}
        except Exception as e:
            components["runtime"] = {"healthy": False, "error": str(e)}

        # Database health
        try:
            from nous_runtime.services.database import get_connection
            conn = get_connection()
            conn.execute("SELECT 1")
            components["database"] = {"healthy": True}
        except Exception as e:
            components["database"] = {"healthy": False, "error": str(e)}

        # Provider health
        try:
            from nous_runtime.services.providers import provider_health_summary
            ph = provider_health_summary()
            components["providers"] = {
                "healthy": ph.get("healthy_count", 0) > 0,
                "total": ph.get("total_count", 0),
                "healthy_count": ph.get("healthy_count", 0),
                "unhealthy_count": ph.get("unhealthy_count", 0),
            }
        except Exception as e:
            components["providers"] = {"healthy": False, "error": str(e)}

        # Task health
        try:
            from nous_runtime.api.desktop_routes import handle_tasks_list
            td = handle_tasks_list()
            if td.get("ok"):
                components["tasks"] = {
                    "healthy": True,
                    "total": td["data"]["total"],
                    "running": td["data"]["running"],
                }
            else:
                components["tasks"] = {"healthy": False, "error": td.get("error", {}).get("message", "")}
        except Exception as e:
            components["tasks"] = {"healthy": False, "error": str(e)}

        # Workspace health
        try:
            ws = Path(_workspace())
            ws.mkdir(parents=True, exist_ok=True)
            test_file = ws / ".health"
            test_file.write_text("ok")
            test_file.unlink()
            components["workspace"] = {"healthy": True, "path": str(ws)}
        except Exception as e:
            components["workspace"] = {"healthy": False, "error": str(e)}

        # System resources
        try:
            import psutil
            vm = psutil.virtual_memory()
            disk = psutil.disk_usage(_workspace())
            components["system"] = {
                "healthy": vm.percent < 95 and disk.percent < 95,
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": vm.percent,
                "disk_percent": disk.percent,
                "platform": platform.platform(),
            }
        except ImportError:
            components["system"] = {
                "healthy": True,
                "platform": platform.platform(),
                "note": "psutil not installed — limited metrics",
            }

        # Overall
        all_healthy = all(
            c.get("healthy", False)
            for c in components.values()
        )

        return ok({
            "overall": "healthy" if all_healthy else "degraded",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "components": components,
        })
    except Exception as e:
        return {"ok": False, "error": {"code": "HEALTH_DASHBOARD_ERROR", "message": str(e)}}


def handle_service_status() -> dict[str, Any]:
    """Return daemon service status."""
    try:
        from nous_runtime.daemon.service import DaemonService
        svc = DaemonService()
        return ok(svc.status())
    except Exception as e:
        return {"ok": False, "error": {"code": "SERVICE_STATUS_ERROR", "message": str(e)}}


HEALTH_DASHBOARD_ROUTES = {
    ("GET", "/api/v1/health/dashboard"): handle_health_dashboard,
    ("GET", "/api/v1/service/status"): handle_service_status,
}


def register_health_dashboard_routes(routes_dict: dict) -> None:
    routes_dict.update(HEALTH_DASHBOARD_ROUTES)


__all__ = [
    "HEALTH_DASHBOARD_ROUTES",
    "register_health_dashboard_routes",
]
