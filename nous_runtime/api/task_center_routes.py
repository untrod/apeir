# -*- coding: utf-8 -*-
"""Task Center API routes — timeline, graph, artifacts, verification."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.api.task_center")


def ok(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _workspace() -> str:
    return os.environ.get("NOUS_WORKSPACE_ROOT", str(Path.home() / ".nous"))


# Task Timeline

def handle_task_timeline(task_id: str = "", limit: int = 50) -> dict[str, Any]:
    """Get execution timeline for task(s)."""
    try:

        events = []
        if task_id:
            try:
                from nous_runtime.events import EventStream
                stream = EventStream(_workspace())
                persisted = list(stream.iter_persisted_events(task_id, limit=limit))
                events = [
                    {
                        "sequence": e.sequence,
                        "event_type": e.event_type,
                        "timestamp": e.timestamp,
                        "data": e.data if hasattr(e, "data") else {},
                    }
                    for e in persisted
                ]
            except Exception:
                pass

        if not events:
            # Fallback: build from task manager
            try:
                from nous_runtime.task.cli import get_task_manager
                manager = get_task_manager()
                if task_id:
                    t = manager.get(task_id)
                    if t:
                        events = [
                            {
                                "sequence": 0,
                                "event_type": "task_created",
                                "timestamp": getattr(t, "created_at", ""),
                                "data": {"status": getattr(t, "status", "unknown")},
                            }
                        ]
            except Exception:
                pass

        return ok({
            "task_id": task_id or "all",
            "events": events,
            "count": len(events),
        })
    except Exception as e:
        return err("TASK_TIMELINE_ERROR", str(e))


# Task Graph

def handle_task_graph(task_id: str = "") -> dict[str, Any]:
    """Get task dependency graph."""
    try:
        nodes = []
        edges = []

        try:
            from nous_runtime.task.cli import get_task_manager
            manager = get_task_manager()
            all_tasks = manager.list() if hasattr(manager, "list") else []

            for t in (all_tasks or []):
                tid = getattr(t, "task_id", str(t))
                status = getattr(t, "status", getattr(t, "state", "unknown"))
                name = getattr(t, "name", tid)
                deps = getattr(t, "depends_on", []) or []

                nodes.append({
                    "id": tid,
                    "label": name or tid,
                    "status": status,
                    "priority": getattr(t, "priority", "NORMAL"),
                })

                for dep in deps:
                    edges.append({"from": dep, "to": tid})
        except Exception:
            pass

        # Add connectivity project work items
        try:
            from nous_runtime.connectivity.project.store import ProjectStore
            store = ProjectStore()
            for p in store.list_projects():
                for wi in store.list_work_items(p.get("project_id", "")):
                    wid = wi.get("work_item_id", "")
                    nodes.append({
                        "id": wid,
                        "label": wi.get("description", wid),
                        "status": wi.get("status", "unknown"),
                        "project": p.get("name", ""),
                    })
                    for dep_id in wi.get("depends_on", []) or []:
                        edges.append({"from": dep_id, "to": wid})
        except Exception:
            pass

        return ok({"nodes": nodes, "edges": edges})
    except Exception as e:
        return err("TASK_GRAPH_ERROR", str(e))


# Task Artifacts

def handle_task_artifacts(task_id: str) -> dict[str, Any]:
    """Get artifacts produced by a task."""
    try:
        artifacts = []
        ws = Path(_workspace())

        # Check common artifact locations
        artifact_dirs = [
            ws / "artifacts" / task_id,
            ws / "tasks" / task_id / "artifacts",
            ws / "outputs" / task_id,
        ]

        for ad in artifact_dirs:
            if ad.is_dir():
                for f in ad.rglob("*"):
                    if f.is_file():
                        artifacts.append({
                            "name": f.name,
                            "path": str(f.relative_to(ws)),
                            "size_bytes": f.stat().st_size,
                            "type": f.suffix.lstrip(".") or "file",
                        })

        return ok({
            "task_id": task_id,
            "artifacts": artifacts,
            "count": len(artifacts),
        })
    except Exception as e:
        return err("TASK_ARTIFACTS_ERROR", str(e))


# Task Verification

def handle_task_verification(task_id: str) -> dict[str, Any]:
    """Get verification status for a task."""
    try:
        verification = {
            "task_id": task_id,
            "verified": False,
            "checks": [],
        }

        # Check governance verification
        try:
            from nous_runtime.governance.gate import get_gate
            gate = get_gate()
            if hasattr(gate, "get_verification"):
                v = gate.get_verification(task_id)
                if v:
                    verification["verified"] = v.get("passed", False)
                    verification["checks"] = v.get("checks", [])
        except Exception:
            pass

        # Check evaluation records
        try:
            from nous_runtime.evaluation.history import EvaluationHistory
            history = EvaluationHistory(_workspace())
            records = history.list(limit=5)
            for r in records:
                rd = r.to_dict() if hasattr(r, "to_dict") else {}
                if rd.get("target_id") == task_id:
                    verification["evaluation"] = {
                        "score": rd.get("overall_score"),
                        "passed": rd.get("passed", False),
                    }
                    verification["verified"] = rd.get("passed", False)
        except Exception:
            pass

        return ok(verification)
    except Exception as e:
        return err("TASK_VERIFICATION_ERROR", str(e))


# Route table

TASK_CENTER_ROUTES = {
    ("GET", "/api/v1/tasks/timeline"): handle_task_timeline,
    ("GET", "/api/v1/tasks/graph"): handle_task_graph,
    ("GET", "/api/v1/tasks/{task_id}/artifacts"): handle_task_artifacts,
    ("GET", "/api/v1/tasks/{task_id}/verification"): handle_task_verification,
}


def register_task_center_routes(routes_dict: dict) -> None:
    routes_dict.update(TASK_CENTER_ROUTES)


__all__ = [
    "TASK_CENTER_ROUTES",
    "register_task_center_routes",
]
