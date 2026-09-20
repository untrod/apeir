# -*- coding: utf-8 -*-
"""
Notification Center — unified notification interface.

Provides a single abstraction for delivering notifications to clients
regardless of delivery channel (SSE, polling, future push).

Design:
  - Notifications are stored in the `notifications` table.
  - Each notification has a target (client_id, session_id, or broadcast).
  - Delivery is channel-agnostic: the same API call works whether the
    client polls or receives SSE events.
  - Unread count tracking per client/session.

Usage:
  from nous_core.notifications import notify, get_unread, mark_read

  # Send a notification to a specific client
  notify("tool.confirmation_required", target_client="phone",
         title="确认操作", body="是否执行 rm -rf /?", data={"confirmation_id": "xxx"})

  # Client polls for unread notifications
  unread = get_unread(target_client="phone", limit=20)

  # Mark as read
  mark_read(notification_id)
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.notifications")


# CRUD

def notify(
    ntype: str,
    *,
    title: str = "",
    body: str = "",
    target_client: str = "",     # "phone", "watch", "laptop" — empty = broadcast
    target_session: str = "",    # optional session-scoping
    data: dict[str, Any] | None = None,
    priority: int = 0,           # 0=normal, 1=high, 2=urgent
    ttl_sec: int = 86400,        # auto-expire after N seconds (default 24h)
) -> str:
    """
    Create and store a notification. Returns the notification ID.

    The notification is immediately available for polling.
    TTL auto-cleanup happens when get_unread() is called.
    """
    nid = _ids.make_ntf_id()
    now = _time.utc_now()
    data_json = _json.dumps(data or {}, ensure_ascii=False)

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO notifications (id, type, title, body,
                   target_client, target_session, data, priority, ttl_sec, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, ntype, title, body, target_client, target_session,
                 data_json, priority, ttl_sec, now),
            )
        _log.debug("Notification %s created: %s → %s", nid, ntype,
                   target_client or "broadcast")
        return nid
    except Exception as e:
        _log.error("notify failed: %s", e)
        return ""


def get_unread(
    *,
    target_client: str = "",
    target_session: str = "",
    since: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Get unread notifications for a client/session.

    Automatically cleans up expired notifications (past TTL).
    """
    now = _time.utc_now()
    limit = max(1, min(limit, 100))

    # Clean up expired notifications
    _purge_expired()

    try:
        with _connect(readonly=True) as db:
            conds = ["read_at = ''"]
            params: list[Any] = []

            if target_client:
                conds.append("(target_client = ? OR target_client = '')")
                params.append(target_client)
            if target_session:
                conds.append("(target_session = ? OR target_session = '')")
                params.append(target_session)
            if since:
                conds.append("created_at > ?")
                params.append(since)

            where = "WHERE " + " AND ".join(conds)
            query = ("SELECT * FROM notifications " + where +
                     " ORDER BY priority DESC, created_at DESC LIMIT ?")
            params.append(limit)

            rows = db.execute(query, params).fetchall()
            return [_row_to_notif(r) for r in rows]
    except Exception as e:
        _log.warning("get_unread: %s", e)
        return []


def count_unread(target_client: str = "", target_session: str = "") -> int:
    """Count unread notifications for a client/session."""
    _purge_expired()
    try:
        with _connect(readonly=True) as db:
            conds = ["read_at = ''"]
            params = []
            if target_client:
                conds.append("(target_client = ? OR target_client = '')")
                params.append(target_client)
            if target_session:
                conds.append("(target_session = ? OR target_session = '')")
                params.append(target_session)
            where = "WHERE " + " AND ".join(conds)
            row = db.execute(
                f"SELECT COUNT(*) as cnt FROM notifications {where}", params
            ).fetchone()
            return row["cnt"] if row else 0
    except Exception:
        return 0


def mark_read(notification_id: str) -> bool:
    """Mark a single notification as read."""
    now = _time.utc_now()
    try:
        with _connect() as db:
            db.execute(
                "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at = ''",
                (now, notification_id),
            )
        return True
    except Exception:
        return False


def mark_all_read(target_client: str = "", target_session: str = "") -> int:
    """Mark all unread notifications for a client/session as read. Returns count."""
    now = _time.utc_now()
    try:
        with _connect() as db:
            conds = ["read_at = ''"]
            params = [now]
            if target_client:
                conds.append("(target_client = ? OR target_client = '')")
                params.append(target_client)
            if target_session:
                conds.append("(target_session = ? OR target_session = '')")
                params.append(target_session)
            where = "WHERE " + " AND ".join(conds)
            cur = db.execute(
                f"UPDATE notifications SET read_at = ? {where}", params
            )
            return cur.rowcount
    except Exception:
        return 0


def _purge_expired() -> int:
    """Delete notifications past their TTL. Called automatically by get_unread."""
    now = _time.utc_now_epoch()
    try:
        with _connect() as db:
            rows = db.execute(
                "SELECT id, created_at, ttl_sec FROM notifications WHERE read_at = ''"
            ).fetchall()
            to_delete = []
            for row in rows:
                created = _time.parse_iso(row["created_at"])
                ttl = row["ttl_sec"]
                if created > 0 and ttl > 0 and (now - created) > ttl:
                    to_delete.append(row["id"])
            for nid in to_delete:
                db.execute("DELETE FROM notifications WHERE id = ?", (nid,))
            if to_delete:
                _log.debug("Purged %d expired notifications", len(to_delete))
            return len(to_delete)
    except Exception:
        return 0


# Helpers

def _row_to_notif(row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["data"] = _json.loads(d.get("data", "{}"))
    except (_json.JSONDecodeError, TypeError):
        d["data"] = {}
    return d
