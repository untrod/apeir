# -*- coding: utf-8 -*-
"""
Device Registry — SQLite-backed device management with capability model.

Provides a richer device registry that can run alongside the existing
devices.json (brain_devices.py). During the transition period, this
module syncs from the existing registry via an adapter.

Design:
  - Each device has a stable ID, display name, type, and capabilities.
  - Capabilities use dot-notation: "shell.exec", "screen.screenshot", etc.
  - Heartbeat tracking with online/offline detection.
  - The existing devices.json continues to work — this is additive.

Usage:
  from nous_core.devices import register_device, heartbeat, get_device, list_devices

  register_device("laptop", name="我的电脑", device_type="pc",
                  capabilities=["shell.exec", "screen.screenshot", "desktop.click"])
  heartbeat("laptop")
  dev = get_device("laptop")
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from .. import ids as _ids
from .. import time as _time
from ..db import connect as _connect

_log = _logging.getLogger("nous_core.devices")

# Offline threshold in seconds (matches brain_devices.py)
_OFFLINE_AFTER = 75

# Known capability taxonomy
_STANDARD_CAPABILITIES = {
    # PC
    "shell.exec", "shell.interactive", "shell.sudo",
    "screen.screenshot", "desktop.click", "desktop.type",
    "desktop.hotkey", "desktop.drag", "desktop.scroll",
    "browser.playwright", "browser.tabs",
    "files.read", "files.write", "files.list", "files.watch",
    # Phone
    "phone.accessibility_tree", "phone.tap", "phone.type",
    "phone.scroll", "phone.back", "phone.home",
    "phone.notification_read", "phone.notification_action",
    "phone.screenshot", "phone.app_list", "phone.open_app",
    "phone.share", "phone.clipboard",
    # Watch
    "watch.observe", "watch.act", "watch.notification",
    # Common
    "audio.record", "audio.play",
    "tts.speak", "tts.stream",
    "camera.capture", "camera.stream",
    "location.gps",
    "network.wifi", "network.bluetooth", "network.cellular",
}


# CRUD

def register_device(
    device_id: str,
    *,
    name: str = "",
    device_type: str = "unknown",  # "pc", "phone", "watch", "server", "unknown"
    host: str = "",
    port: int = 0,
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """
    Register or update a device. Idempotent — calling it again
    with the same device_id updates the record.

    Returns True on success.
    """
    caps = _json.dumps(capabilities or [], ensure_ascii=False)
    meta = _json.dumps(metadata or {}, ensure_ascii=False)
    now = _time.utc_now()

    try:
        with _connect() as db:
            existing = db.execute(
                "SELECT id FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if existing:
                db.execute(
                    """UPDATE devices SET name = ?, device_type = ?, host = ?, port = ?,
                       capabilities = ?, metadata = ?, updated_at = ?
                       WHERE id = ?""",
                    (name or device_id, device_type, host, port, caps, meta, now, device_id),
                )
            else:
                db.execute(
                    """INSERT INTO devices (id, name, device_type, host, port,
                       capabilities, metadata, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (device_id, name or device_id, device_type, host, port, caps, meta, now, now),
                )
        _log.debug("Device registered: %s (%s)", device_id, device_type)
        return True
    except Exception as e:
        _log.error("register_device failed for %s: %s", device_id, e)
        return False


def get_device(device_id: str) -> dict[str, Any] | None:
    """Read a single device by ID."""
    try:
        with _connect(readonly=True) as db:
            row = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            return _row_to_device(row) if row else None
    except Exception:
        return None


def list_devices(device_type: str = "", online_only: bool = False) -> list[dict[str, Any]]:
    """List all registered devices, optionally filtered."""
    try:
        with _connect(readonly=True) as db:
            conds = []
            params = []
            if device_type:
                conds.append("device_type = ?"); params.append(device_type)
            if online_only:
                conds.append("is_online = 1")
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = db.execute(
                f"SELECT * FROM devices {where} ORDER BY name ASC", params
            ).fetchall()
            return [_row_to_device(r) for r in rows]
    except Exception:
        return []


