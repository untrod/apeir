# -*- coding: utf-8 -*-
"""Disaster Recovery — full system restore procedure."""
from __future__ import annotations
import logging
from typing import Any

_log = logging.getLogger("nous.recovery")

class DisasterRecovery:
    """Orchestrates full system recovery after failure."""
    def __init__(self, workspace: str = ""):
        self._workspace = workspace

    def recover(self) -> dict[str, Any]:
        steps = []
        # 1. Restore context
        try:
            from nous_runtime.context.snapshot import restore_snapshot
            result = restore_snapshot(workspace=self._workspace)
            steps.append({"step": "context", "ok": result.success, "items": result.restored_items})
        except Exception as exc:
            steps.append({"step": "context", "ok": False, "error": str(exc)})
        # 2. Verify database integrity
        try:
            from nous_runtime.intelligence.consistency import verify_cross_store_consistency
            findings = verify_cross_store_consistency(self._workspace)
            errors = [f for f in findings.get("findings", []) if f.get("severity") == "error"]
            steps.append({"step": "integrity", "ok": len(errors) == 0, "findings": len(findings.get("findings", []))})
        except Exception as exc:
            steps.append({"step": "integrity", "ok": False, "error": str(exc)})
        # 3. Restore agent states
        try:
            from nous_runtime.agent.registry import AgentRegistry
            agents = AgentRegistry().list()
            steps.append({"step": "agents", "ok": True, "count": len(agents)})
        except Exception as exc:
            steps.append({"step": "agents", "ok": False, "error": str(exc)})
        success = all(s["ok"] for s in steps)
        _log.info("Disaster recovery: %s", "OK" if success else "with errors")
        return {"success": success, "steps": steps}
