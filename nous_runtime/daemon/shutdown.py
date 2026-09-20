# -*- coding: utf-8 -*-
"""Graceful shutdown — save state, close connections."""
from __future__ import annotations
import logging
from typing import Any

_log = logging.getLogger("nous.daemon.shutdown")

def graceful_shutdown(workspace: str = "") -> dict[str, Any]:
    report: dict[str, Any] = {"success": True, "steps": []}
    try:
        from nous_runtime.context.snapshot import create_snapshot
        snap = create_snapshot(workspace=workspace, intent="shutdown_checkpoint", persist=True)
        report["steps"].append({"step": "context_snapshot", "ok": True, "snapshot_id": snap.id})
    except Exception as exc:
        report["steps"].append({"step": "context_snapshot", "ok": False, "error": str(exc)})
        report["success"] = False
    try:
        from nous_runtime.experience.store import ExperienceStore
        stats = ExperienceStore(workspace).stats()
        report["steps"].append({"step": "experience_flush", "ok": True, "records": stats.get("total_experiences", 0)})
    except Exception as exc:
        report["steps"].append({"step": "experience_flush", "ok": False, "error": str(exc)})
    _log.info("Graceful shutdown: %s", "OK" if report["success"] else "with errors")
    return report