def heartbeat(device_id: str) -> bool:
    """Record a device heartbeat — updates last_seen and marks online."""
    now = _time.utc_now()
    try:
        with _connect() as db:
            db.execute(
                "UPDATE devices SET last_seen = ?, last_heartbeat = ?, is_online = 1 "
                "WHERE id = ?",
                (now, now, device_id),
            )
        return True
    except Exception:
        return False


def update_online_status() -> int:
    """
    Scan all devices and update is_online based on last_seen age.
    Called periodically by the dispatcher.

    Returns the number of devices whose status changed.
    """
    now_epoch = _time.utc_now_epoch()
    changed = 0
    try:
        with _connect() as db:
            rows = db.execute(
                "SELECT id, last_seen, is_online FROM devices WHERE last_seen != ''"
            ).fetchall()
            for row in rows:
                last = _time.parse_iso(row["last_seen"])
                online = last > 0 and (now_epoch - last) < _OFFLINE_AFTER
                if bool(row["is_online"]) != online:
                    db.execute(
                        "UPDATE devices SET is_online = ? WHERE id = ?",
                        (1 if online else 0, row["id"]),
                    )
                    changed += 1
        if changed:
            _log.debug("Updated online status for %d devices", changed)
    except Exception as e:
        _log.warning("update_online_status: %s", e)
    return changed


def has_capability(device_id: str, capability: str) -> bool:
    """Check if a device has a specific capability."""
    dev = get_device(device_id)
    if not dev:
        return False
    return capability in (dev.get("capabilities") or [])


def find_device_by_capability(capability: str) -> list[dict[str, Any]]:
    """Find all online devices that have a specific capability."""
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM devices WHERE is_online = 1 "
                "AND capabilities LIKE ?",
                (f"%\"{capability}\"%",),
            ).fetchall()
            return [_row_to_device(r) for r in rows]
    except Exception:
        return []


def delete_device(device_id: str) -> bool:
    """Remove a device from the registry."""
    try:
        with _connect() as db:
            db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        return True
    except Exception:
        return False


# Adapter: sync from existing devices.json

def sync_from_legacy(legacy_devices: dict[str, dict]) -> int:
    """
    Import devices from the existing brain_devices.devices dict.

    Maps the old fields:
      name → name
      host → host
      port → port
      os → device_type (windows→pc, android→phone, wearos→watch)
      capabilities → capabilities (if present, else derived from os)

    Returns the number of devices synced.
    """
    os_to_type = {"windows": "pc", "linux": "server", "android": "phone", "wearos": "watch"}
    count = 0
    for did, dev in legacy_devices.items():
        dtype = os_to_type.get((dev.get("os") or "").lower(), "unknown")
        caps = list(dev.get("capabilities") or [])
        # Derive capabilities from device type if not explicitly set
        if not caps and dtype == "pc":
            caps = ["shell.exec", "screen.screenshot", "files.read", "files.write"]
        elif not caps and dtype == "phone":
            caps = ["phone.accessibility_tree", "phone.tap", "phone.screenshot", "audio.record", "tts.speak"]
        elif not caps and dtype == "watch":
            caps = ["watch.observe", "audio.record", "tts.speak"]

        register_device(
            did,
            name=dev.get("name", did),
            device_type=dtype,
            host=str(dev.get("host", "")),
            port=int(dev.get("port", 0)),
            capabilities=caps,
            metadata={"os": dev.get("os", ""), "default_cwd": dev.get("default_cwd", "")},
        )
        count += 1

    _log.info("Synced %d devices from legacy devices.json", count)
    return count


# Helpers

def _row_to_device(row) -> dict[str, Any]:
    d = dict(row)
    for field in ("capabilities", "metadata"):
        try:
            d[field] = _json.loads(d.get(field, "[]" if field == "capabilities" else "{}"))
        except (_json.JSONDecodeError, TypeError):
            d[field] = [] if field == "capabilities" else {}
    d["is_online"] = bool(d.get("is_online", 0))
    return d
