"""Runtime trace records for end-to-end observability."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TraceEntry:
    stage: str
    result: str
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeTrace:
    request_id: str
    trace_id: str = ""
    entries: list[TraceEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.trace_id:
            self.trace_id = hashlib.sha256(f"trace:{self.request_id}".encode("utf-8")).hexdigest()[:16]

    def add(self, stage: str, result: str, *, reason: str = "", data: dict[str, Any] | None = None) -> TraceEntry:
        entry = TraceEntry(stage=stage, result=result, reason=reason, data=data or {})
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }
