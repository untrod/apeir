"""Ordinary workspace paths cannot alias private or external inode content."""

from __future__ import annotations

import hashlib
import os

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.workspace.isolation import normalize_workspace_path
from nous_runtime.workspace.proposals import WorkspaceProposalService
from nous_runtime.workspace.workbench import DeveloperWorkbench, WorkbenchError


@pytest.mark.parametrize("origin", [".nous", ".git", "outside"])
def test_ordinary_surfaces_refuse_linked_source_before_publication(tmp_path, origin):
    root = tmp_path / "workspace"
    root.mkdir()
    source = (
        tmp_path / "external.txt"
        if origin == "outside"
        else root / origin / "protected.txt"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"OWNED_BENIGN_PRIVATE_BOUNDARY_MARKER\n"
    source.write_bytes(content)
    alias = root / "notes.txt"
    os.link(source, alias)
    assert source.stat().st_nlink == alias.stat().st_nlink == 2
    digest = hashlib.sha256(content).hexdigest()
    workbench = DeveloperWorkbench(root)
    chat = WorkspaceToolRuntime(str(root))
    gate = ExecutionAuthorizationGate(store=GovernanceStore(root / ".nous"))
    proposals = WorkspaceProposalService(root, gate=gate)

    with pytest.raises(WorkbenchError, match="single-link"):
        workbench.read_file(alias.name)
    assert workbench.list_files()["files"] == []
    assert workbench.search("OWNED_BENIGN")["matches"] == []
    result = chat.execute("read_file", {"path": alias.name})
    assert result["ok"] is False
    assert "OWNED_BENIGN" not in str(result)
    assert chat.execute("search_workspace", {"query": "OWNED_BENIGN"})["matches"] == []
    assert chat._read_versions == {}
    with pytest.raises(WorkbenchError, match="single-link"):
        workbench.preview_write(alias.name, "replacement\n", expected_sha256=digest)
    with pytest.raises(WorkbenchError, match="single-link"):
        proposals.prepare(
            [
                {
                    "path": alias.name,
                    "content": "replacement\n",
                    "expected_sha256": digest,
                }
            ],
            subject_id="fixture-agent",
        )
    assert proposals.artifacts.list() == []
    assert proposals.list()["proposals"] == []
    assert source.read_bytes() == alias.read_bytes() == content


def test_protected_single_link_and_legacy_explicit_scope_remain_compatible(tmp_path):
    source = tmp_path / "ordinary.txt"
    source.write_text("ordinary\n")
    assert (
        normalize_workspace_path(str(tmp_path), source.name, protect_runtime_state=True)
        == source
    )
    alias = tmp_path / "legacy.txt"
    os.link(source, alias)
    assert normalize_workspace_path(str(tmp_path), alias.name) == alias
    assert alias.read_text() == "ordinary\n"
