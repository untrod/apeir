from __future__ import annotations

import json
from pathlib import Path

from nous_runtime.workspace.auto_create import (
    _is_safe_location,
    create_default_workspace,
)


def test_runtime_is_the_single_workspace_metadata_writer(tmp_path) -> None:
    result = create_default_workspace(tmp_path)

    assert result["ok"] is True
    manifest = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    registry_path = tmp_path / ".nous" / "workspaces.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["active_workspace"] == manifest["workspace_id"]
    assert registry["workspaces"][0]["id"] == manifest["workspace_id"]
    assert registry["workspaces"][0]["metadata"]["managed_by"] == "nous-runtime"

    second = create_default_workspace(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert second["created"] is False
    assert second["workspace_id"] == manifest["workspace_id"]
    assert len(registry["workspaces"]) == 1


def test_workspace_authority_rejects_filesystem_root_and_home(tmp_path) -> None:
    assert _is_safe_location(Path(tmp_path.anchor)) is False
    assert _is_safe_location(Path.home()) is False
