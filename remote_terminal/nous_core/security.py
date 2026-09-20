# -*- coding: utf-8 -*-
"""
Security Policy Engine — risk-based enforcement + logical sandbox.

Risk levels and enforcement:
  LOW      → auto-execute, audit only
  MEDIUM   → execute, audit, log
  HIGH     → require confirmation + audit
  CRITICAL → require confirmation + revocable + double audit

Sandbox (logical isolation):
  - Module permission whitelist
  - Capability permission check
  - Timeout enforcement
  - Secret isolation
  - Write rate limiting
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.security")

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"

# Default policy per risk level
_POLICY = {
    RISK_LOW:      {"auto_execute": True,  "require_confirm": False, "require_revoke": False, "double_audit": False},
    RISK_MEDIUM:   {"auto_execute": True,  "require_confirm": False, "require_revoke": False, "double_audit": False},
    RISK_HIGH:     {"auto_execute": False, "require_confirm": True,  "require_revoke": False, "double_audit": False},
    RISK_CRITICAL: {"auto_execute": False, "require_confirm": True,  "require_revoke": True,  "double_audit": True},
}

# Module permission whitelist
_MODULE_PERMISSIONS: dict[str, list[str]] = {}

# Write rate limiter: {key: [timestamps]}
_rate_buckets: dict[str, list[float]] = {}
_RATE_LIMIT_WRITES_PER_MIN = 60


def check_risk(capability_name: str, risk_level: str) -> dict[str, Any]:
    """
    Check if a capability can execute based on its risk level.
    Returns: {"allowed": bool, "requires_confirmation": bool, "reason": str}
    """
    policy = _POLICY.get(risk_level, _POLICY[RISK_LOW])

    if risk_level == RISK_CRITICAL:
        return {
            "allowed": False,
            "requires_confirmation": True,
            "requires_revoke_period": True,
            "reason": f"CRITICAL risk: '{capability_name}' requires explicit confirmation with revocation window",
        }

    if risk_level == RISK_HIGH:
        return {
            "allowed": False,
            "requires_confirmation": True,
            "requires_revoke_period": False,
            "reason": f"HIGH risk: '{capability_name}' requires user confirmation",
        }

    return {
        "allowed": True,
        "requires_confirmation": False,
        "requires_revoke_period": False,
        "reason": f"{risk_level.upper()} risk: auto-approved",
    }


def check_module_permission(module_id: str, permission: str) -> bool:
    """Check if a module has a specific permission."""
    if module_id not in _MODULE_PERMISSIONS:
        return False
    allowed = _MODULE_PERMISSIONS[module_id]
    # Wildcard check
    for perm in allowed:
        if perm == "*" or perm == permission:
            return True
        if perm.endswith(".*") and permission.startswith(perm[:-1]):
            return True
    return False


def register_module_permissions(module_id: str, permissions: list[str]):
    """Register a module's allowed permissions."""
    _MODULE_PERMISSIONS[module_id] = permissions
    _log.info("Module '%s' permissions registered: %s", module_id, permissions)


def check_rate_limit(key: str, limit_per_min: int = 0) -> bool:
    """Check write rate limit. Returns True if allowed."""
    limit = limit_per_min or _RATE_LIMIT_WRITES_PER_MIN
    now = _time_module.time()

    if key not in _rate_buckets:
        _rate_buckets[key] = []
    bucket = [t for t in _rate_buckets[key] if now - t < 60]
    _rate_buckets[key] = bucket

    if len(bucket) >= limit:
        _log.warning("Rate limit hit: %s (%d/min)", key, len(bucket))
        return False

    bucket.append(now)
    return True


def record_security_event(
    event_type: str,
    *,
    actor: str = "",
    target: str = "",
    risk: str = RISK_LOW,
    decision: str = "",
    detail: dict[str, Any] | None = None,
) -> str:
    """Record a security decision to audit."""
    eid = _ids.make_aud_id()
    now = _time.utc_now()
    detail_safe = _sanitize_secrets(detail or {})

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO security_events (id, event_type, actor, target, risk,
                   decision, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, event_type, actor, target, risk, decision,
                 _json.dumps(detail_safe, ensure_ascii=False), now),
            )
        return eid
    except Exception:
        return ""


def _sanitize_secrets(detail: dict) -> dict:
    """Remove secrets from detail dict."""
    secret_keys = {"key", "token", "password", "secret", "private", "credential", "signing"}
    return {k: ("***MASKED***" if any(s in k.lower() for s in secret_keys) else v)
            for k, v in detail.items()}


def get_security_stats() -> dict[str, Any]:
    """Get security overview for dashboard."""
    try:
        with _connect(readonly=True) as db:
            total = db.execute("SELECT COUNT(*) as n FROM security_events").fetchone()["n"]
            by_risk = db.execute(
                "SELECT risk, COUNT(*) as n FROM security_events GROUP BY risk"
            ).fetchall()
            by_decision = db.execute(
                "SELECT decision, COUNT(*) as n FROM security_events GROUP BY decision"
            ).fetchall()
            return {
                "total_events": total,
                "by_risk": {r["risk"]: r["n"] for r in by_risk},
                "by_decision": {d["decision"]: d["n"] for d in by_decision},
            }
    except Exception:
        return {}

# Need time module for rate limiting
import time as _time_module
