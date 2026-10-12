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
    try:
        # This is the existing host registry, not a workspace-discovery source.
        # A linked/corrupt authority file cannot redirect a configured root.
        for path in (registry.store_path.parent, registry.store_path):
            if path.is_symlink() or not path.resolve().is_relative_to(registry.root):
                raise ValueError("Workspace registry escapes its configured root")
        if (
            registry.store_path.exists()
            and registry.store_path.stat().st_size > 1024 * 1024
        ):
            raise ValueError("Workspace registry exceeds its bounded read")
        workspaces = registry.list()
        active_id = registry.active_id()
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return _unresolved("registry")
    if hint == "default" and root:
        # Intent resolution emits this reserved selector without a user choice.
        # A registered external project named "default" cannot capture it.
        return ResolvedWorkspace(
            workspace_id="default", path=str(registry.root), source="root"
        )
    if hint:
        matches = [ws for ws in workspaces if hint in (ws.id, ws.name)]
        if len(matches) == 1:
            return _resolved(matches[0], "hint", registry.root)
        if len(matches) > 1:
            return ResolvedWorkspace(
                workspace_id="",
                path="",
                ambiguous=True,
                candidates=tuple(ws.id for ws in matches),
                source="hint",
            )
        # The existing Intent resolver emits this reserved default selector
        # when no workspace was chosen. It never names an external directory.
        if hint != "default":
            return _unresolved("hint")
    active = next((item for item in workspaces if item.id == active_id), None)
    if active:
        selected = _resolved(active, "active", registry.root)
        if not selected.ambiguous and (
            not root or Path(selected.path).is_relative_to(registry.root)
        ):
            return selected
    if root:
        return ResolvedWorkspace(
            workspace_id="default", path=str(registry.root), source="root"
        )
    try:
        from nous_runtime.project.workspace import find_workspace

        found = find_workspace()
        if found:
            return ResolvedWorkspace(
                workspace_id="default", path=str(found), source="project.workspace"
            )
    except Exception:
        pass
    return ResolvedWorkspace(
        workspace_id="default", path=str(Path(root or ".").resolve()), source="cwd"
    )


def _unresolved(source: str) -> ResolvedWorkspace:
    return ResolvedWorkspace(workspace_id="", path="", ambiguous=True, source=source)


def _resolved(workspace: Workspace, source: str, root: Path) -> ResolvedWorkspace:
    if not workspace.path:
        return _unresolved(source)
    path = Path(workspace.path).expanduser()
    try:
        resolved = (path if path.is_absolute() else root / path).resolve()
    except (OSError, ValueError, RuntimeError):
        return _unresolved(source)
    return ResolvedWorkspace(
        workspace_id=workspace.id, path=str(resolved), source=source
    )
