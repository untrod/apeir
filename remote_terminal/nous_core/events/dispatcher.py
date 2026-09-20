# -*- coding: utf-8 -*-
"""
Event Dispatcher — polls unprocessed events and runs registered handlers.

Design:
  - Runs as a background daemon thread.
  - Polls events WHERE processed=0, ordered by created_at ASC.
  - For each event, finds matching handlers and calls them in registration order.
  - An event is marked processed when ALL matching handlers succeed (return True).
    If any handler fails (returns False or raises), the event stays unprocessed
    for retry on next poll cycle (at-least-once semantics).

Usage:
  from nous_core.events.dispatcher import register_handler, start_dispatcher

  def my_handler(event: dict) -> bool:
      # do something with event, return True on success
      return True

  register_handler("device.*", my_handler, name="device-watcher")
  start_dispatcher(interval=5.0)  # polls every 5 seconds
"""

from __future__ import annotations

import fnmatch as _fnmatch
import logging as _logging
import threading as _threading
from typing import Any, Callable

from ..db import connect as _connect
from ..time import utc_now as _utc_now

_log = _logging.getLogger("nous_core.dispatcher")

# Handler type: callable(event_dict) -> bool
HandlerFn = Callable[[dict[str, Any]], bool]


# Handler Registry

class _HandlerEntry:
    __slots__ = ("pattern", "fn", "name", "registered_at")

    def __init__(self, pattern: str, fn: HandlerFn, name: str = ""):
        self.pattern = pattern      # e.g. "device.*", "chat.*", "tool.executed"
        self.fn = fn                # callable
        self.name = name or fn.__name__
        self.registered_at = _utc_now()


_registry: list[_HandlerEntry] = []
_registry_lock = _threading.Lock()


def register_handler(pattern: str, fn: HandlerFn, name: str = "") -> _HandlerEntry:
    """
    Register a handler for events matching `pattern`.

    Patterns support fnmatch wildcards:
      - "device.*" matches device.heartbeat, device.online, device.offline
      - "tool.confirmation_required" matches exactly that type
      - "*" matches ALL events (use sparingly)

    Handlers are called in registration order. The first handler to
    fail (return False) stops the chain — the event stays unprocessed.

    Returns the handler entry (can be used to unregister later).
    """
    entry = _HandlerEntry(pattern, fn, name)
    with _registry_lock:
        _registry.append(entry)
    _log.info("Registered handler '%s' for pattern '%s'", entry.name, pattern)
    return entry


def unregister_handler(entry: _HandlerEntry) -> bool:
    """Remove a previously registered handler. Returns True if found and removed."""
    with _registry_lock:
        try:
            _registry.remove(entry)
            _log.info("Unregistered handler '%s'", entry.name)
            return True
        except ValueError:
            return False


def _match(event_type: str, pattern: str) -> bool:
    """Check if an event type matches a handler pattern."""
    return _fnmatch.fnmatch(event_type, pattern)


# Dispatcher Engine

