# -*- coding: utf-8 -*-
"""Desktop-specific API routes that bridge UI surfaces to Runtime primitives.

These are thin adapters — no state ownership, no duplicate stores.
All data comes from existing Runtime components.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.api.desktop")


def ok(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def err(code: str, message: str, details: dict | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": details or {}},
    }


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
    "RECOVERY_REQUIRED": "blocked",
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


def handle_tasks_list(
    state: str = "",
    limit: int = 50,
    status: str = "",
    page: int = 1,
    page_size: int | None = None,
    sort_by: str = "",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """List tasks from the Execution Runtime and connectivity layers."""
    try:
        from nous_runtime.task.cli import get_task_manager
        from nous_runtime.task.exceptions import TaskRuntimeError
        from nous_runtime.control_plane.routes import _task_to_dict

        manager = get_task_manager()
        state = state or status
        try:
            runtime_tasks = manager.list(state or None)
        except TaskRuntimeError:
            runtime_tasks = []

        task_list = []
        for t in runtime_tasks:
            task_list.append(
                _task_to_dict(t)
                | {
                    "name": getattr(t, "name", ""),
                    "duration": getattr(t, "duration_ms", None),
                }
            )

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
                    task_list.append(
                        {
                            "task_id": wi.get("work_item_id", ""),
                            "name": wi.get("description", ""),
                            "status": wi.get("status", "unknown"),
                            "priority": "NORMAL",
                            "model_id": "",
                            "duration": None,
                            "created_at": wi.get("created_at", ""),
                        }
                    )
        except Exception:
            pass

        if state and task_list:
            task_list = [
                task
                for task in task_list
                if str(task.get("status") or "").casefold() == state.casefold()
            ]
        task_list.sort(
            key=lambda item: str(
                item.get(sort_by)
                if sort_by
                else item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=sort_order != "asc",
        )
        total = len(task_list)
        status_counts = {}
        for task in task_list:
            key = str(task.get("status") or "unknown")
            status_counts[key] = status_counts.get(key, 0) + 1
        page = max(1, int(page))
        size = max(
            1,
            min(
                int(page_size if page_size is not None else limit),
                500 if page_size is not None else 200,
            ),
        )
        start = (page - 1) * size
        selected = task_list[start : start + size]

        return ok(
            {
                "tasks": selected,
                "total": total,
                "status_counts": status_counts,
                "pagination": {
                    "page": page,
                    "page_size": size,
                    "total": total,
                    "total_pages": max(1, (total + size - 1) // size),
                    "has_next": start + size < total,
                    "has_prev": page > 1,
                },
                "running": sum(
                    1
                    for task in task_list
                    if str(task.get("status") or "").casefold()
                    in {"planning", "running", "recovering", "verifying"}
                ),
            }
        )
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
            from nous_runtime.work import WorkHarness, get_work_supervisor

            checkpoint_path = Path(_workspace()) / ".nous" / "checkpoints.db"
            if not checkpoint_path.is_file():
                raise KeyError(task_id)
            work = WorkHarness(_workspace())
            work.require(task_id)
            supervisor = get_work_supervisor(_workspace())
            if action == "cancel":
                snapshot = supervisor.cancel(
                    task_id,
                    reason="cancelled from Desktop",
                )
            elif action == "pause":
                snapshot = supervisor.pause(task_id, reason="paused from Desktop")
            elif action in {"resume", "recover"}:
                snapshot = supervisor.resume(task_id)
            elif action == "steer":
                snapshot = supervisor.steer(
                    task_id,
                    str(body.get("instruction") or ""),
                    constraints=(
                        dict(body.get("constraints") or {})
                        if isinstance(body.get("constraints"), dict)
                        else None
                    ),
                )
            else:
                return err("NOUS_INVALID_REQUEST", f"Unsupported Work action: {action}")
            return ok(
                {
                    "work": snapshot.to_dict(),
                    "supervisor": supervisor.inspect(task_id)["supervisor"],
                }
            )
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


def handle_work_submit(body: dict[str, Any]) -> dict[str, Any]:
    """Create and dispatch Work in the runtime process, not the UI process."""
    try:
        objective = str(body.get("objective") or "").strip()
        if not objective:
            return err("NOUS_INVALID_REQUEST", "objective is required")
        constraints = body.get("constraints") or {}
        criteria = body.get("completion_criteria") or ()
        if not isinstance(constraints, dict) or not isinstance(criteria, (list, tuple)):
            return err(
                "NOUS_INVALID_REQUEST",
                "constraints must be an object and completion_criteria an array",
            )
        from nous_runtime.work import get_work_supervisor

        supervisor = get_work_supervisor(_workspace())
        snapshot = supervisor.start(
            objective,
            constraints=constraints,
            completion_criteria=tuple(str(item) for item in criteria),
            conversation_id=str(body.get("conversation_id") or ""),
            owner_id=str(body.get("owner_id") or "local"),
            preferred_model=str(body.get("preferred_model") or ""),
            read_only=bool(body.get("read_only", False)),
            max_iterations=int(body.get("max_iterations") or 32),
        )
        return ok(
            {
                "work": snapshot.to_dict(),
                "supervisor": supervisor.inspect(snapshot.run_id)["supervisor"],
            }
        )
    except Exception as exc:
        return err("WORK_SUBMIT_ERROR", str(exc))


def handle_work_inspect(run_id: str) -> dict[str, Any]:
    """Read the complete durable Work projection and process host status."""
    try:
        from nous_runtime.work import get_work_supervisor

        return ok(get_work_supervisor(_workspace()).inspect(run_id))
    except KeyError:
        return err("WORK_NOT_FOUND", f"Work run not found: {run_id}")
    except Exception as exc:
        return err("WORK_INSPECT_ERROR", str(exc))


# Devices


def handle_devices_list() -> dict[str, Any]:
    """Project managed Devices from the same registry as Operations."""
    try:
        from nous_runtime.control_plane.operations import get_operations
        from nous_runtime.reality.registry import DeviceRegistry
        from nous_runtime.core.redaction import redact_sensitive_data

        devices = [
            {
                **device.to_dict(),
                "name": device.device_id,
                "type": device.device_type,
                "status": device.lifecycle.value.lower(),
                "capabilities": list(device.capability_ids),
                "liveness_status": "UNKNOWN",
            }
            for device in DeviceRegistry(get_operations().device_state).list()
        ]
        return ok(
            redact_sensitive_data(
                {
                    "devices": devices,
                    "total": len(devices),
                    # Persisted lifecycle is not a current connectivity observation.
                    "online": 0,
                    "liveness_status": "UNKNOWN",
                    "source": "reality.device_registry",
                }
            )
        )
    except Exception:
        return err(
            "DEVICES_LIST_ERROR",
            "Managed Device state could not be read",
            {"status": "UNKNOWN", "source": "reality.device_registry"},
        )


def handle_devices_scan(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report unavailable discovery without scanning or inventing candidates."""
    if body is not None and body != {}:
        return err(
            "DEVICES_SCAN_INVALID_REQUEST",
            "This compatibility endpoint does not accept discovery targets",
        )
    return ok(
        {
            "discovered": [],
            "timestamp": time.time(),
            "status": "UNAVAILABLE",
            "scan_performed": False,
            "reason": "No qualified discovery backend is configured; use explicit Node pairing or managed Device providers",
        }
    )


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
    store_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _automation_service(authorization_context, *, permission: str, audit=True):
    """Reuse current trusted human identity, permissions, and Governance audit."""
    from nous_runtime.workflow.automation import AutomationConsumer

    service = AutomationConsumer(_workspace())
    service.admit_management(authorization_context, permission=permission, audit=audit)
    service.before_consume = lambda: service.admit_management(
        authorization_context, permission=permission, audit=False
    )
    return service


