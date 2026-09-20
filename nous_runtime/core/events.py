"""Generic event envelope shared across Runtime foundation domains."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass
class EventEnvelope:
    """Stable, domain-neutral Runtime event representation."""

    event_id: str = field(default_factory=_event_id)
    event_type: str = ""
    source: str = "runtime"
    timestamp: str = field(default_factory=_timestamp)
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached dictionary suitable for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventEnvelope":
        """Build an envelope while accepting common legacy field aliases."""
        return cls(
            event_id=str(data.get("event_id") or data.get("id") or _event_id()),
            event_type=str(data.get("event_type") or data.get("type") or ""),
            source=str(data.get("source") or data.get("actor") or "runtime"),
            timestamp=str(data.get("timestamp") or _timestamp()),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["EventEnvelope"]
