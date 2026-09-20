# -*- coding: utf-8 -*-
"""Health Checker — subsystem health aggregation."""
from __future__ import annotations
from typing import Any

class HealthChecker:
    """Checks health of all subsystems."""
    @staticmethod
    def check_all() -> dict[str, Any]:
        results = {}
        # Context
        try:
            from nous_runtime.context.store import ContextStore
            results["context"] = {"ok": True, "snapshots": ContextStore().stats().get("total_snapshots", 0)}
        except Exception as e:
            results["context"] = {"ok": False, "error": str(e)}
        # Governance
        try:
            from nous_runtime.governance.gate import get_gate
            get_gate()
            results["governance"] = {"ok": True}
        except Exception as e:
            results["governance"] = {"ok": False, "error": str(e)}
        # Network
        try:
            from nous_runtime.network.health import NetworkHealth
            nh = NetworkHealth().network_health()
            results["network"] = {"ok": True, "healthy": nh["healthy"], "total": nh["total_nodes"]}
        except Exception as e:
            results["network"] = {"ok": False, "error": str(e)}
        # Overall
        all_ok = all(v.get("ok", False) for v in results.values())
        return {"healthy": all_ok, "components": results}
