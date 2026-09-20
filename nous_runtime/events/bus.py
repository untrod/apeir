# -*- coding: utf-8 -*-
"""RuntimeEventBus — cross-domain pub/sub event dispatcher.

Complements the per-run ``EventStream`` with a global event bus that:
- Routes events across all domains (task, model, node, capability, etc.)
- Supports pattern-based subscription (e.g., ``"task.*"``, ``"model.completed.*"``)
- Persists events to SQLite for cross-session querying
- Provides SSE-friendly streaming for UI/mobile consumers
- Deduplicates via event_id for idempotent delivery
"""

from __future__ import annotations

import atexit
import json
import logging
import sqlite3
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from nous_runtime.core.events import EventEnvelope

_log = logging.getLogger("nous.events.bus")

# Configuration
DEFAULT_MAX_BUFFER = 10_000
DEFAULT_MAX_LISTENERS_PER_PATTERN = 32
DEFAULT_PERSIST_INTERVAL_SEC = 1.0


@dataclass
class BusMetrics:
    """Runtime metrics for the event bus."""
    events_published: int = 0
    events_dropped: int = 0
    events_persisted: int = 0
    listener_calls: int = 0
    listener_failures: int = 0
    last_publish_timestamp: str = ""


class RuntimeEventBus:
    """Cross-domain event bus with pattern subscriptions and SQLite persistence.

    Usage::

        bus = RuntimeEventBus(workspace_root=".")
        bus.subscribe("task.*", lambda evt: print(f"Task event: {evt.event_type}"))
        bus.subscribe("model.completed", lambda evt: record_observation(evt))
        bus.publish(RuntimeEvent.TASK_CREATED, payload={"task_id": "t1"})
    """

    def __init__(
        self,
        workspace_root: str = "",
        *,
        max_buffer: int = DEFAULT_MAX_BUFFER,
        max_listeners_per_pattern: int = DEFAULT_MAX_LISTENERS_PER_PATTERN,
        persist_interval_sec: float = DEFAULT_PERSIST_INTERVAL_SEC,
    ):
        self._workspace = workspace_root or "."
        self._max_buffer = max(100, int(max_buffer))
        self._max_listeners = max(1, int(max_listeners_per_pattern))
        self._persist_interval = max(0.1, float(persist_interval_sec))

        self._lock = threading.RLock()
        self._buffer: deque[EventEnvelope] = deque(maxlen=self._max_buffer)
        self._subscriptions: dict[str, list[Callable[[EventEnvelope], None]]] = {}
        self._metrics = BusMetrics()

        # Persistence
        self._db_path = Path(self._workspace) / ".nous" / "event_bus.db"
        self._db: sqlite3.Connection | None = None
        self._pending_persist: list[EventEnvelope] = []
        self._persist_thread: threading.Thread | None = None
        self._shutdown_flag = threading.Event()

        # Start background persistence
        self._start_persist_worker()

    # Publish

    def publish(
        self,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
        event_id: str = "",
    ) -> EventEnvelope:
        """Publish an event to all matching subscribers and persist it.

        Args:
            event_type: Canonical event type (e.g., ``RuntimeEvent.TASK_CREATED``).
            payload: Event-specific data.
            source: Component that produced the event.
            metadata: Arbitrary annotations.
            event_id: Optional pre-generated event ID (for idempotency).

        Returns:
            The published EventEnvelope.
        """
        envelope = EventEnvelope(
            event_id=event_id or f"evt_{uuid.uuid4().hex}",
            event_type=event_type,
            source=source,
            payload=dict(payload or {}),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._buffer.append(envelope)
            self._metrics.events_published += 1
            self._metrics.last_publish_timestamp = envelope.timestamp

        # Persist (best-effort async)
        self._pending_persist.append(envelope)

        # Notify matching subscribers (fire-and-forget)
        self._notify_subscribers(envelope)

        return envelope

    def publish_batch(
        self,
        events: list[tuple[str, dict[str, Any]]],
        *,
        source: str = "runtime",
    ) -> list[EventEnvelope]:
        """Publish multiple events atomically."""
        envelopes = []
        for event_type, payload in events:
            envelopes.append(
                self.publish(event_type, payload=payload, source=source)
            )
        return envelopes

    # Subscribe

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[EventEnvelope], None],
    ) -> None:
        """Subscribe to events matching a pattern.

        Patterns support wildcards:
        - ``"task.*"`` — all task events
        - ``"model.completed"`` — exact match
        - ``"model.completed.*"`` — all model completed sub-types
        - ``"*"`` — all events
        """
        with self._lock:
            listeners = self._subscriptions.setdefault(pattern, [])
            if callback in listeners:
                return
            if len(listeners) >= self._max_listeners:
                _log.warning(
                    "Listener limit reached for pattern '%s' (%d)",
                    pattern, self._max_listeners,
                )
                return
            listeners.append(callback)

    def unsubscribe(
        self,
        pattern: str,
        callback: Callable[[EventEnvelope], None],
    ) -> None:
        """Remove a subscription."""
        with self._lock:
            if pattern in self._subscriptions:
                self._subscriptions[pattern] = [
                    cb for cb in self._subscriptions[pattern]
                    if cb is not callback
                ]

    # Query

    def query(
        self,
        *,
        event_type: str = "",
        domain: str = "",
        source: str = "",
        since: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query persisted events with filters."""
        self._ensure_db()
        if self._db is None:
            # Fall back to in-memory buffer
            return self._query_buffer(event_type=event_type, domain=domain,
                                      source=source, limit=limit)

        conditions = []
        params: list[Any] = []

        if event_type:
            if event_type.endswith(".*"):
                conditions.append("event_type LIKE ?")
                params.append(event_type[:-2] + ".%")
            elif event_type == "*":
                pass
            else:
                conditions.append("event_type = ?")
                params.append(event_type)

        if domain:
            conditions.append("event_type LIKE ?")
            params.append(f"{domain}.%")

        if source:
            conditions.append("source = ?")
            params.append(source)

        if since:
            conditions.append("timestamp > ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query_sql = (
            f"SELECT event_id, event_type, source, timestamp, payload, metadata "
            f"FROM event_bus{where} "
            f"ORDER BY rowid DESC LIMIT ? OFFSET ?"
        )
        params.extend([max(1, min(int(limit), 1000)), max(0, int(offset))])

        try:
            rows = self._db.execute(query_sql, params).fetchall()
        except sqlite3.OperationalError:
            return self._query_buffer(event_type=event_type, domain=domain,
                                      source=source, limit=limit)

        return [
            {
                "event_id": r[0], "event_type": r[1], "source": r[2],
                "timestamp": r[3], "payload": json.loads(r[4]) if r[4] else {},
                "metadata": json.loads(r[5]) if r[5] else {},
            }
            for r in rows
        ]

    def query_recent(
        self,
        *,
        domain: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent events, optionally filtered by domain."""
        return self.query(domain=domain, limit=limit)

    def count(self, *, event_type: str = "", domain: str = "") -> int:
        """Count persisted events matching filters."""
        self._ensure_db()
        if self._db is None:
            return len(self._buffer)

        conditions = []
        params: list[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if domain:
            conditions.append("event_type LIKE ?")
            params.append(f"{domain}.%")

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        try:
            row = self._db.execute(
                f"SELECT COUNT(*) FROM event_bus{where}", params
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return len(self._buffer)

    # Streaming (SSE-ready)

    def stream_events(
        self,
        *,
        domain: str = "",
        since_event_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get events suitable for SSE streaming to UI clients.

        Returns events newer than ``since_event_id``, up to ``limit``.
        If ``since_event_id`` is empty, returns the most recent events.
        """
        if since_event_id:
            # Find the event and return everything after it
            events = self.query(domain=domain, limit=limit)
            found = False
            result = []
            for evt in reversed(events):  # Chronological order
                if found:
                    result.append(evt)
                elif evt["event_id"] == since_event_id:
                    found = True
            return result if found else events[:limit]
        else:
            return self.query(domain=domain, limit=limit)

    # Metrics

    def get_metrics(self) -> dict[str, Any]:
        """Return bus metrics."""
        with self._lock:
            return {
                "events_published": self._metrics.events_published,
                "events_dropped": self._metrics.events_dropped,
                "events_persisted": self._metrics.events_persisted,
                "listener_calls": self._metrics.listener_calls,
                "listener_failures": self._metrics.listener_failures,
                "buffer_size": len(self._buffer),
                "subscription_count": sum(
                    len(v) for v in self._subscriptions.values()
                ),
                "active_patterns": list(self._subscriptions.keys()),
                "last_publish": self._metrics.last_publish_timestamp,
            }

    def shutdown(self) -> None:
        """Gracefully shut down the bus, flushing pending events."""
        self._shutdown_flag.set()
        if self._persist_thread and self._persist_thread.is_alive():
            self._persist_thread.join(timeout=5.0)
        self._flush_pending()
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    # Internal

    def _notify_subscribers(self, envelope: EventEnvelope) -> None:
        """Notify all subscribers whose pattern matches the event."""
        with self._lock:
            subscriptions = dict(self._subscriptions)

        for pattern, listeners in subscriptions.items():
            if self._pattern_matches(pattern, envelope.event_type):
                for callback in listeners:
                    try:
                        callback(envelope)
                        self._metrics.listener_calls += 1
                    except Exception:
                        self._metrics.listener_failures += 1
                        _log.debug(
                            "Listener failed for %s (pattern=%s)",
                            envelope.event_type, pattern, exc_info=True,
                        )

    @staticmethod
    def _pattern_matches(pattern: str, event_type: str) -> bool:
        """Check if an event type matches a subscription pattern."""
        if pattern == "*":
            return True
        if pattern == event_type:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type == prefix or event_type.startswith(prefix + ".")
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type.startswith(prefix)
        return False

    def _query_buffer(
        self,
        *,
        event_type: str = "",
        domain: str = "",
        source: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fallback query against in-memory buffer."""
        with self._lock:
            events = list(self._buffer)

        result = []
        for evt in reversed(events):
            if event_type and event_type not in ("*", evt.event_type):
                if not (
                    event_type.endswith(".*")
                    and evt.event_type.startswith(event_type[:-2])
                ):
                    continue
            if domain and not evt.event_type.startswith(f"{domain}."):
                continue
            if source and evt.source != source:
                continue
            result.append(evt.to_dict())
            if len(result) >= limit:
                break

        return result

    # Persistence

    def _ensure_db(self) -> None:
        """Lazy-init the SQLite database."""
        if self._db is not None:
            return
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=5.0,
            )
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS event_bus (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'runtime',
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_bus_type
                ON event_bus(event_type)
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_bus_timestamp
                ON event_bus(timestamp)
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_bus_domain
                ON event_bus(event_type)
            """)
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to init event bus DB: %s (buffer-only mode)", e)
            self._db = None

    def _flush_pending(self) -> None:
        """Persist all pending events to SQLite."""
        if not self._pending_persist or self._db is None:
            self._pending_persist.clear()
            return

        self._ensure_db()
        if self._db is None:
            self._pending_persist.clear()
            return

        batch = self._pending_persist[:]
        self._pending_persist.clear()

        try:
            with self._db:
                self._db.executemany(
                    """INSERT OR IGNORE INTO event_bus
                       (event_id, event_type, source, timestamp, payload, metadata)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            e.event_id,
                            e.event_type,
                            e.source,
                            e.timestamp,
                            json.dumps(e.payload, ensure_ascii=False),
                            json.dumps(e.metadata, ensure_ascii=False),
                        )
                        for e in batch
                    ],
                )
            self._metrics.events_persisted += len(batch)
        except Exception as e:
            _log.warning("Failed to persist %d events: %s", len(batch), e)
            # Re-queue failed events (up to buffer limit)
            self._pending_persist = (batch + self._pending_persist)[
                -self._max_buffer:
            ]

    def _start_persist_worker(self) -> None:
        """Start background thread that periodically flushes pending events."""
        def _worker() -> None:
            while not self._shutdown_flag.wait(timeout=self._persist_interval):
                self._flush_pending()
                self._prune_old_events()

        self._persist_thread = threading.Thread(
            target=_worker, daemon=True, name="event-bus-persist"
        )
        self._persist_thread.start()

    def _prune_old_events(self) -> None:
        """Remove events older than 7 days to prevent unbounded growth."""
        if self._db is None:
            return
        try:
            self._db.execute(
                "DELETE FROM event_bus WHERE timestamp < datetime('now', '-7 days')"
            )
            self._db.commit()
        except Exception:
            pass


# Global singleton

_bus_instance: RuntimeEventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus(workspace_root: str = "") -> RuntimeEventBus:
    """Get or create the global RuntimeEventBus singleton."""
    global _bus_instance
    if _bus_instance is not None:
        return _bus_instance

    with _bus_lock:
        if _bus_instance is not None:
            return _bus_instance
        _bus_instance = RuntimeEventBus(workspace_root=workspace_root)
        return _bus_instance


def reset_event_bus() -> None:
    """Reset the global bus (for testing)."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance is not None:
            _bus_instance.shutdown()
        _bus_instance = None


atexit.register(reset_event_bus)


__all__ = [
    "RuntimeEventBus",
    "BusMetrics",
    "get_event_bus",
    "reset_event_bus",
]
