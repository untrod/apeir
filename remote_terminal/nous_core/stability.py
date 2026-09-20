# -*- coding: utf-8 -*-
"""
Stability Monitor — tracks long-term health of the Nous runtime.

Records hourly snapshots: uptime, memory, DB size, job depth,
notification loss, device online rate, API latency.
"""
from __future__ import annotations

import logging as _logging
import os as _os
import time as _time_module
from typing import Any

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.stability")


def take_snapshot() -> dict[str, Any]:
    """Record current health snapshot. Returns snapshot dict."""
    now = _time.utc_now()
    sid = _ids.make_id("stb")

    snapshot = {
        "id": sid, "timestamp": now,
        "events_total": _safe_count("events"),
        "jobs_pending": _safe_count("jobs", "status='pending'"),
        "jobs_running": _safe_count("jobs", "status='running'"),
        "jobs_failed": _safe_count("jobs", "status='failed'"),
        "devices_total": _safe_count("devices"),
        "devices_online": _safe_count("devices", "is_online=1"),
        "notifications_unread": _safe_count("notifications", "read_at=''"),
        "inbox_new": _safe_count("inbox", "status='new'"),
        "db_size_kb": _db_size_kb(),
        "uptime_seconds": _time_module.monotonic(),
    }

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO stability_snapshots (id, timestamp, events_total,
                   jobs_pending, jobs_running, jobs_failed, devices_total,
                   devices_online, notifications_unread, inbox_new,
                   db_size_kb, uptime_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, now, snapshot["events_total"], snapshot["jobs_pending"],
                 snapshot["jobs_running"], snapshot["jobs_failed"],
                 snapshot["devices_total"], snapshot["devices_online"],
                 snapshot["notifications_unread"], snapshot["inbox_new"],
                 snapshot["db_size_kb"], snapshot["uptime_seconds"]),
            )
    except Exception as e:
        _log.warning("Snapshot save failed: %s", e)

    return snapshot


def get_stability_report(hours: int = 24) -> dict[str, Any]:
    """Get stability report for the last N hours."""
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM stability_snapshots "
                "WHERE timestamp > datetime('now', ?) "
                "ORDER BY timestamp ASC",
                (f'-{hours} hours',),
            ).fetchall()

            if not rows:
                return {"status": "no_data", "hours": hours}

            snapshots = [dict(r) for r in rows]
            first = snapshots[0]
            last = snapshots[-1]

            # Trends
            events_growth = (last["events_total"] - first["events_total"])
            jobs_peak_pending = max(s["jobs_pending"] for s in snapshots)
            jobs_peak_failed = max(s["jobs_failed"] for s in snapshots)
            db_growth = last["db_size_kb"] - first["db_size_kb"]

            warnings = []
            if jobs_peak_failed > 3:
                warnings.append(f"{jobs_peak_failed} failed jobs at peak")
            if db_growth > 10240:
                warnings.append(f"DB grew {db_growth}KB in {hours}h")
            if last["jobs_pending"] > 20:
                warnings.append(f"{last['jobs_pending']} pending jobs")

            return {
                "status": "healthy" if not warnings else "warning",
                "hours": hours,
                "snapshots_count": len(snapshots),
                "first_seen": first["timestamp"],
                "last_seen": last["timestamp"],
                "trends": {
                    "events_growth": events_growth,
                    "jobs_peak_pending": jobs_peak_pending,
                    "jobs_peak_failed": jobs_peak_failed,
                    "db_growth_kb": db_growth,
                    "devices_online_now": last["devices_online"],
                },
                "current": {
                    "events": last["events_total"],
                    "jobs_pending": last["jobs_pending"],
                    "jobs_failed": last["jobs_failed"],
                    "devices_online": last["devices_online"],
                    "inbox_new": last["inbox_new"],
                    "db_size_kb": last["db_size_kb"],
                    "uptime_hours": round(last["uptime_seconds"] / 3600, 1),
                },
                "warnings": warnings,
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _safe_count(table: str, where: str = "") -> int:
    try:
        with _connect(readonly=True) as db:
            w = f"WHERE {where}" if where else ""
            row = db.execute(f"SELECT COUNT(*) as n FROM {table} {w}").fetchone()
            return row["n"] if row else 0
    except Exception:
        return 0


def _db_size_kb() -> int:
    try:
        from .db import get_db_path
        return _os.path.getsize(get_db_path()) // 1024
    except Exception:
        return 0
