# -*- coding: utf-8 -*-
"""
Event store for Nous Core.

Provides:
  - emit_event(): write an event (fire-and-forget, NEVER throws)
  - get_event():  read one event by ID
  - list_events(): query with filters
  - mark_processed(): mark event as handled

Design: all writes are best-effort side effects. The existing chat/tool
execution flow MUST NOT break if event recording fails.
"""

from __future__ import annotations

import json as _json
import logging as _logging
import sqlite3 as _sqlite3
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.events")


# Write

def emit_event(
    event_type: str,
    source: str = "",
    payload: dict[str, Any] | None = None,
    *,
    session_id: str = "",
    device_id: str = "",
    correlation_id: str = "",
) -> dict[str, Any] | None:
    """
    Write a single event. NEVER raises — returns None on failure.

    This is a side effect that records what happened; it does NOT
    drive business logic. That comes later in P0-2 (dispatcher).
    """
    event_id = _ids.make_evt_id()
    corr_id = correlation_id or _ids.make_corr_id()
    now = _time.utc_now()
    payload_json = _json.dumps(payload or {}, ensure_ascii=False)

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO events (id, type, source, session_id, device_id,
                   payload, correlation_id, created_at, processed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (event_id, event_type, source, session_id, device_id,
                 payload_json, corr_id, now),
            )
        return {
            "id": event_id, "type": event_type, "source": source,
            "session_id": session_id, "device_id": device_id,
            "payload": payload or {}, "correlation_id": corr_id,
            "created_at": now,
        }
    except Exception:
        _log.warning("emit_event failed for %s (non-fatal)", event_type)
        return None


# Read

def get_event(event_id: str) -> dict[str, Any] | None:
    """Read a single event by ID."""
    try:
        with _connect(readonly=True) as db:
            row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return _row_to_dict(row) if row else None
    except Exception:
        return None


def list_events(
    event_type: str = "",
    source: str = "",
    session_id: str = "",
    correlation_id: str = "",
    since: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Query events with optional filters.
    event_type can be a prefix: "device." matches "device.heartbeat".
    """
    limit = max(1, min(limit, 500))
    conds: list[str] = []
    params: list[str] = []

    if event_type:
        if event_type.endswith("."):
            conds.append("type LIKE ?"); params.append(event_type + "%")
        else:
            conds.append("type = ?"); params.append(event_type)
    if source:
        conds.append("source = ?"); params.append(source)
    if session_id:
        conds.append("session_id = ?"); params.append(session_id)
    if correlation_id:
        conds.append("correlation_id = ?"); params.append(correlation_id)
    if since:
        conds.append("created_at > ?"); params.append(since)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    query = f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([str(limit), str(offset)])

    try:
        with _connect(readonly=True) as db:
            return [_row_to_dict(r) for r in db.execute(query, params).fetchall()]
    except Exception:
        return []


def count_events(event_type: str = "") -> int:
    """Count events, optionally filtered by type."""
    try:
        with _connect(readonly=True) as db:
            if event_type:
                row = db.execute("SELECT COUNT(*) as cnt FROM events WHERE type = ?",
                                 (event_type,)).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
            return row["cnt"] if row else 0
    except Exception:
        return 0


def mark_processed(event_id: str) -> bool:
    """Mark an event as processed. Returns True on success."""
    try:
        with _connect() as db:
            db.execute("UPDATE events SET processed = 1 WHERE id = ?", (event_id,))
        return True
    except Exception:
        return False


# helpers

def _row_to_dict(row: _sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["payload"] = _json.loads(d.get("payload", "{}"))
    except (_json.JSONDecodeError, TypeError):
        d["payload"] = {}
    return d
