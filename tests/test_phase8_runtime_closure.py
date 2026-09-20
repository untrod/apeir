from __future__ import annotations

from pathlib import Path

from nous_runtime.interaction.classifier import classify_intent
from nous_runtime.interaction.intent import CONTINUE, EXECUTE
from nous_runtime.runtime.orchestrator import RuntimeOrchestrator
from nous_runtime.runtime.request import RuntimeRequest
from nous_runtime.sdk import AgentTestHarness
from nous_runtime.workspace.isolation import is_within_workspace
from nous_runtime.workspace.registry import WorkspaceRegistry
from nous_runtime.workspace.resolver import resolve_workspace


def test_intent_runtime_classifies_continue_and_requires_confirmation_for_destructive_text():
    assert classify_intent("continue my Nous project").intent == CONTINUE

    decision = classify_intent("delete the workspace files")
    assert decision.intent == EXECUTE
    assert decision.requires_confirmation is True


def test_workspace_runtime_registers_switches_and_resolves_workspace(tmp_path: Path):
    registry = WorkspaceRegistry(str(tmp_path))
    created = registry.create("Nous Dev", path=str(tmp_path / "dev"))
    registry.switch(created.id)

    resolved = resolve_workspace(root=str(tmp_path))
    assert resolved.workspace_id == created.id
    assert is_within_workspace(str(tmp_path), str(tmp_path / "child.txt"))
    assert not is_within_workspace(str(tmp_path), str(tmp_path.parent / "outside.txt"))


def test_unified_runtime_pipeline_records_full_alpha_loop(tmp_path: Path):
    response = RuntimeOrchestrator(workspace_root=str(tmp_path)).run(
        RuntimeRequest("continue my Nous project", session="phase8-test")
    )

    assert response.status == "ok"
    assert response.intent == CONTINUE
    assert response.trace_id
    trace = response.result["trace"]
    stages = [entry["stage"] for entry in trace["entries"]]
    for expected in (
        "input",
        "intent",
        "workspace",
        "context",
        "planning",
        "decision",
        "governance",
        "agent",
        "capability",
        "evaluation",
        "experience",
        "response",
    ):
        assert expected in stages


def test_runtime_api_and_model_runtime_are_available(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")

    from nous_runtime.api.routes import route

    model = route(
        "POST",
        "/api/model/select",
        body={"task_type": "runtime", "privacy": "standard"},
        auth={"token": "test-token"},
    )
    assert model["ok"] is True
    assert model["data"]["model"]

    runtime = route(
        "POST",
        "/api/runtime/run",
        body={"user_input": "status"},
        auth={"token": "test-token"},
    )
    assert runtime["ok"] is True
    assert runtime["data"]["trace_id"]


def test_sdk_agent_test_harness_uses_runtime_pipeline(tmp_path: Path):
    harness = AgentTestHarness(workspace_root=str(tmp_path))
    data = harness.run_request("status")

    assert data["trace_id"]
    assert harness.results
