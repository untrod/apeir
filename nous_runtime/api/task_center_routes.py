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
    """Project persisted EventStream evidence, retaining its original identity."""
    try:
        from nous_runtime.events import EventStream

        maximum = max(1, min(int(limit), 500))
        stream = EventStream(_workspace())
        events = []
        if task_id:
            events = list(stream.iter_persisted_events(task_id, limit=maximum))
        if not events:
            for run in stream.list_runs(limit=200):
                if task_id and run.task_id != task_id:
                    continue
                events.extend(
                    stream.iter_persisted_events(
                        run.run_id, limit=maximum - len(events)
                    )
                )
                if len(events) >= maximum:
                    break

        projected = [
            event.to_dict() | {"data": event.payload, "source": "EventStream"}
            for event in events
        ]

        if not projected and task_id:
            # Fallback: build from task manager
            try:
                from nous_runtime.task.cli import get_task_manager

                manager = get_task_manager()
                if task_id:
                    t = manager.get(task_id)
                    if t:
                        projected = [
                            {
                                "sequence": 0,
                                "event_type": "task_created",
                                "timestamp": getattr(t, "created_at", ""),
                                "data": {"status": getattr(t, "status", "unknown")},
                                "source": "task-manager-projection",
                            }
                        ]
            except Exception:
                pass

        return ok(
            {
                "task_id": task_id or "all",
                "events": projected,
                "count": len(projected),
                "scope": "persisted-runtime-events",
            }
        )
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

            for t in all_tasks or []:
                tid = getattr(t, "task_id", str(t))
                status = getattr(t, "status", getattr(t, "state", "unknown"))
                name = getattr(t, "name", tid)
                deps = getattr(t, "depends_on", []) or []

                nodes.append(
                    {
                        "id": tid,
                        "label": name or tid,
                        "status": status,
                        "priority": getattr(t, "priority", "NORMAL"),
                    }
                )

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
                    nodes.append(
                        {
                            "id": wid,
                            "label": wi.get("description", wid),
                            "status": wi.get("status", "unknown"),
                            "project": p.get("name", ""),
                        }
                    )
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
        from nous_runtime.api.routes import handle_list_artifacts

        registered = handle_list_artifacts(task_id=task_id, limit=500)
        if not registered["ok"]:
            return registered
        artifacts = list(registered["data"]["artifacts"])
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
                        artifacts.append(
                            {
                                "name": f.name,
                                "path": str(f.relative_to(ws)),
                                "size_bytes": f.stat().st_size,
                                "type": f.suffix.lstrip(".") or "file",
                                "scope": "legacy-filesystem-metadata",
                                "integrity": "UNKNOWN",
                                "effect_verification_performed": False,
                            }
                        )

        return ok(
            {
                "task_id": task_id,
                "artifacts": artifacts,
                "count": len(artifacts),
                "total": len(artifacts),
            }
        )
    except Exception as e:
        return err("TASK_ARTIFACTS_ERROR", str(e))


# Task Verification


def handle_task_verification(task_id: str) -> dict[str, Any]:
    """Read recorded Reality verification; evaluation scores are separate."""
    try:
        verification = {
            "task_id": task_id,
            "verified": False,
            "verdict": "UNKNOWN",
            "committed": False,
            "checks": [],
            "effect_verification": {},
            "scope": "recorded-runtime-service-effect-verification",
        }

        from nous_runtime.node_runtime.distributed_work import DistributedWorkStore

        state = Path(
            os.environ.get("NOUS_CONTROLLER_STATE_DIR")
            or str(Path(_workspace()) / ".nous" / "relay")
        )
        if (state / "distributed-works.json").is_file():
            work = DistributedWorkStore(state).get(task_id)
            if work is not None:
                recorded = dict(work.effect_verification)
                bound = (
                    recorded.get("operation_id") == work.work_id
                    and recorded.get("receipt_operation_id") == work.work_id
                    and bool(recorded.get("observation_ids"))
                    and work.state.value in {"VERIFIED", "COMMITTED"}
                )
                verdict = recorded.get("verdict", "UNKNOWN") if bound else "UNKNOWN"
                if verdict not in {"MATCH", "MISMATCH", "UNKNOWN"}:
                    verdict = "UNKNOWN"
                verification.update(
                    effect_verification=recorded,
                    verdict=verdict,
                    verified=verdict == "MATCH",
                    committed=verdict == "MATCH" and work.state.value == "COMMITTED",
                    work_state=work.state.value,
                    evidence_refs=list(work.evidence_refs),
                    source="DistributedWorkStore",
                )

        # Check evaluation records
        try:
            from nous_runtime.evaluation.history import EvaluationHistory

            records = (
                EvaluationHistory(_workspace()).list(target_id=task_id, limit=1)
                if (Path(_workspace()) / "evaluation.db").is_file()
                else []
            )
            for r in records:
                rd = r.to_dict() if hasattr(r, "to_dict") else {}
                if rd.get("target_id") == task_id:
                    verification["evaluation"] = {
                        "score": rd.get("composite_score"),
                        "passed": rd.get("passed", False),
                        "evaluation_id": rd.get("id"),
                    }
                    break
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
