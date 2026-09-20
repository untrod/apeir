"""Workspace snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nous_runtime.workspace.resolver import resolve_workspace


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace_id: str
    path: str
    exists: bool
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "path": self.path,
            "exists": self.exists,
            "source": self.source,
        }


def snapshot_workspace(hint: str = "", *, root: str = "") -> WorkspaceSnapshot:
    resolved = resolve_workspace(hint, root=root)
    return WorkspaceSnapshot(
        workspace_id=resolved.workspace_id,
        path=resolved.path,
        exists=Path(resolved.path).exists() if resolved.path else False,
        source=resolved.source,
    )
