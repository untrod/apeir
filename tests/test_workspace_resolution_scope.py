"""Host-selected workspace scope stays separate from process cwd discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nous_runtime.agent.models import AgentIdentity, AgentManifest
from nous_runtime.agent.registry import AgentRegistry
from nous_runtime.context.providers.agent import AgentProvider
from nous_runtime.context.providers.decision import DecisionProvider
from nous_runtime.intelligence import (
    DecisionContext,
    DecisionRequest,
    DecisionType,
    RuntimePolicyEngine,
)
from nous_runtime.intelligence.store import JsonlDecisionStore
from nous_runtime.runtime.pipeline import RuntimePipeline
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.workspace.models import Workspace
from nous_runtime.workspace.registry import WorkspaceRegistry
from nous_runtime.workspace.resolver import resolve_workspace


def test_explicit_host_root_is_not_replaced_by_cwd_project(tmp_path, monkeypatch):
    root = tmp_path / "host"
    outside = tmp_path / "cwd-project"
    root.mkdir()
    outside.mkdir()
    calls = []

    def discover():
        calls.append(True)
        return outside

    monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", discover)
    resolved = resolve_workspace(root=str(root))
    assert Path(resolved.path) == root
    assert not resolved.ambiguous
    assert not calls


def test_no_explicit_root_preserves_legacy_project_discovery(tmp_path, monkeypatch):
    outside = tmp_path / "legacy-project"
    outside.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace", lambda: outside
    )
    resolved = resolve_workspace()
    assert Path(resolved.path) == outside
    assert resolved.source == "project.workspace"


def test_active_registered_child_keeps_bounded_root_default(tmp_path, monkeypatch):
    root = tmp_path / "host"
    child = root / "registered"
    child.mkdir(parents=True)
    registry = WorkspaceRegistry(str(root))
    workspace = registry.create("Registered", path=str(child))
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace", lambda: tmp_path / "outside"
    )
    resolved = resolve_workspace(root=str(root))
    assert resolved.workspace_id == workspace.id
    assert Path(resolved.path) == child


def test_active_external_registration_needs_explicit_selection(tmp_path):
    root = tmp_path / "host"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    registry = WorkspaceRegistry(str(root))
    external = registry.create("External", path=str(outside))
    default = resolve_workspace(root=str(root))
    assert Path(default.path) == root
    selected = resolve_workspace(external.id, root=str(root))
    assert selected.workspace_id == external.id
    assert Path(selected.path) == outside


def test_unknown_selector_never_falls_back_to_active_or_cwd(tmp_path, monkeypatch):
    registry = WorkspaceRegistry(str(tmp_path))
    registry.create("Known", path=str(tmp_path / "known"))
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace", lambda: tmp_path / "outside"
    )
    resolved = resolve_workspace("not-registered", root=str(tmp_path))
    assert resolved.ambiguous
    assert resolved.path == ""


def test_reserved_default_selector_stays_in_configured_host_root(tmp_path):
    root, outside = tmp_path / "host", tmp_path / "outside"
    assert Path(resolve_workspace("default", root=str(root)).path) == root
    WorkspaceRegistry(str(root)).create("External", path=str(outside))
    assert Path(resolve_workspace("default", root=str(root)).path) == root
    WorkspaceRegistry(str(root)).create("Default", path=str(outside))
    assert Path(resolve_workspace("default", root=str(root)).path) == root


def test_relative_registered_path_is_anchored_to_registry_root(tmp_path, monkeypatch):
    root = tmp_path / "host"
    root.mkdir()
    registry = WorkspaceRegistry(str(root))
    registry._save(
        [Workspace("relative", "Relative", path="nested")], active="relative"
    )
    monkeypatch.chdir(tmp_path)
    resolved = resolve_workspace("relative", root=str(root))
    assert Path(resolved.path) == root / "nested"


def test_pathless_selected_record_does_not_invent_a_cwd_path(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path))
    registry._save([Workspace("missing", "Missing", path="")], active="missing")
    resolved = resolve_workspace("missing", root=str(tmp_path))
    assert resolved.ambiguous
    assert resolved.path == ""


def test_prefix_sibling_is_outside_default_root(tmp_path):
    root = tmp_path / "host"
    sibling = tmp_path / "host-other"
    registry = WorkspaceRegistry(str(root))
    registry.create("Sibling", path=str(sibling))
    assert Path(resolve_workspace(root=str(root)).path) == root


def test_symlinked_active_path_cannot_expand_default_root(tmp_path):
    root = tmp_path / "host"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    registry = WorkspaceRegistry(str(root))
    # Persist the original path to exercise resolver validation after loading.
    registry._save([Workspace("link", "Link", path=str(root / "link"))], active="link")
    assert Path(resolve_workspace(root=str(root)).path) == root


def test_registry_symlink_cannot_change_explicit_host_authority(tmp_path):
    root = tmp_path / "host"
    outside = tmp_path / "outside.json"
    (root / ".nous").mkdir(parents=True)
    payload = {
        "active_workspace": "foreign",
        "workspaces": [
            Workspace("foreign", "Foreign", path=str(tmp_path / "foreign")).to_dict()
        ],
    }
    outside.write_text(json.dumps(payload), encoding="utf-8")
    (root / ".nous" / "workspaces.json").symlink_to(outside)
    resolved = resolve_workspace("foreign", root=str(root))
    assert resolved.ambiguous
    assert resolved.path == ""


def test_corrupt_registry_fails_closed_instead_of_discovering_cwd(
    tmp_path, monkeypatch
):
    registry = WorkspaceRegistry(str(tmp_path))
    registry.store_path.parent.mkdir(parents=True)
    registry.store_path.write_text("corrupt registry", encoding="utf-8")
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace", lambda: tmp_path / "outside"
    )
    resolved = resolve_workspace(root=str(tmp_path))
    assert resolved.ambiguous
    assert resolved.path == ""


def test_ambiguous_registered_selector_does_not_choose_either_path(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path))
    first = Workspace("first", "second", path=str(tmp_path / "first"))
    second = Workspace("second", "Other", path=str(tmp_path / "second"))
    registry._save([first, second], active="first")
    resolved = resolve_workspace("second", root=str(tmp_path))
    assert resolved.ambiguous
    assert resolved.path == ""
    assert resolved.candidates == ("first", "second")


@pytest.mark.parametrize("storage_path", [False, True])
def test_agent_context_uses_real_profiles_in_selected_workspace(
    tmp_path, monkeypatch, storage_path
):
    selected, outside = tmp_path / "selected", tmp_path / "outside"
    for root, agent_id in ((selected, "agent.selected"), (outside, "agent.outside")):
        AgentRegistry(root / ".nous").register(
            AgentManifest(AgentIdentity(agent_id, agent_id))
        )
    monkeypatch.chdir(outside)
    provider = AgentProvider(str(selected / ".nous" if storage_path else selected))
    items = provider.collect()
    assert [item.source_id for item in items] == ["agent.selected"]
    assert "REGISTERED" in items[0].content
    assert provider.health().item_count == 1
    assert not any("outside" in item.content for item in items)


def test_decision_health_and_collection_use_same_selected_store(tmp_path, monkeypatch):
    selected, outside = tmp_path / "selected" / ".nous", tmp_path / "outside" / ".nous"
    selected.mkdir(parents=True)
    outside.mkdir(parents=True)
    decision = RuntimePolicyEngine().decide(
        DecisionRequest(
            task_id="selected-task",
            decision_type=DecisionType.RETRIEVAL,
            context=DecisionContext(task_kind="question"),
        )
    )
    JsonlDecisionStore(selected).persist_decision_snapshot(decision)
    monkeypatch.setattr(
        "nous_runtime.project.workspace.find_workspace", lambda: outside
    )
    provider = DecisionProvider(str(selected))
    assert provider.health().item_count == 1
    assert {item.source_id for item in provider.collect()} == {decision.decision_id}


def test_runtime_ignores_cwd_workspace_identity_filled_by_intent_resolution(
    tmp_path, monkeypatch
):
    root, outside = tmp_path / "host", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    foreign = WorkspaceRegistry(str(outside)).create("Foreign", path=str(outside))
    monkeypatch.chdir(outside)
    result = RuntimePipeline(workspace_root=str(root)).run(RuntimeRequest("status"))
    selection = next(
        entry
        for entry in result.result["trace"]["entries"]
        if entry["stage"] == "workspace"
    )
    assert selection["data"]["path"] == str(root)
    assert selection["data"]["workspace_id"] != foreign.id
    assert result.workspace == "default"


def test_runtime_unknown_explicit_workspace_never_calls_product_handler(tmp_path):
    calls = []
    pipeline = RuntimePipeline(
        workspace_root=str(tmp_path),
        product_handlers={"chat": lambda *args: calls.append(args) or {"ok": True}},
    )
    result = pipeline.run(
        RuntimeRequest(
            "status", workspace="missing", constraints={"product_capability": "chat"}
        )
    )
    assert result.status == "workspace_ambiguous"
    assert calls == []
