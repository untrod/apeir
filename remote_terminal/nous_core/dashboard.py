# -*- coding: utf-8 -*-
"""
Dashboard data API — feeds the web dashboard with live system state.
Single JSON endpoint returns all sections at once.
"""
from __future__ import annotations
from typing import Any
from .db import connect as _connect


def get_dashboard_data() -> dict[str, Any]:
    """Return all dashboard sections as a single dict."""
    return {
        "brain": _brain_status(),
        "devices": _devices_status(),
        "events": _recent_events(20),
        "jobs_running": _jobs_by_status("running", 10),
        "jobs_failed": _jobs_by_status("failed", 10),
        "notifications": _recent_notifications(10),
        "audit_high": _high_risk_audit(10),
        "automation_log": _recent_automation_log(10),
        "inbox": _inbox_summary(),
    }


def _brain_status() -> dict:
    try:
        with _connect(readonly=True) as db:
            evt_cnt = db.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]
            evt_last = db.execute(
                "SELECT type, created_at FROM events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            job_cnt = db.execute("SELECT COUNT(*) as n FROM jobs").fetchone()["n"]
            job_running = db.execute(
                "SELECT COUNT(*) as n FROM jobs WHERE status='running'"
            ).fetchone()["n"]
            job_pending = db.execute(
                "SELECT COUNT(*) as n FROM jobs WHERE status='pending'"
            ).fetchone()["n"]
            return {
                "events_total": evt_cnt,
                "last_event": f"{evt_last['type']} at {evt_last['created_at'][:19]}" if evt_last else "none",
                "jobs_total": job_cnt,
                "jobs_running": job_running,
                "jobs_pending": job_pending,
            }
    except Exception:
        return {"error": "db read failed"}


def _devices_status() -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT id, name, device_type, is_online, last_seen, last_heartbeat FROM devices ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _recent_events(limit: int) -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT type, source, session_id, created_at, processed "
                "FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _jobs_by_status(status: str, limit: int) -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT id, type, source, status, created_at, started_at, completed_at, error "
                "FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _recent_notifications(limit: int) -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT id, type, title, target_client, priority, read_at, created_at "
                "FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _high_risk_audit(limit: int) -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT action, actor, target, result, created_at "
                "FROM audit_logs WHERE result IN ('denied','timeout','awaiting_confirmation','failed') "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _recent_automation_log(limit: int) -> list[dict]:
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT al.rule_id, ar.name as rule_name, al.action_type, al.success, al.fired_at "
                "FROM automation_log al LEFT JOIN automation_rules ar ON al.rule_id = ar.id "
                "ORDER BY al.fired_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _inbox_summary() -> dict:
    try:
        with _connect(readonly=True) as db:
            new = db.execute("SELECT COUNT(*) as n FROM inbox WHERE status='new'").fetchone()["n"]
            by_cat = db.execute(
                "SELECT category, COUNT(*) as n FROM inbox WHERE status='new' GROUP BY category ORDER BY n DESC"
            ).fetchall()
            return {
                "total_new": new,
                "by_category": {r["category"]: r["n"] for r in by_cat},
            }
    except Exception:
        return {"total_new": 0, "by_category": {}}