def _get_pending_events(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch unprocessed events, oldest first."""
    try:
        with _connect(readonly=True) as db:
            rows = db.execute(
                "SELECT * FROM events WHERE processed = 0 "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                try:
                    import json
                    d["payload"] = json.loads(d.get("payload", "{}"))
                except Exception:
                    d["payload"] = {}
                result.append(d)
            return result
    except Exception as e:
        _log.warning("Failed to fetch pending events: %s", e)
        return []


def _mark_event_processed(event_id: str) -> bool:
    """Mark a single event as processed."""
    try:
        with _connect() as db:
            db.execute("UPDATE events SET processed = 1 WHERE id = ?", (event_id,))
        return True
    except Exception as e:
        _log.warning("Failed to mark event %s as processed: %s", event_id, e)
        return False


def _dispatch_event(event: dict[str, Any]) -> bool:
    """
    Run all matching handlers for a single event.
    Returns True if ALL matching handlers succeed.
    """
    event_type = event.get("type", "")
    with _registry_lock:
        handlers = [entry for entry in _registry if _match(event_type, entry.pattern)]

    if not handlers:
        # No handler interested in this event type — mark processed to clear queue
        return True

    all_ok = True
    for entry in handlers:
        try:
            ok = entry.fn(event)
            if not ok:
                _log.warning("Handler '%s' returned False for event %s (%s)",
                             entry.name, event.get("id", "?"), event_type)
                all_ok = False
                break  # stop on first failure (preserve ordering)
        except Exception as e:
            _log.error("Handler '%s' raised %s for event %s: %s",
                       entry.name, type(e).__name__, event.get("id", "?"), e)
            all_ok = False
            break

    return all_ok


def dispatch_once(limit: int = 50) -> int:
    """
    Process one batch of pending events. Call this from your own loop
    if you don't want the built-in daemon thread.

    Returns the number of events processed successfully.
    """
    events = _get_pending_events(limit)
    if not events:
        return 0

    count = 0
    for event in events:
        if _dispatch_event(event):
            _mark_event_processed(event["id"])
            count += 1

    if count > 0:
        _log.debug("Dispatched %d/%d events successfully", count, len(events))
    return count


# Background Dispatcher Thread

_dispatcher_thread: _threading.Thread | None = None
_dispatcher_stop: _threading.Event | None = None


def _dispatcher_loop(interval: float):
    """Background loop: poll + dispatch at fixed interval."""
    _log.info("Event dispatcher started (interval=%.1fs)", interval)
    while not _dispatcher_stop.is_set():
        try:
            n = dispatch_once()
            if n > 0:
                _log.debug("Dispatched %d events", n)
        except Exception as e:
            _log.error("Dispatcher loop error: %s", e)

        # Wait with periodic wake-up for clean shutdown
        _dispatcher_stop.wait(interval)

    _log.info("Event dispatcher stopped")


def start_dispatcher(interval: float = 5.0) -> _threading.Thread:
    """
    Start the background event dispatcher daemon thread.

    Args:
        interval: seconds between poll cycles (default 5s).

    Returns the thread object. The thread stops automatically when
    the process exits (daemon=True).

    Safe to call multiple times — if already running, returns the
    existing thread.
    """
    global _dispatcher_thread, _dispatcher_stop

    if _dispatcher_thread and _dispatcher_thread.is_alive():
        _log.warning("Dispatcher already running")
        return _dispatcher_thread

    _dispatcher_stop = _threading.Event()
    _dispatcher_thread = _threading.Thread(
        target=_dispatcher_loop,
        args=(interval,),
        daemon=True,
        name="nous-core-dispatcher",
    )
    _dispatcher_thread.start()
    return _dispatcher_thread


def stop_dispatcher(timeout: float = 10.0):
    """Signal the dispatcher thread to stop and wait for it."""
    global _dispatcher_stop, _dispatcher_thread
    if _dispatcher_stop:
        _dispatcher_stop.set()
    if _dispatcher_thread and _dispatcher_thread.is_alive():
        _dispatcher_thread.join(timeout=timeout)
        _dispatcher_thread = None
    _dispatcher_stop = None


# Built-in Handlers

def _log_event_handler(event: dict[str, Any]) -> bool:
    """Built-in handler: logs every dispatched event at DEBUG level."""
    _log.debug("Event: %s (src=%s, sid=%s, corr=%s)",
               event.get("type", "?"),
               event.get("source", "?"),
               event.get("session_id", "")[:8] or "-",
               event.get("correlation_id", "")[:8] or "-")
    return True


def _heartbeat_pruner(event: dict[str, Any]) -> bool:
    """
    Built-in handler: keeps device.heartbeat events from piling up.
    Deletes heartbeat events older than 24 hours after processing.
    """
    event_type = event.get("type", "")
    if event_type not in ("device.heartbeat",):
        return True  # not our concern — let other handlers run

    try:
        with _connect() as db:
            db.execute(
                "DELETE FROM events WHERE type = 'device.heartbeat' "
                "AND created_at < datetime('now', '-1 day')"
            )
    except Exception:
        pass
    return True


def register_builtin_handlers():
    """Register the standard built-in handlers. Idempotent — safe to call again."""
    # Check if already registered
    with _registry_lock:
        names = {e.name for e in _registry}
    if "_log_all" not in names:
        register_handler("*", _log_event_handler, name="_log_all")
    if "_heartbeat_pruner" not in names:
        register_handler("device.heartbeat", _heartbeat_pruner, name="_heartbeat_pruner")
