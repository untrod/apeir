"""Context delivery preserves source data within bound canonical admission."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone

import pytest

from nous_runtime.context.builder import ContextBudgetError, ContextBuilder
from nous_runtime.context.exceptions import ContextBuildError, ContextPermissionError
from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.types import BuildRequest
from nous_runtime.governance.cli import _build_context as local_owner_context
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.runtime.pipeline import RuntimePipeline
from nous_runtime.runtime.request import RuntimeRequest
from tests.context.test_guard_admission import (
    admitted_context as admitted_context_fixture,
)

admitted_context = admitted_context_fixture


class Source:
    source_type = "memory"

    def __init__(self, items):
        self.items = items
        self.calls = []

    def collect(self, request_hint="", limit=100):
        self.calls.append((request_hint, limit))
        return self.items[:limit]


def live_request(context, **kwargs):
    return RuntimeRequest(
        kwargs.pop("user_input", "continue the current objective"),
        authenticated_context=context,
        **kwargs,
    )


def connect_source(monkeypatch, source):
    def build(request, workspace):
        return ContextBuilder(workspace=workspace, providers=[source]).build_context(
            request
        )

    monkeypatch.setattr("nous_runtime.context.builder.build_context", build)


def test_normal_initialization_declares_context_reader_without_granting_permission(
    tmp_path, monkeypatch
):
    from nous_runtime.compat.capability import get_capability, set_capability_enabled
    from nous_runtime.services.lifecycle import seed_capabilities
    from nous_runtime.governance.gate import ExecutionAuthorizationGate
    from nous_runtime.governance.store import GovernanceStore

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "capabilities"))
    seed_capabilities()
    capability = get_capability("context.read")
    assert capability is not None
    assert capability["metadata"]["side_effect_class"] == "read_only"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    gate = ExecutionAuthorizationGate(
        GovernanceStore(workspace), permission_engine=PermissionEngine()
    )
    result = RuntimePipeline(workspace_root=str(workspace), gate=gate)._build_context(
        live_request(local_owner_context()), "chat", str(workspace)
    )
    assert result["status"] == "no_source_access"
    assert (
        gate.store.get_decision(result["admission_decision_id"])["reason_code"]
        == "PERMISSION_DENIED"
    )

    assert set_capability_enabled("context.read", False)
    seed_capabilities()
    assert get_capability("context.read")["enabled"] == 0


def test_owned_default_sources_reach_runtime_handler_with_live_identity(
    tmp_path, monkeypatch
):
    import json

    from nous_runtime.governance.gate import ExecutionAuthorizationGate
    from nous_runtime.governance.store import GovernanceStore
    from nous_runtime.project.memory import add_fact
    from nous_runtime.services.lifecycle import seed_capabilities

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "capabilities"))
    seed_capabilities()
    workspace = tmp_path / "workspace"
    state = workspace / ".nous"
    state.mkdir(parents=True)
    (state / "project.json").write_text(
        json.dumps({"name": "owned-context-project", "project_id": "owned-project"}),
        encoding="utf-8",
    )
    add_fact(state, "current-goal", "preserve the middle constraint")
    actor = local_owner_context()
    gate = ExecutionAuthorizationGate(
        GovernanceStore(workspace),
        permission_engine=PermissionEngine(
            (PermissionRule(actor.subject_id, "context.read", "*"),)
        ),
    )
    captured = {}

    def handler(request, context):
        captured.update(context["context_snapshot"])
        return {"ok": True, "status": "success", "content": "source inspection"}

    pipeline = RuntimePipeline(
        workspace_root=str(workspace), gate=gate, product_handlers={"chat": handler}
    )
    request = live_request(
        actor,
        user_input="status",
        constraints={"product_capability": "chat"},
    )
    response = pipeline.run(request)
    assert response.status == "ok"
    assert captured["delivery_status"] == "loaded"
    contents = [item["content"] for item in captured["items"]]
    assert "Project: owned-context-project" in contents
    assert "current-goal: preserve the middle constraint" in contents
    assert captured["metadata"]["context_binding"]["context_id"] == actor.context_id
    assert not (workspace / "context.db").exists()
    assert (state / "context.db").exists()
    events = pipeline.events.load_events(request.request_id)
    serialized = json.dumps([event.to_dict() for event in events], ensure_ascii=False)
    assert "authenticated_context" not in serialized
    assert "subject_claims" not in serialized
    assert "preserve the middle constraint" not in serialized
    context_event = next(
        event for event in events if event.event_type == "context.loaded"
    )
    assert context_event.payload["snapshot_id"] == captured["snapshot_id"]
    assert context_event.payload["checksum"] == captured["checksum"]
    assert "items" not in context_event.payload
    assert "preserve the middle constraint" not in json.dumps(response.to_dict())


def test_cli_passes_current_local_attestation_and_configured_host_root(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from nous_runtime.governance.cli import _is_local_owner_context
    from nous_runtime.runtime.cli import runtime_app

    captured = {}

    class Orchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, request):
            captured["request"] = request
            return SimpleNamespace(
                status="ok", message="inspected", trace_id="original-trace"
            )

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("nous_runtime.runtime.cli.RuntimeOrchestrator", Orchestrator)
    result = CliRunner().invoke(runtime_app, ["run", "status"])
    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert captured["workspace_root"] == str(tmp_path.resolve())
    assert _is_local_owner_context(request.authenticated_context)
    assert request.user_id == request.authenticated_context.subject_id
    assert request.governance_surface == "local_cli"
    assert "authenticated_context" not in request.to_dict()


def test_long_required_constraints_are_whole_and_keep_source_positions():
    required_content = (
        "HEAD constraint\n" + "long objective " * 2_000 + "\nTAIL constraint"
    )
    required = ContextItem(
        item_id="required",
        source_id="objective-1",
        source_type="memory",
        content=required_content,
        importance=0,
        confidence=0,
        metadata={"context_class": "active_objective", "file_sha256": "version-1"},
    )
    optional = ContextItem(
        item_id="optional",
        content="optional high-score fact",
        source_type="memory",
        importance=1,
        confidence=1,
    )
    source = Source([optional, required])
    snapshot = ContextBuilder(providers=[source]).build_context(
        BuildRequest(
            context_hint="complete current objective",
            max_items=1,
            metadata={
                "max_input_tokens": 12_000,
                "token_budgets": {"active_objective": 1},
                "min_importance": 1,
                "min_confidence": 1,
            },
        )
    )

    assert [item.item_id for item in snapshot.items] == ["required"]
    item = snapshot.items[0]
    assert item.content == required_content
    assert item.metadata["source_position"] == 1
    assert item.metadata["included_position"] == 0
    assert (
        item.metadata["original_content_sha256"]
        == hashlib.sha256(required_content.encode()).hexdigest()
    )
    assert (
        item.metadata["included_content_sha256"]
        == item.metadata["original_content_sha256"]
    )
    assert item.metadata["original_content_characters"] == len(required_content)
    assert (
        snapshot.metadata["context_build_profile"]["estimated_input_tokens"] <= 12_000
    )
    assert (
        snapshot.metadata["context_build_profile"]["token_measurement"] == "estimated"
    )
    assert source.calls == [("complete current objective", 100)]
    assert (
        snapshot.metadata["truncation_explanation"][0]["reason"]
        == "context_item_budget"
    )


@pytest.mark.parametrize("budget,max_items", [(10, 100), (100, 1)])
def test_required_context_over_bound_is_explicit(budget, max_items):
    items = [
        ContextItem(content="constraint " * 10, source_type="runtime") for _ in range(2)
    ]
    with pytest.raises(ContextBudgetError):
        ContextBuilder(providers=[Source(items)]).build_context(
            BuildRequest(max_items=max_items, metadata={"max_input_tokens": budget})
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_input_tokens", True),
        ("max_input_tokens", 0),
        ("max_input_tokens", 1.5),
        ("token_budgets", {"workspace_facts": -1}),
        ("token_budgets", {"recent_messages": False}),
    ],
)
def test_invalid_bounds_are_rejected_before_source_collection(field, value):
    source = Source([ContextItem(content="fact", source_type="memory")])
    with pytest.raises(ContextBuildError):
        ContextBuilder(providers=[source]).build_context(
            BuildRequest(metadata={field: value})
        )
    assert not source.calls


def test_same_text_from_distinct_sources_or_versions_is_not_collapsed():
    memory = ContextItem(
        source_type="memory",
        source_id="same-id",
        content="same text",
        metadata={"file_sha256": "one"},
    )
    project = ContextItem(
        source_type="project", source_id="same-id", content="same text"
    )
    updated = replace(memory, item_id="changed-source", metadata={"file_sha256": "two"})
    snapshot = ContextBuilder(
        providers=[Source([memory, memory, project, updated])]
    ).build_context(BuildRequest())
    assert snapshot.item_count == 3
    assert snapshot.metadata["duplicate_suppressed"] == 1
    assert {item.source_type for item in snapshot.items} == {"memory", "project"}
    assert {item.metadata.get("file_sha256") for item in snapshot.items} == {
        None,
        "one",
        "two",
    }


def test_restricted_flag_cannot_authorize_source_items():
    items = [
        ContextItem(content=permission, source_type="memory", permission=permission)
        for permission in ("read", "restricted", "private")
    ]
    snapshot = ContextBuilder(providers=[Source(items)]).build_context(
        BuildRequest(metadata={"include_restricted": True})
    )
    assert [item.permission for item in snapshot.items] == ["read"]


def test_existing_datetime_source_timestamp_round_trips_canonically():
    item = ContextItem(
        content="memory fact",
        source_type="memory",
        created_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    snapshot = ContextBuilder(providers=[Source([item])]).build_context(BuildRequest())
    assert snapshot.items[0].created_at == "2026-10-12T00:00:00Z"
    assert (
        ContextSnapshot.from_dict(snapshot.to_dict()).checksum() == snapshot.checksum()
    )


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        {
            "subject_type": "user",
            "subject_id": "owner",
            "authn_method": "cli_os_user",
            "authn_confidence": 1,
        },
        {
            "subject_type": "service",
            "subject_id": "current-service",
            "authn_method": "runtime",
            "authn_confidence": 1,
        },
        {
            "subject_type": "agent",
            "subject_id": "agent.coding",
            "authn_method": "runtime",
            "authn_confidence": 1,
        },
    ],
)
def test_pipeline_without_live_identity_never_collects_sources(
    tmp_path, monkeypatch, authorization
):
    source = Source([ContextItem(content="external fact", source_type="memory")])
    connect_source(monkeypatch, source)
    request = RuntimeRequest(
        "full user objective", authorization_context=authorization or {}
    )
    result = RuntimePipeline(workspace_root=str(tmp_path))._build_context(
        request, "continue", str(tmp_path)
    )
    assert result["status"] == "no_source_access"
    assert result["items"] == []
    assert not source.calls
    assert request.user_input == "full user objective"


def test_context_audit_uses_private_existing_state_directory(tmp_path):
    from nous_runtime.context.security import ContextGuard

    root = tmp_path / "project"
    guard = ContextGuard(str(root))
    assert Path(guard._store.db_path) == root / ".nous" / "context.db"
    assert not (root / "context.db").exists()
    legacy = ContextGuard(str(root / ".nous"))
    assert legacy._store.db_path == guard._store.db_path


def test_pipeline_uses_configured_canonical_gate_and_preserves_long_metadata(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    service = replace(context, subject_type="service", subject_id="current-service")
    content = "  HEAD\n" + "constraint " * 3_000 + "\nTAIL  "
    item = ContextItem(
        item_id="long",
        source_id="goal-file",
        source_type="memory",
        content=content,
        permission="read",
        metadata={
            "context_class": "active_objective",
            "file_sha256": "file-version",
            "owner_id": "original-owner",
            "citation": "source reference",
        },
    )
    source = Source([item])
    connect_source(monkeypatch, source)
    # A different global authority denies access. The pipeline's configured
    # Gate must own source collection and each item decision instead.
    from nous_runtime.governance import gate as gate_module
    from nous_runtime.governance.gate import ExecutionAuthorizationGate

    monkeypatch.setattr(
        gate_module,
        "_gate_instance",
        ExecutionAuthorizationGate(gate.store, permission_engine=PermissionEngine(())),
    )
    pipeline = RuntimePipeline(workspace_root=guard._workspace, gate=gate)
    request = live_request(service, constraints={"context_max_input_tokens": 16_000})
    result = pipeline._build_context(request, "continue", guard._workspace)

    assert result["delivery_status"] == "loaded"
    assert result["status"] == "active"
    delivered = result["items"][0]
    assert delivered["content"] == content
    assert delivered["permission"] == "read"
    assert delivered["metadata"]["owner_id"] == "original-owner"
    assert delivered["metadata"]["file_sha256"] == "file-version"
    assert delivered["metadata"]["source_position"] == 0
    assert result["metadata"]["source_versions"] == {"memory:goal-file": "file-version"}
    assert result["checksum"] == ContextSnapshot.from_dict(result).checksum()
    assert not result["truncated"]
    binding = result["metadata"]["context_binding"]
    assert binding["subject_id"] == "current-service"
    assert "subject_claims" not in binding
    assert (
        gate.store.get_decision(binding["admission_decision_id"])["context_id"]
        == service.context_id
    )
    assert source.calls == [(request.user_input, 100)]


def test_pipeline_delivers_more_than_thirty_two_whole_items(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    service = replace(context, subject_type="service", subject_id="current-service")
    items = [
        ContextItem(
            item_id=f"fact-{index}", content=f"fact {index}", source_type="memory"
        )
        for index in range(40)
    ]
    connect_source(monkeypatch, Source(items))
    result = RuntimePipeline(workspace_root=guard._workspace, gate=gate)._build_context(
        live_request(service), "continue", guard._workspace
    )
    assert result["item_count"] == 40
    assert len(result["items"]) == 40
    assert not result["truncated"]


def test_pipeline_denied_canonical_permission_never_collects(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    gate.permission_engine = PermissionEngine(
        (PermissionRule("*", "context.read", "*", effect="deny"),)
    )
    source = Source([ContextItem(content="fact", source_type="memory")])
    connect_source(monkeypatch, source)
    result = RuntimePipeline(workspace_root=guard._workspace, gate=gate)._build_context(
        live_request(context), "continue", guard._workspace
    )
    assert result["status"] == "no_source_access"
    assert not source.calls
    assert gate.store.get_decision(result["admission_decision_id"])["allowed"] is False


def test_pipeline_unknown_agent_has_no_automatic_registration(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    source = Source([ContextItem(content="fact", source_type="memory")])
    connect_source(monkeypatch, source)
    result = RuntimePipeline(workspace_root=guard._workspace, gate=gate)._build_context(
        live_request(replace(context, subject_id="browser-mode")),
        "continue",
        guard._workspace,
    )
    assert result["status"] == "no_source_access"
    assert not source.calls


def test_pipeline_actual_owner_can_read_private_data_without_serializing_attestation(
    admitted_context, monkeypatch
):
    guard, gate, _ = admitted_context
    owner = local_owner_context()
    private = ContextItem(
        content="owner fact",
        source_type="memory",
        permission="private",
        metadata={"owner_id": owner.subject_id},
    )
    connect_source(monkeypatch, Source([private]))
    result = RuntimePipeline(workspace_root=guard._workspace, gate=gate)._build_context(
        live_request(owner, user_id=owner.subject_id), "continue", guard._workspace
    )
    assert result["items"][0]["permission"] == "private"
    assert "authorization_context" not in result["metadata"]
    assert "context_guard" not in result["metadata"]
    assert "subject_claims" not in result["metadata"]["context_binding"]


def test_model_continuation_rechecks_retained_source_permission(
    admitted_context, monkeypatch
):
    from nous_runtime.model_runtime.bridges import GatewayChatHandler
    from nous_runtime.model_runtime.facade import GatewayResponse

    guard, gate, identity = admitted_context
    service_identity = replace(
        identity, subject_type="service", subject_id="current-service"
    )
    (Path(guard._workspace) / "example.txt").write_text("owned file")
    connect_source(
        monkeypatch,
        Source([ContextItem(content="bound source fact", source_type="memory")]),
    )
    request = live_request(
        service_identity,
        constraints={"agent_mode": "agent", "workspace_path": guard._workspace},
    )
    snapshot = RuntimePipeline(
        workspace_root=guard._workspace, gate=gate
    )._build_context(request, "continue", guard._workspace)
    assert snapshot["delivery_status"] == "loaded"

    class Facade:
        calls = 0

        def try_invoke_sync(self, invoked):
            self.calls += 1
            assert self.calls == 1, (
                "Revoked context must not enter another provider call"
            )
            assert "bound source fact" in str(invoked.messages)
            gate.permission_engine = PermissionEngine(())
            return GatewayResponse(
                request_id="controlled-first-call",
                content="",
                tool_calls=(
                    {
                        "id": "read-owned",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"example.txt"}',
                        },
                    },
                ),
            )

    facade = Facade()
    result = GatewayChatHandler(facade, checkpoint_root=guard._workspace)(
        request,
        {
            "intent": "continue",
            "workspace": guard._workspace,
            "context_snapshot": snapshot,
            "_governance_gate": gate,
            "runtime_plan": {"execution_mode": "gateway_agent"},
        },
    )
    assert not result["ok"]
    assert result["agent"] == "runtime.context"
    assert facade.calls == 1


def test_transient_identity_is_not_serialized_into_runtime_evidence(admitted_context):
    _, _, identity = admitted_context
    request = live_request(identity)
    assert request.authenticated_context is identity
    assert "authenticated_context" not in request.to_dict()
    assert "authenticated_context" not in repr(request)


def test_required_over_budget_stops_pipeline_before_product_handler(
    admitted_context, monkeypatch
):
    guard, gate, context = admitted_context
    service = replace(context, subject_type="service", subject_id="current-service")
    source = Source([ContextItem(content="mandatory " * 200, source_type="runtime")])
    monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", lambda: None)
    connect_source(monkeypatch, source)
    invoked = []
    pipeline = RuntimePipeline(
        workspace_root=guard._workspace,
        gate=gate,
        product_handlers={"chat": lambda *args: invoked.append(args) or {"ok": True}},
    )
    request = live_request(
        service,
        constraints={"product_capability": "chat", "context_max_input_tokens": 10},
    )
    response = pipeline.run(request)
    assert response.status == "context_budget_exceeded"
    assert not invoked
    assert response.result["context_snapshot"]["items"] == []


def bound_snapshot():
    first = ContextItem(
        item_id="z-first",
        source_type="project",
        source_id="file-a",
        content="Project old content",
        metadata={"file_sha256": "file-a-v1"},
    )
    second = ContextItem(
        item_id="a-second",
        source_type="memory",
        source_id="file-b",
        content="stable content",
        metadata={"file_sha256": "file-b-v1"},
    )
    binding = {
        "subject_id": "owner",
        "workspace": "/current",
        "admission_decision_id": "permission-v1",
    }
    return ContextSnapshot(
        items=(first, second),
        project={"summary": first.content},
        metadata={"context_binding": binding},
    ), binding


@pytest.mark.parametrize(
    "changed", ["subject_id", "workspace", "admission_decision_id"]
)
def test_incremental_identity_workspace_or_permission_change_denies(changed):
    snapshot, binding = bound_snapshot()
    with pytest.raises(ContextPermissionError):
        snapshot.apply_patch(
            context_binding={**binding, changed: "changed"}, source_versions={}
        )


def test_incremental_sources_require_current_versions_and_keep_original_order():
    snapshot, binding = bound_snapshot()
    with pytest.raises(ContextPermissionError):
        snapshot.apply_patch(context_binding=binding)
    versions = {"project:file-a": "file-a-v1", "memory:file-b": "file-b-v1"}
    same = snapshot.apply_patch(context_binding=binding, source_versions=versions)
    assert [item.item_id for item in same.items] == ["z-first", "a-second"]
    changed = snapshot.apply_patch(
        context_binding=binding,
        source_versions={**versions, "project:file-a": "file-a-v2"},
    )
    assert [item.item_id for item in changed.items] == ["a-second"]
    assert "summary" not in changed.project
    assert changed.metadata["selection_required"] is True
    assert changed.metadata["execution_authority"] is False


def test_incremental_upserts_require_current_authoritative_source_version():
    snapshot, binding = bound_snapshot()
    update = replace(
        snapshot.items[0],
        content="Project updated content",
        metadata={"file_sha256": "file-a-v2"},
    )
    versions = {"project:file-a": "file-a-v2", "memory:file-b": "file-b-v1"}
    with pytest.raises(ValueError, match="missing or stale"):
        snapshot.apply_patch(
            upsert=(update,),
            context_binding=binding,
            source_versions={**versions, "project:file-a": "old-version"},
        )
    patched = snapshot.apply_patch(
        upsert=(update,), context_binding=binding, source_versions=versions
    )
    assert {item.item_id: item.content for item in patched.items}[
        "z-first"
    ] == "Project updated content"
    assert [item.item_id for item in patched.items] == ["z-first", "a-second"]
    assert patched.metadata["source_versions"] == versions
    assert patched.metadata["patch_removals"] == 0


def test_incremental_content_cannot_keep_stale_original_source_provenance():
    original = "source text"
    item = ContextItem(
        source_type="memory",
        content=original,
        metadata={
            "original_content_sha256": hashlib.sha256(original.encode()).hexdigest()
        },
    )
    snapshot = ContextSnapshot(items=(item,))
    with pytest.raises(ValueError, match="source provenance"):
        snapshot.apply_patch(upsert=(replace(item, content="changed text"),))


@pytest.mark.parametrize(
    "change", ["permission", "source_id", "owner", "version", "order", "identity"]
)
def test_checksum_binds_source_permission_identity_version_and_order(change):
    snapshot, _ = bound_snapshot()
    first, second = snapshot.items
    if change == "permission":
        changed = replace(
            snapshot, items=(replace(first, permission="private"), second)
        )
    elif change == "source_id":
        changed = replace(
            snapshot, items=(replace(first, source_id="another-source"), second)
        )
    elif change in {"owner", "version"}:
        key = "owner_id" if change == "owner" else "file_sha256"
        changed = replace(
            snapshot,
            items=(replace(first, metadata={**first.metadata, key: "changed"}), second),
        )
    elif change == "order":
        changed = replace(snapshot, items=(second, first))
    else:
        changed = replace(
            snapshot, metadata={"context_binding": {"subject_id": "another-owner"}}
        )
    assert snapshot.checksum() != changed.checksum()
