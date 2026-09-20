"""Workspace resolution for Runtime requests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nous_runtime.workspace.models import Workspace
from nous_runtime.workspace.registry import WorkspaceRegistry


@dataclass(frozen=True)
class ResolvedWorkspace:
    workspace_id: str
    path: str
    ambiguous: bool = False
    candidates: tuple[str, ...] = ()
    source: str = "default"


def resolve_workspace(hint: str = "", *, root: str = "") -> ResolvedWorkspace:
    registry = WorkspaceRegistry(root)
    workspaces = registry.list()
    if hint:
        matches = [ws for ws in workspaces if hint in (ws.id, ws.name)]
        if len(matches) == 1:
            return _resolved(matches[0], "hint")
        if len(matches) > 1:
            return ResolvedWorkspace(
                workspace_id="",
                path="",
                ambiguous=True,
                candidates=tuple(ws.id for ws in matches),
                source="hint",
            )
    active = registry.active()
    if active:
        return _resolved(active, "active")
    try:
        from nous_runtime.project.workspace import find_workspace

        found = find_workspace()
        if found:
            return ResolvedWorkspace(workspace_id="default", path=str(found), source="project.workspace")
    except Exception:
        pass
    return ResolvedWorkspace(workspace_id="default", path=str(Path(root or ".").resolve()), source="cwd")


def _resolved(workspace: Workspace, source: str) -> ResolvedWorkspace:
    return ResolvedWorkspace(workspace_id=workspace.id, path=workspace.path, source=source)