def handle_automations_list(*, authorization_context=None) -> dict[str, Any]:
    """List configured automations."""
    try:
        store = _automation_store()
        from nous_runtime.workflow.store import WorkflowStore

        configured = [
            {**item, "qualification": "UNQUALIFIED", "execution_qualified": False}
            for item in store.get("automations", [])
        ]
        structured = WorkflowStore(_workspace()).list_automations()
        if structured:
            structured = _automation_service(
                authorization_context, permission="read"
            ).list()
        configured.extend(structured)
        return ok(
            {
                "automations": configured,
                "total": len(configured),
            }
        )
    except PermissionError:
        raise
    except Exception as e:
        return err("AUTOMATIONS_LIST_ERROR", str(e))


def handle_automations_add(
    body: dict[str, Any], *, authorization_context=None
) -> dict[str, Any]:
    """Add a new automation rule."""
    try:
        import uuid

        if body.get("adapter") or body.get("workflow_id"):
            if (
                set(body) - {"adapter", "name", "trigger", "due_at", "firmware_version"}
                or body.get("adapter") != "simulated-reality"
            ):
                return err(
                    "AUTOMATION_UNQUALIFIED",
                    "Only the explicit structured simulated-reality template is supported",
                )
            service = _automation_service(authorization_context, permission="manage")
            return ok(
                service.add_simulation(
                    name=body.get("name", "Governed simulated firmware"),
                    trigger=body.get("trigger", "manual"),
                    due_at=body.get("due_at", ""),
                    firmware_version=body.get("firmware_version", "2.0.0"),
                )
            )
        if authorization_context is not None:
            _automation_service(authorization_context, permission="manage")
        store = _automation_store()
        new_auto = {
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "name": str(body.get("name", "Untitled")),
            "trigger": str(body.get("trigger", "schedule")),
            "schedule": body.get("schedule", ""),
            "action": str(body.get("action", "")),
            "enabled": True,
            "qualification": "UNQUALIFIED",
            "execution_qualified": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        store.setdefault("automations", []).append(new_auto)
        _save_automation_store(store)
        return ok(new_auto)
    except PermissionError:
        raise
    except Exception as e:
        return err("AUTOMATIONS_ADD_ERROR", str(e))


def handle_automations_action(
    body: dict[str, Any], *, authorization_context=None
) -> dict[str, Any]:
    """Enable/disable an automation."""
    try:
        action = str(body.get("action", ""))
        automation_id = str(body.get("automation_id", ""))
        from nous_runtime.workflow.store import WorkflowStore

        if action == "run_due":
            if set(body) - {"action", "limit"}:
                return err(
                    "AUTOMATION_INVALID_REQUEST", "run_due accepts only a bounded limit"
                )
            service = _automation_service(authorization_context, permission="manage")
            return ok(
                {
                    "runs": service.run_due(limit=body.get("limit", 10)),
                    "simulated": True,
                }
            )
        try:
            structured = WorkflowStore(_workspace()).get_automation(automation_id)
        except KeyError:
            structured = None
        if structured is not None:
            allowed = {"action", "automation_id"} | (
                {"trigger_key"}
                if action == "trigger"
                else {"run_id"}
                if action in {"resume", "reconcile", "cancel"}
                else set()
            )
            if set(body) - allowed:
                return err(
                    "AUTOMATION_INVALID_REQUEST",
                    "Only original trigger/run identifiers may be supplied",
                )
            service = _automation_service(authorization_context, permission="manage")
            if action in {"enable", "disable"}:
                return ok(
                    service.store.set_automation_enabled(
                        automation_id,
                        action == "enable",
                        before_publish=service.before_consume,
                    )
                )
            if action == "trigger":
                return ok(service.trigger(automation_id, body.get("trigger_key", "")))
            if action in {"resume", "reconcile", "cancel"}:
                return ok(
                    getattr(service, action)(
                        automation_id, str(body.get("run_id") or "")
                    )
                )
            return err("AUTOMATION_INVALID_REQUEST", "Unsupported Automation action")
        if action not in {"enable", "disable"}:
            return err(
                "AUTOMATION_UNQUALIFIED",
                "Legacy free-text configuration cannot execute a Workflow",
            )
        if authorization_context is not None:
            _automation_service(authorization_context, permission="manage")
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
    except PermissionError:
        raise
    except Exception as e:
        return err("AUTOMATIONS_ACTION_ERROR", str(e))


def handle_automations_history(
    automation_id: str, params=None, *, authorization_context=None
):
    try:
        return ok(
            _automation_service(authorization_context, permission="read").history(
                automation_id, limit=int((params or {}).get("limit", 50))
            )
        )
    except PermissionError:
        raise
    except (KeyError, ValueError) as exc:
        return err("AUTOMATION_HISTORY_ERROR", str(exc))


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
    store_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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
    """Inspect canonical configuration without inventing an authorization."""
    try:
        from nous_runtime.governance import get_gate
        from nous_runtime.governance.permission import PermissionEngine

        gate = get_gate()
        engine = gate.permission_engine
        state = (
            "unconfigured"
            if engine is None
            else "configured"
            if isinstance(engine, PermissionEngine)
            else "unknown"
        )
        return ok(
            {
                "permissions": _default_permissions(),
                "configuration_state": state,
                "configuration": engine.configuration_status()
                if isinstance(engine, PermissionEngine)
                else None,
                "permissions_evaluated": False,
                "reason": (
                    "Authorization requires the current subject, action, resource and context. "
                    "Selected-file delivery requires a trusted host-configured canonical PermissionEngine."
                ),
            }
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        from nous_runtime.core.redaction import redact_sensitive_text

        return err("SECURITY_PERMISSION_READ_ERROR", redact_sensitive_text(str(exc)))


def _default_permissions() -> list[dict]:
    """Compatibility descriptions only; no request has been evaluated here."""
    return [
        {
            "id": "model_access",
            "name": "Model Access",
            "description": "Allow AI models to process your requests",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "low",
        },
        {
            "id": "file_access",
            "name": "File Access",
            "description": "Allow reading and writing files in workspace",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "medium",
        },
        {
            "id": "network_access",
            "name": "Network Access",
            "description": "Allow connecting to external services",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "medium",
        },
        {
            "id": "code_execution",
            "name": "Code Execution",
            "description": "Allow executing generated code",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "high",
        },
        {
            "id": "system_commands",
            "name": "System Commands",
            "description": "Allow running system shell commands",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "high",
        },
        {
            "id": "device_control",
            "name": "Device Control",
            "description": "Allow controlling connected devices",
            "granted": None,
            "evaluation_state": "UNKNOWN",
            "risk": "high",
        },
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
        for line in lines[-limit * 3 :]:  # Over-sample then filter
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
        return ok(
            {
                "rss_mb": round(mem.rss / (1024 * 1024), 1),
                "vms_mb": round(mem.vms / (1024 * 1024), 1),
                "used_pct": round(vm.percent, 1),
                "total_gb": round(vm.total / (1024**3), 1),
                "available_gb": round(vm.available / (1024**3), 1),
            }
        )
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
        tasks = task_data.get("data", {}) if task_data.get("ok") else {}

        # Device summary
        dev_data = handle_devices_list()
        devices = dev_data.get("data", {}) if dev_data.get("ok") else {}

        # Memory
        mem_data = handle_memory_usage()
        memory = mem_data.get("data", {}) if mem_data.get("ok") else {}

        return ok(
            {
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
            }
        )
    except Exception as e:
        return err("DASHBOARD_ERROR", str(e))


# Route table

DESKTOP_ROUTES = {
    ("GET", "/api/v1/tasks"): handle_tasks_list,
    ("POST", "/api/v1/tasks/action"): handle_tasks_action,
    ("POST", "/api/v1/work"): handle_work_submit,
    ("GET", "/api/v1/work/{run_id}"): handle_work_inspect,
    ("GET", "/api/v1/devices"): handle_devices_list,
    ("POST", "/api/v1/devices/scan"): handle_devices_scan,
    ("GET", "/api/v1/automations"): handle_automations_list,
    ("POST", "/api/v1/automations/add"): handle_automations_add,
    ("POST", "/api/v1/automations/action"): handle_automations_action,
    ("GET", "/api/v1/automations/{automation_id}/history"): handle_automations_history,
    ("GET", "/api/v1/knowledge"): handle_knowledge_list,
    ("POST", "/api/v1/knowledge/add"): handle_knowledge_add,
    ("GET", "/api/v1/security/permissions"): handle_security_permissions,
    ("GET", "/api/v1/logs"): handle_logs_list,
    ("GET", "/api/v1/runtime/memory"): handle_memory_usage,
    ("GET", "/api/v1/dashboard"): handle_dashboard_full,
}


AUTOMATION_AUTHENTICATED_ROUTES = {
    handle_automations_list,
    handle_automations_add,
    handle_automations_action,
    handle_automations_history,
}


DESKTOP_GOVERNANCE = {
    ("POST", "/api/v1/work"): (
        "runtime.execute",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/tasks/action"): (
        "runtime.execute",
        "local_write",
        "reversible",
    ),
}


def register_desktop_routes(routes_dict: dict) -> None:
    """Add desktop-specific routes to the main route table."""
    routes_dict.update(DESKTOP_ROUTES)


__all__ = [
    "DESKTOP_ROUTES",
    "DESKTOP_GOVERNANCE",
    "register_desktop_routes",
    "handle_tasks_list",
    "handle_tasks_action",
    "handle_work_submit",
    "handle_work_inspect",
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
