# -*- coding: utf-8 -*-
"""Desktop-specific API routes that bridge UI surfaces to Runtime primitives.

These are thin adapters — no state ownership, no duplicate stores.
All data comes from existing Runtime components.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.api.desktop")


def ok(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def err(code: str, message: str, details: dict | None = None) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}


def _workspace() -> str:
    return os.environ.get("NOUS_WORKSPACE_ROOT", str(Path.home() / ".nous"))


# Tasks

_WORK_TASK_STATES = {
    "RECEIVED": "planning",
    "UNDERSTANDING": "planning",
    "PREPARING": "planning",
    "PLANNING": "planning",
    "EXECUTING": "running",
    "OBSERVING": "running",
    "REPLANNING": "planning",
    "RUNNING": "running",
    "VERIFYING": "verifying",
    "WAITING_FOR_NODE": "waiting_for_node",
    "WAITING_FOR_APPROVAL": "awaiting_approval",
    "WAITING_USER": "waiting_user",
    "PAUSED": "paused",
    "BLOCKED": "blocked",
    "RECOVERING": "recovering",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}


def _work_task_projection(snapshot: Any) -> dict[str, Any]:
    """Project durable Work facts into the existing Desktop Task contract."""
    state = str(getattr(snapshot.state, "value", snapshot.state))
    plan = snapshot.plan
    plan_tasks = list(getattr(plan, "tasks", ()) or ())
    completed = sum(
        str(getattr(item.status, "value", item.status)) in {"completed", "skipped"}
        for item in plan_tasks
    )
    progress = round((completed / len(plan_tasks)) * 100) if plan_tasks else 0
    if state == "COMPLETED":
        progress = 100
    result = snapshot.result
    result_summary = result if isinstance(result, str) else ""
    if result is not None and not result_summary:
        result_summary = "Durable Work result recorded"
    return {
        "id": snapshot.run_id,
        "task_id": snapshot.run_id,
        "run_id": snapshot.run_id,
        "task_kind": "work",
        "conversation_id": snapshot.conversation_id,
        "name": snapshot.goal.objective,
        "status": _WORK_TASK_STATES.get(state, state.casefold()),
        "priority": "normal",
        "model_id": "auto",
        "plan_id": getattr(plan, "plan_id", "") if plan else "",
        "trace_id": snapshot.run_id,
        "steps": [
            {
                "step_id": item.task_id,
                "name": item.description,
                "status": str(getattr(item.status, "value", item.status)),
                "started_at": item.started_at or None,
                "completed_at": item.completed_at or None,
                "error": item.error or None,
                "retry_count": item.retry_count,
                "max_retries": item.max_retries,
            }
            for item in plan_tasks
        ],
        "progress_pct": progress,
        "current_step": snapshot.current_step,
        "plan_revision": getattr(plan, "revision", 0) if plan else 0,
        "artifact_refs": list(snapshot.artifacts),
        "cancellation_requested": state == "CANCELLED",
        "recoverable": not snapshot.terminal,
        "error": snapshot.error or None,
        "result_summary": result_summary or None,
        "schema_version": "1.0.0",
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }

def handle_tasks_list(state: str = "", limit: int = 50) -> dict[str, Any]:
    """List tasks from the Execution Runtime and connectivity layers."""
    try:
        from nous_runtime.task.cli import get_task_manager
        from nous_runtime.task.exceptions import TaskRuntimeError

        manager = get_task_manager()
        try:
            runtime_tasks = manager.list(state or None)
        except TaskRuntimeError:
            runtime_tasks = []

        task_list = []
        for t in runtime_tasks[-limit:]:
            task_list.append({
                "task_id": getattr(t, "task_id", str(t)),
                "name": getattr(t, "name", ""),
                "status": getattr(t, "status", getattr(t, "state", "unknown")),
                "priority": getattr(t, "priority", "NORMAL"),
                "model_id": getattr(t, "model_id", ""),
                "duration": getattr(t, "duration_ms", None),
                "created_at": getattr(t, "created_at", ""),
            })

        # Work checkpoints remain the authority; this is only a Desktop view.
        try:
            from nous_runtime.work import WorkHarness
            checkpoint_path = Path(_workspace()) / ".nous" / "checkpoints.db"
            if checkpoint_path.is_file():
                task_list.extend(
                    _work_task_projection(snapshot)
                    for snapshot in WorkHarness(_workspace()).list()
                )
        except Exception:
            _log.exception("Could not project durable Work runs into Task Center")

        # Also include connectivity tasks if available
        try:
            from nous_runtime.connectivity.project.store import ProjectStore
            store = ProjectStore()
            # Collect tasks from projects
            for project in store.list_projects()[:5]:
                for wi in store.list_work_items(project.get("project_id", "")):
                    task_list.append({
                        "task_id": wi.get("work_item_id", ""),
                        "name": wi.get("description", ""),
                        "status": wi.get("status", "unknown"),
                        "priority": "NORMAL",
                        "model_id": "",
                        "duration": None,
                        "created_at": wi.get("created_at", ""),
                    })
        except Exception:
            pass

        if state and task_list:
            task_list = [
                task for task in task_list
                if str(task.get("status") or "").casefold() == state.casefold()
            ]
        task_list.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        task_list = task_list[:max(1, min(int(limit), 200))]

        return ok({
            "tasks": task_list,
            "total": len(task_list),
            "running": sum(
                1 for task in task_list
                if str(task.get("status") or "").casefold()
                in {"planning", "running", "recovering", "verifying"}
            ),
        })
    except Exception as e:
        return err("TASKS_LIST_ERROR", str(e))


def handle_tasks_action(body: dict[str, Any]) -> dict[str, Any]:
    """Perform an action on a task."""
    try:
        action = str(body.get("action", "")).lower()
        task_id = str(body.get("task_id", ""))

        if not task_id or not action:
            return err("NOUS_INVALID_REQUEST", "task_id and action are required")

        try:
            from nous_runtime.work import WorkHarness
            checkpoint_path = Path(_workspace()) / ".nous" / "checkpoints.db"
            if not checkpoint_path.is_file():
                raise KeyError(task_id)
            work = WorkHarness(_workspace())
            work.require(task_id)
            if action == "cancel":
                snapshot = work.cancel(task_id, reason="cancelled from Desktop")
            elif action == "pause":
                snapshot = work.pause(task_id, reason="paused from Desktop")
            else:
                return err("NOUS_INVALID_REQUEST", f"Unsupported Work action: {action}")
            return ok({"work": snapshot.to_dict()})
        except KeyError:
            pass

        if action == "cancel":
            from nous_runtime.task.cli import get_task_manager
            manager = get_task_manager()
            result = manager.cancel(task_id)
            return ok({"cancelled": task_id, "result": result})
        elif action == "retry":
            from nous_runtime.task.cli import get_task_manager
            manager = get_task_manager()
            result = manager.retry(task_id)
            return ok({"retried": task_id, "result": result})
        else:
            return err("NOUS_INVALID_REQUEST", f"Unsupported task action: {action}")
    except Exception as e:
        return err("TASKS_ACTION_ERROR", str(e))


# Devices

def handle_devices_list() -> dict[str, Any]:
    """List known devices from the connectivity layer."""
    devices = []
    try:
        # Try connected nodes
        try:
            from nous_runtime.connectivity.cli.commands import _list_nodes
            nodes = _list_nodes() if callable(_list_nodes) else []
            for n in nodes if isinstance(nodes, list) else []:
                devices.append({
                    "device_id": n.get("node_id", ""),
                    "name": n.get("name", "Unknown"),
                    "type": n.get("type", "node"),
                    "status": n.get("status", "unknown"),
                    "address": n.get("address", ""),
                    "capabilities": n.get("capabilities", []),
                })
        except Exception:
            pass

        # Add local machine
        try:
            local = {
                "device_id": "local",
                "name": platform.node() or "This Computer",
                "type": "pc",
                "status": "online",
                "hardware": f"{platform.processor() or 'Unknown'}",
                "address": "localhost",
                "capabilities": ["runtime", "desktop"],
            }
            devices.insert(0, local)
        except Exception:
            devices.insert(0, {
                "device_id": "local",
                "name": "This Computer",
                "type": "pc",
                "status": "online",
                "hardware": platform.platform(),
                "address": "localhost",
                "capabilities": ["runtime", "desktop"],
            })

        return ok({
            "devices": devices,
            "total": len(devices),
            "online": sum(1 for d in devices if d["status"] == "online"),
        })
    except Exception as e:
        return err("DEVICES_LIST_ERROR", str(e))


def handle_devices_scan() -> dict[str, Any]:
    """Scan local network for devices."""
    try:
        from nous_runtime.connectivity.control_plane.pairing_service import (
            discover_devices,
        )
        discovered = discover_devices() if callable(discover_devices) else []
        return ok({
            "discovered": list(discovered) if discovered else [],
            "timestamp": time.time(),
        })
    except Exception:
        # Fallback: return local device only
        return ok({
            "discovered": [{
                "device_id": "local",
                "name": "This Computer",
                "status": "online",
                "type": "pc",
            }],
            "timestamp": time.time(),
        })


# Automations

def _automation_store():
    """Get or create automations store."""
    store_path = Path(_workspace()) / "automations.json"
    import json
    if store_path.is_file():
        return json.loads(store_path.read_text(encoding="utf-8"))
    return {"automations": []}


def _save_automation_store(data: dict) -> None:
    import json
    store_path = Path(_workspace()) / "automations.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def handle_automations_list() -> dict[str, Any]:
    """List configured automations."""
    try:
        store = _automation_store()
        return ok({
            "automations": store.get("automations", []),
            "total": len(store.get("automations", [])),
        })
    except Exception as e:
        return err("AUTOMATIONS_LIST_ERROR", str(e))


def handle_automations_add(body: dict[str, Any]) -> dict[str, Any]:
    """Add a new automation rule."""
    try:
        import uuid
        store = _automation_store()
        new_auto = {
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "name": str(body.get("name", "Untitled")),
            "trigger": str(body.get("trigger", "schedule")),
            "schedule": body.get("schedule", ""),
            "action": str(body.get("action", "")),
            "enabled": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        store.setdefault("automations", []).append(new_auto)
        _save_automation_store(store)
        return ok(new_auto)
    except Exception as e:
        return err("AUTOMATIONS_ADD_ERROR", str(e))


def handle_automations_action(body: dict[str, Any]) -> dict[str, Any]:
    """Enable/disable an automation."""
    try:
        action = str(body.get("action", ""))
        automation_id = str(body.get("automation_id", ""))
        store = _automation_store()
        for a in store.get("automations", []):
            if a["id"] == automation_id:
                if action == "enable":
                    a["enabled"] = True
                elif action == "disable":
                    a["enabled"] = False
                _save_automation_store(store)
                return ok(a)
        return err("AUTOMATION_NOT_FOUND", f"Automation {automation_id} not found")
    except Exception as e:
        return err("AUTOMATIONS_ACTION_ERROR", str(e))


# Knowledge

def _knowledge_store():
    store_path = Path(_workspace()) / "knowledge.json"
    import json
    if store_path.is_file():
        return json.loads(store_path.read_text(encoding="utf-8"))
    return {"items": []}


def _save_knowledge_store(data: dict) -> None:
    import json
    store_path = Path(_workspace()) / "knowledge.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def handle_knowledge_list(category: str = "all") -> dict[str, Any]:
    """List knowledge items with optional category filter."""
    try:
        store = _knowledge_store()
        items = store.get("items", [])
        if category and category != "all":
            items = [i for i in items if i.get("category") == category]
        return ok({"items": items, "total": len(items)})
    except Exception as e:
        return err("KNOWLEDGE_LIST_ERROR", str(e))


def handle_knowledge_add(body: dict[str, Any]) -> dict[str, Any]:
    """Add knowledge item."""
    try:
        import uuid
        store = _knowledge_store()
        item = {
            "id": f"kn_{uuid.uuid4().hex[:12]}",
            "title": str(body.get("title", "Untitled")),
            "category": str(body.get("category", "documents")),
            "format": str(body.get("format", "text")),
            "content": str(body.get("content", "")),
            "summary": str(body.get("content", ""))[:200],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        store.setdefault("items", []).append(item)
        _save_knowledge_store(store)
        return ok(item)
    except Exception as e:
        return err("KNOWLEDGE_ADD_ERROR", str(e))


# Security

def handle_security_permissions() -> dict[str, Any]:
    """List permission status from governance layer."""
    try:
        from nous_runtime.governance.permission import PermissionEngine
        engine = PermissionEngine()
        rules = engine.list_rules() if hasattr(engine, "list_rules") else []
        return ok({
            "permissions": [
                {
                    "id": getattr(r, "permission_id", str(r)),
                    "name": getattr(r, "name", str(r)),
                    "description": getattr(r, "description", ""),
                    "granted": getattr(r, "granted", True),
                    "risk": getattr(r, "risk_level", "medium"),
                }
                for r in rules
            ] if rules else _default_permissions(),
        })
    except Exception:
        return ok({"permissions": _default_permissions()})


def _default_permissions() -> list[dict]:
    return [
        {"id": "model_access", "name": "Model Access", "description": "Allow AI models to process your requests", "granted": True, "risk": "low"},
        {"id": "file_access", "name": "File Access", "description": "Allow reading and writing files in workspace", "granted": True, "risk": "medium"},
        {"id": "network_access", "name": "Network Access", "description": "Allow connecting to external services", "granted": True, "risk": "medium"},
        {"id": "code_execution", "name": "Code Execution", "description": "Allow executing generated code", "granted": False, "risk": "high"},
        {"id": "system_commands", "name": "System Commands", "description": "Allow running system shell commands", "granted": False, "risk": "high"},
        {"id": "device_control", "name": "Device Control", "description": "Allow controlling connected devices", "granted": False, "risk": "high"},
    ]


# Logs

def handle_logs_list(level: str = "info", limit: int = 100) -> dict[str, Any]:
    """Return recent log lines from the workspace log file."""
    try:
        log_path = Path(_workspace()) / "nous.log"
        if not log_path.is_file():
            return ok({"lines": [], "level": level})

        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        min_level = levels.index(level.upper()) if level.upper() in levels else 1

        lines = log_path.read_text(encoding="utf-8", errors="replace").split("\n")
        filtered = []
        for line in lines[-limit * 3:]:  # Over-sample then filter
            if not line.strip():
                continue
            line_level = 1  # Default to INFO
            for i, level_name in enumerate(levels):
                if level_name in line.upper():
                    line_level = i
                    break
            if line_level >= min_level:
                filtered.append(line)

        return ok({"lines": filtered[-limit:], "level": level, "total": len(filtered)})
    except Exception as e:
        return err("LOGS_LIST_ERROR", str(e))


# Memory

def handle_memory_usage() -> dict[str, Any]:
    """Report runtime memory usage."""
    try:
        import psutil
        process = psutil.Process()
        mem = process.memory_info()
        vm = psutil.virtual_memory()
        return ok({
            "rss_mb": round(mem.rss / (1024 * 1024), 1),
            "vms_mb": round(mem.vms / (1024 * 1024), 1),
            "used_pct": round(vm.percent, 1),
            "total_gb": round(vm.total / (1024**3), 1),
            "available_gb": round(vm.available / (1024**3), 1),
        })
    except ImportError:
        return ok({"used_pct": 0, "rss_mb": 0, "total_gb": 0, "available_gb": 0})
    except Exception as e:
        return err("MEMORY_ERROR", str(e))


# Dashboard

def handle_dashboard_full() -> dict[str, Any]:
    """Aggregated dashboard data for the desktop home page."""
    try:
        # API liveness and live Rust Kernel status are separate authorities.
        import nous_runtime
        from nous_runtime.api.kernel_status import kernel_status
        kernel = kernel_status()
        from nous_runtime.capability.availability import check_availability
        capability_summary = check_availability()["summary"]

        # Model summary
        try:
            from nous_runtime.model_runtime.center import ModelCenterService
            model_snap = ModelCenterService(_workspace()).snapshot()
        except Exception:
            model_snap = {"summary": {"enabled": 0, "healthy": 0}, "models": []}

        # Task summary
        task_data = handle_tasks_list(limit=5)
        tasks = (task_data.get("data", {}) if task_data.get("ok") else {})

        # Device summary
        dev_data = handle_devices_list()
        devices = (dev_data.get("data", {}) if dev_data.get("ok") else {})

        # Memory
        mem_data = handle_memory_usage()
        memory = (mem_data.get("data", {}) if mem_data.get("ok") else {})

        return ok({
            "runtime": {
                "version": nous_runtime.__version__,
                "running": True,
                "demo_mode": False,
                "kernel": kernel,
            },
            "models": {
                "total": model_snap.get("summary", {}).get("enabled", 0),
                "healthy": model_snap.get("summary", {}).get("healthy", 0),
            },
            "tasks": {
                "total": tasks.get("total", 0),
                "running": tasks.get("running", 0),
            },
            "devices": {
                "total": devices.get("total", 0),
                "online": devices.get("online", 0),
            },
            "memory": memory,
            "providers": model_snap.get("summary", {}).get("providers", 0),
            "capabilities": capability_summary.get("registered", 0),
            "events_total": 0,
            "jobs_pending": 0,
        })
    except Exception as e:
        return err("DASHBOARD_ERROR", str(e))


# Route table

DESKTOP_ROUTES = {
    ("GET", "/api/v1/tasks"): handle_tasks_list,
    ("POST", "/api/v1/tasks/action"): handle_tasks_action,
    ("GET", "/api/v1/devices"): handle_devices_list,
    ("POST", "/api/v1/devices/scan"): handle_devices_scan,
    ("GET", "/api/v1/automations"): handle_automations_list,
    ("POST", "/api/v1/automations/add"): handle_automations_add,
    ("POST", "/api/v1/automations/action"): handle_automations_action,
    ("GET", "/api/v1/knowledge"): handle_knowledge_list,
    ("POST", "/api/v1/knowledge/add"): handle_knowledge_add,
    ("GET", "/api/v1/security/permissions"): handle_security_permissions,
    ("GET", "/api/v1/logs"): handle_logs_list,
    ("GET", "/api/v1/runtime/memory"): handle_memory_usage,
    ("GET", "/api/v1/dashboard"): handle_dashboard_full,
}


def register_desktop_routes(routes_dict: dict) -> None:
    """Add desktop-specific routes to the main route table."""
    routes_dict.update(DESKTOP_ROUTES)


__all__ = [
    "DESKTOP_ROUTES",
    "register_desktop_routes",
    "handle_tasks_list",
    "handle_tasks_action",
    "handle_devices_list",
    "handle_devices_scan",
    "handle_automations_list",
    "handle_automations_add",
    "handle_automations_action",
    "handle_knowledge_list",
    "handle_knowledge_add",
    "handle_security_permissions",
    "handle_logs_list",
    "handle_memory_usage",
    "handle_dashboard_full",
]
