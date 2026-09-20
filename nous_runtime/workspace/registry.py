"""JSON-backed Workspace Runtime registry."""

from __future__ import annotations

import json
import re
from pathlib import Path

from nous_runtime.workspace.models import Workspace


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return slug or "workspace"


class WorkspaceRegistry:
    def __init__(self, root: str = ""):
        self.root = Path(root or ".").resolve()
        self.store_path = self.root / ".nous" / "workspaces.json"

    def list(self) -> list[Workspace]:
        if not self.store_path.exists():
            return []
        data = json.loads(self.store_path.read_text(encoding="utf-8") or "{}")
        return [Workspace.from_dict(item) for item in data.get("workspaces", [])]

    def create(self, name: str, *, owner: str = "local", path: str = "", workspace_type: str = "project") -> Workspace:
        workspaces = self.list()
        workspace_id = _slug(name)
        existing_ids = {ws.id for ws in workspaces}
        if workspace_id in existing_ids:
            suffix = 2
            while f"{workspace_id}-{suffix}" in existing_ids:
                suffix += 1
            workspace_id = f"{workspace_id}-{suffix}"
        workspace = Workspace(
            id=workspace_id,
            name=name,
            owner=owner,
            type=workspace_type,
            path=str(Path(path or self.root).resolve()),
        )
        self._save(workspaces + [workspace], active=workspace.id if len(workspaces) == 0 else self.active_id())
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        for workspace in self.list():
            if workspace.id == workspace_id or workspace.name == workspace_id:
                return workspace
        return None

    def active_id(self) -> str:
        if not self.store_path.exists():
            return ""
        data = json.loads(self.store_path.read_text(encoding="utf-8") or "{}")
        return str(data.get("active_workspace") or "")

    def active(self) -> Workspace | None:
        active_id = self.active_id()
        return self.get(active_id) if active_id else None

    def switch(self, workspace_id: str) -> Workspace:
        workspace = self.get(workspace_id)
        if workspace is None:
            raise ValueError(f"workspace not found: {workspace_id}")
        self._save(self.list(), active=workspace.id)
        return workspace

    def _save(self, workspaces: list[Workspace], *, active: str = "") -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_workspace": active,
            "workspaces": [workspace.to_dict() for workspace in workspaces],
        }
        self.store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
