# -*- coding: utf-8 -*-
"""
Audit System — structured, queryable audit logging.

All security-relevant actions (tool execution, confirmation, auth, config changes)
are recorded here. Audit logs are append-only — designed for forensic analysis
and compliance.

Design:
  - Every audit entry has: action, actor, target, result, detail, ip_address.
  - Detail is always sanitized (no keys, tokens, passwords).
  - Query API supports filtering by action, actor, time range.
  - Auto-purge old entries (configurable retention, default 90 days).

Usage:
  from nous_core.audit import audit_log, query_logs, get_audit_trail

  audit_log("tool.executed", actor="phone", target="run_command",
            result="success", detail={"command": "dir", "output_length": 200})
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.audit")


# Write

def audit_log(
    action: str,
    *,
    actor: str = "",
    target: str = "",
    session_id: str = "",
    result: str = "success",
    detail: dict[str, Any] | None = None,
    ip_address: str = "",
) -> str:
    """
    Write an audit entry. Returns the audit ID.

    All detail values are truncated to prevent unbounded growth.
    Secret patterns (key/token/password) are masked before storage.
    """
    aud_id = _ids.make_aud_id()
    now = _time.utc_now()
    detail_sanitized = _sanitize(detail or {})

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO audit_logs (id, action, actor, target, session_id,
                   result, detail, ip_address, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aud_id, action, actor[:100], target[:200], session_id[:64],
                 result[:50], _json.dumps(detail_sanitized, ensure_ascii=False),
                 ip_address[:45], now),
            )
        return aud_id
    except Exception as e:
        _log.warning("audit_log failed for %s (non-fatal): %s", action, e)
        return ""


# Query

def query_logs(
    action: str = "",
    actor: str = "",
    session_id: str = "",
    result: str = "",
    since: str = "",
    until: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query audit logs with optional filters."""
    limit = max(1, min(limit, 500))
    conds: list[str] = []
    params: list[Any] = []

    if action:
        conds.append("action = ?"); params.append(action)
    if actor:
        conds.append("actor = ?"); params.append(actor)
    if session_id:
        conds.append("session_id = ?"); params.append(session_id)
    if result:
        conds.append("result = ?"); params.append(result)
    if since:
        conds.append("created_at > ?"); params.append(since)
    if until:
        conds.append("created_at < ?"); params.append(until)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    query = f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with _connect(readonly=True) as db:
            return [_row_to_audit(r) for r in db.execute(query, params).fetchall()]
    except Exception:
        return []


def get_audit_trail(session_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Get the full audit trail for a specific session (chronological order)."""
    limit = max(1, min(limit, 1000))
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM audit_logs WHERE session_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [_row_to_audit(r) for r in rows]
    except Exception:
        return []


def count_actions(action: str = "", since: str = "") -> int:
    """Count audit entries, optionally filtered by action type and time."""
    try:
        with _connect(readonly=True) as db:
            conds = []
            params = []
            if action:
                conds.append("action = ?"); params.append(action)
            if since:
                conds.append("created_at > ?"); params.append(since)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            row = db.execute(
                f"SELECT COUNT(*) as cnt FROM audit_logs {where}", params
            ).fetchone()
            return row["cnt"] if row else 0
    except Exception:
        return 0


def purge_old_audit_logs(retention_days: int = 90) -> int:
    """Delete audit logs older than retention_days. Returns count deleted."""
    try:
        with _connect() as db:
            cur = db.execute(
                "DELETE FROM audit_logs WHERE created_at < datetime('now', ?)",
                (f'-{retention_days} days',),
            )
            deleted = cur.rowcount
            if deleted:
                _log.info("Purged %d audit logs older than %d days", deleted, retention_days)
            return deleted
    except Exception as e:
        _log.error("purge_old_audit_logs: %s", e)
        return 0


# Security Checks

def check_token_expiry(client_id: str) -> dict[str, Any]:
    """
    Check if a client's token has expired or needs rotation.
    Reads the audit log for the client's last auth.

    Returns: {"valid": bool, "last_auth": str, "days_since_last_auth": int, "warning": str}
    """
    entries = query_logs(action="auth.success", actor=client_id, limit=1)
    if not entries:
        return {"valid": True, "last_auth": "", "days_since_last_auth": 0,
                "warning": "No auth history found"}
    last = entries[0]["created_at"]
    days = _days_ago(last)
    if days > 30:
        return {"valid": True, "last_auth": last, "days_since_last_auth": days,
                "warning": f"Last auth was {days} days ago — consider token rotation"}
    return {"valid": True, "last_auth": last, "days_since_last_auth": days, "warning": ""}


# Helpers

_SECRET_PATTERNS = [
    "key", "token", "password", "passwd", "secret", "api_key", "auth",
    "signing", "private", "credential",
]


def _sanitize(detail: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive fields in audit detail."""
    sanitized = {}
    for k, v in detail.items():
        k_lower = k.lower()
        if any(p in k_lower for p in _SECRET_PATTERNS):
            sanitized[k] = "***MASKED***"
        elif isinstance(v, str) and len(v) > 500:
            sanitized[k] = v[:500] + "..."
        elif isinstance(v, dict):
            sanitized[k] = _sanitize(v)
        elif isinstance(v, list):
            sanitized[k] = [_sanitize_item(i) for i in v[:20]]
        else:
            sanitized[k] = v
    return sanitized


def _sanitize_item(item):
    if isinstance(item, dict):
        return _sanitize(item)
    if isinstance(item, str) and len(item) > 500:
        return item[:500] + "..."
    return item


def _row_to_audit(row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["detail"] = _json.loads(d.get("detail", "{}"))
    except (_json.JSONDecodeError, TypeError):
        d["detail"] = {}
    return d


def _days_ago(iso_str: str) -> int:
    if not iso_str:
        return 0
    epoch = _time.parse_iso(iso_str)
    if epoch <= 0:
        return 0
    import time
    return int((time.time() - epoch) / 86400)
