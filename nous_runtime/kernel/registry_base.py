# -*- coding: utf-8 -*-
"""
Unified Registry base class for all Nous Runtime registries.

Replaces 22 independent registry implementations with a single,
well-tested base that provides:

- Standard CRUD (register, get, list, unregister, update)
- Thread-safe operations
- Consistent error handling with NousResult
- Audit trail via append-only event log
- Health aggregation
- Serialization (to_dict / to_json)

Usage:
    from nous_runtime.kernel.registry_base import RegistryBase
    from nous_runtime.kernel.node import Node

    class NodeRegistry(RegistryBase[Node]):
        object_kind = "Node"
        object_type = Node
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.object_model import Health, NousObject
from nous_runtime.compat.ids import make_id

T = TypeVar("T", bound=NousObject)


# Registry event (immutable audit trail)

@dataclass
class RegistryEvent:
    """Immutable record of a registry mutation."""

    event_id: str = field(default_factory=lambda: make_id(prefix="regev"))
    action: str = ""                     # register, unregister, update, get, list
    object_id: str = ""
    object_kind: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "object_id": self.object_id,
            "object_kind": self.object_kind,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
        }


# Registry base

@dataclass
class RegistryBase(Generic[T]):
    """Thread-safe, generic registry for NousObject subclasses.

    Subclasses must set:
        object_kind: str   — e.g., "Node", "Provider", "Agent"
        object_type: type  — The NousObject subclass
    """

    object_kind: str = field(default="", init=False)
    object_type: type = field(default=NousObject, init=False)

    # Internal storage
    _items: dict[str, T] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    # Audit trail
    _events: list[RegistryEvent] = field(default_factory=list, init=False)
    _max_events: int = field(default=10000, init=False)

    # CRUD

    def register(self, obj: T, trace_id: str = "") -> NousResult[T]:
        """Register a new object. Returns ALREADY_EXISTS if ID is taken."""
        with self._lock:
            obj_id = obj.metadata.id
            if obj_id in self._items:
                return NousResult.err(
                    ErrorCode.ALREADY_EXISTS,
                    message=f"{self.object_kind} '{obj_id}' already registered",
                    details={"object_id": obj_id},
                )

            # Ensure kind is set
            if not obj.metadata.kind:
                obj.metadata.kind = self.object_kind

            self._items[obj_id] = obj
            self._record_event("register", obj_id, trace_id)
            return NousResult.ok(obj)

    def get(self, obj_id: str) -> NousResult[T]:
        """Retrieve an object by ID."""
        with self._lock:
            obj = self._items.get(obj_id)
            if obj is None:
                return NousResult.err(
                    ErrorCode.NOT_FOUND,
                    message=f"{self.object_kind} '{obj_id}' not found",
                )
            return NousResult.ok(obj)

    def list(self, filter_fn=None) -> NousResult[list[T]]:
        """List all objects, optionally filtered."""
        with self._lock:
            items = list(self._items.values())
            if filter_fn is not None:
                items = [o for o in items if filter_fn(o)]
            return NousResult.ok(items)

    def unregister(self, obj_id: str, trace_id: str = "") -> NousResult[None]:
        """Remove an object from the registry."""
        with self._lock:
            if obj_id not in self._items:
                return NousResult.err(
                    ErrorCode.NOT_FOUND,
                    message=f"{self.object_kind} '{obj_id}' not found",
                )
            del self._items[obj_id]
            self._record_event("unregister", obj_id, trace_id)
            return NousResult.ok(None)

    def update(self, obj_id: str, update_fn, trace_id: str = "") -> NousResult[T]:
        """Atomically update an object.

        Args:
            obj_id: Object to update
            update_fn: Callable[T, T] — receives current object, returns updated
            trace_id: Optional trace context
        """
        with self._lock:
            obj = self._items.get(obj_id)
            if obj is None:
                return NousResult.err(
                    ErrorCode.NOT_FOUND,
                    message=f"{self.object_kind} '{obj_id}' not found",
                )
            try:
                updated = update_fn(obj)
                if updated is not None:
                    self._items[obj_id] = updated
                self._record_event("update", obj_id, trace_id)
                return NousResult.ok(self._items[obj_id])
            except Exception as e:
                return NousResult.err(
                    ErrorCode.INTERNAL,
                    message=f"Update failed: {e}",
                )

    def count(self) -> int:
        """Return the number of registered objects."""
        with self._lock:
            return len(self._items)

    # Health

    def health(self) -> NousResult[dict[str, Any]]:
        """Aggregate health of all registered objects."""
        with self._lock:
            items = list(self._items.values())
            if not items:
                return NousResult.ok({
                    "object_kind": self.object_kind,
                    "count": 0,
                    "health": Health.UNKNOWN.value,
                })

            health_counts = {h.value: 0 for h in Health}
            for obj in items:
                hv = obj.health.value if hasattr(obj.health, 'value') else str(obj.health)
                health_counts[hv] = health_counts.get(hv, 0) + 1

            # Aggregate: if any DOWN → DOWN, if any DEGRADED → DEGRADED, else OK
            if health_counts.get("down", 0) > 0:
                agg = Health.DOWN
            elif health_counts.get("degraded", 0) > 0:
                agg = Health.DEGRADED
            elif health_counts.get("unknown", 0) == len(items):
                agg = Health.UNKNOWN
            else:
                agg = Health.OK

            return NousResult.ok({
                "object_kind": self.object_kind,
                "count": len(items),
                "health": agg.value,
                "breakdown": health_counts,
            })

    # Audit

    def _record_event(self, action: str, object_id: str, trace_id: str) -> None:
        event = RegistryEvent(
            action=action,
            object_id=object_id,
            object_kind=self.object_kind,
            trace_id=trace_id,
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent audit events."""
        with self._lock:
            return [e.to_dict() for e in self._events[-limit:]]

    def get_event_count(self) -> int:
        return len(self._events)

    # Bulk operations

    def register_all(self, objects: list[T], trace_id: str = "") -> NousResult[list[T]]:
        """Register multiple objects. Skips duplicates without failing."""
        registered = []
        for obj in objects:
            result = self.register(obj, trace_id=trace_id)
            if result.ok:
                registered.append(result.value)
        return NousResult.ok(registered)

    def to_dict(self) -> dict[str, Any]:
        """Serialize entire registry."""
        with self._lock:
            return {
                "object_kind": self.object_kind,
                "count": len(self._items),
                "items": {obj_id: obj.to_dict() for obj_id, obj in self._items.items()},
            }

    def clear(self) -> None:
        """Remove all objects. Use with caution."""
        with self._lock:
            self._items.clear()
            self._events.clear()
