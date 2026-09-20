"""Unified Runtime response model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeResponse:
    request_id: str
    status: str
    message: str
    intent: str = ""
    workspace: str = ""
    trace_id: str = ""
    requires_confirmation: bool = False
    result: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = list(self.errors)
        return data
