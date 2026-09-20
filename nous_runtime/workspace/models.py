"""Workspace Runtime models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    owner: str = "local"
    type: str = "project"
    permissions: tuple[str, ...] = ("read", "write")
    context_policy: str = "workspace_only"
    memory_policy: str = "workspace_only"
    active_project: str = ""
    path: str = ""
    created_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("workspace id is required")
        if not self.name:
            raise ValueError("workspace name is required")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permissions"] = list(self.permissions)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            owner=str(data.get("owner") or "local"),
            type=str(data.get("type") or "project"),
            permissions=tuple(data.get("permissions") or ("read", "write")),
            context_policy=str(data.get("context_policy") or "workspace_only"),
            memory_policy=str(data.get("memory_policy") or "workspace_only"),
            active_project=str(data.get("active_project") or ""),
            path=str(data.get("path") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )
