from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from nous_runtime.capability.runtime_executor import (
    execute_runtime_capability,
    RuntimeCapabilityError,
)
from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.evaluation.validators.test_validator import TestValidator
from nous_runtime.events import EventStream, RunEvent, RunState


@pytest.mark.parametrize(
    "summary,code,complete,outcome",
    [
        ("Ran 1 test in 0.01s\n\nOK\n", 0, True, "PASS"),
        ("Ran 0 tests in 0.01s\n\nOK\n", 0, True, "UNKNOWN"),
        ("Ran 2 tests in 0.01s\n\nOK (skipped=2)\n", 0, True, "UNKNOWN"),
        ("Ran 2 tests in 0.01s\n\nFAILED (failures=1)\n", 1, True, "FAIL"),
        ("Ran 1 test in 0.01s\n\nOK\n", 0, False, "UNKNOWN"),
        ("", 0, True, "UNKNOWN"),
    ],
)
def test_unittest_requires_positive_complete_test_evidence(
    summary, code, complete, outcome
):
    assert (
        TestValidator.unittest_outcome(summary, code, complete=complete)["test_outcome"]
        == outcome
    )


@pytest.fixture
def command_receipt(tmp_path, monkeypatch):
    calls = []

    def run(self, profile, **kwargs):
        calls.append((profile, kwargs))
        run_id = "workbench-fixture-" + uuid4().hex
        events = EventStream(str(tmp_path))
        events.create_run(run_id)
        events.emit(
            RunEvent(
                run_id=run_id,
                event_type="command.output",
                actor="developer.workbench",
                payload={"stream": "stderr", "text": "Ran 1 test in 0.01s\n\nOK\n"},
            )
        )
        events.emit(
            RunEvent(
                run_id=run_id,
                event_type="test.completed",
                actor="developer.workbench",
                payload={
                    "profile": profile,
                    "exit_code": 0,
                    "ok": True,
                    "input_snapshot_sha256": "a" * 64,
                },
            )
        )
        events.emit_state_change(run_id, RunState.COMPLETED)
        return {
            "run_id": run_id,
            "ok": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "Ran 1 test in 0.01s\n\nOK\n",
            "input_snapshot_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        "nous_runtime.workspace.workbench.DeveloperWorkbench.run_profile", run
    )
    return calls


def test_dispatcher_consumes_existing_profile_and_registers_actual_receipt(
    tmp_path, command_receipt
):
    result = execute_runtime_capability(
        "project.run_tests", {"target": "tests"}, workspace_root=tmp_path
    )
    assert command_receipt == [
        ("python-unittest", {"target": "tests", "timeout_seconds": 30})
    ]
    assert result["ok"] and result["test_outcome"] == "PASS"
    assert result["test_counts"] == {"run": 1, "passed": 1}
    from nous_runtime.artifact import ArtifactRegistry, ContentAddressedArtifactStore

    assert ArtifactRegistry(tmp_path / ".nous/artifacts.jsonl").get(
        result["artifact_id"]
    )
    assert (
        ContentAddressedArtifactStore(tmp_path / ".nous/artifacts")
        .resolve(result["artifact_digest"], verify=True)
        .is_file()
    )


def test_workbench_api_uses_the_same_test_receipt_consumer(
    tmp_path, monkeypatch, command_receipt
):
    from nous_runtime.api.developer_routes import (
        DEVELOPER_GOVERNANCE,
        handle_developer_workspace_run,
    )

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    assert DEVELOPER_GOVERNANCE[("POST", "/api/v1/developer/workspace/run")][0] == (
        "project.run_tests"
    )
    response = handle_developer_workspace_run(
        {"profile": "python-unittest", "target": "tests"}
    )
    assert response["ok"]
    assert response["data"]["test_outcome"] == "PASS"
    assert response["data"]["artifact_id"]
    assert len(command_receipt) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"profile": "python"},
        {"argv": ["sh"]},
        {"target": "../outside"},
        {"timeout_seconds": True},
        {"timeout_seconds": 0},
        {"approved": True},
    ],
)
def test_bad_requests_never_reach_the_execution_consumer(
    tmp_path, command_receipt, arguments
):
    with pytest.raises(RuntimeCapabilityError):
        execute_runtime_capability(
            "project.run_tests", arguments, workspace_root=tmp_path
        )
    assert command_receipt == []


def test_model_tool_cannot_inherit_a_cli_owner_identity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "nous_runtime.capability.resolver.execute_capability_observation",
        lambda *a, **kw: calls.append(a),
    )
    result = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True).execute(
        "run_project_tests", {"target": "tests"}
    )
    assert result["error_code"] == "NOUS_AUTHENTICATION_REQUIRED"
    assert calls == []


def test_nested_failed_execution_cannot_become_tool_success(tmp_path, monkeypatch):
    from nous_runtime.planner.observation import Observation

    monkeypatch.setattr(
        "nous_runtime.capability.resolver.execute_capability_observation",
        lambda *a, **kw: Observation.success(
            "capability.execute",
            {"result": {"ok": False, "run_id": "original-run", "test_outcome": "FAIL"}},
        ),
    )
    runtime = WorkspaceToolRuntime(
        str(tmp_path),
        allow_mutations=True,
        authorization_context={"subject_type": "service", "subject_id": "fixture"},
    )
    result = runtime.execute("run_project_tests", {"target": "tests"})
    assert result["ok"] is False and result["run_id"] == "original-run"
    assert result["kernel_traversed"] is False


@pytest.mark.parametrize("mode", ["DENY", "ASK_APPROVAL", "RECOMMEND", "UNKNOWN"])
def test_project_tests_remain_fail_closed_in_legacy_compatibility_mode(
    tmp_path, monkeypatch, mode
):
    from nous_runtime.capability.resolver import execute_capability_observation

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "compatibility")
    monkeypatch.setattr(
        "nous_runtime.capability.resolver._get_capability_metadata",
        lambda _: {"executor_type": "runtime"},
    )
    decision = SimpleNamespace(
        action_mode=mode,
        reason_message="fixture decision",
        rule_class="OVERRIDABLE",
        decision_id="fixture",
        reason_code="fixture",
    )
    monkeypatch.setattr(
        "nous_runtime.governance.get_gate",
        lambda: SimpleNamespace(evaluate=lambda *a: decision),
    )
    calls = []
    monkeypatch.setattr(
        "nous_runtime.capability.runtime_executor.execute_runtime_capability",
        lambda *a, **kw: calls.append(a),
    )
    result = execute_capability_observation(
        "project.run_tests", _workspace_root=str(tmp_path), target="tests"
    )
    assert result.status == "failed"
    assert calls == []


def test_original_governance_approval_is_required_before_dispatch(
    tmp_path, monkeypatch, command_receipt
):
    from nous_runtime.governance import (
        AuthorizationContext,
        ExecutionAuthorizationGate,
        GovernanceStore,
    )
    from nous_runtime.governance.broker import ApprovalBroker
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.services.lifecycle import seed_capabilities

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    assert seed_capabilities() > 0
    gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous"))
    broker = ApprovalBroker(store=gate.store)
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", gate)
    monkeypatch.setattr("nous_runtime.governance.broker._broker", broker)
    context = AuthorizationContext(
        subject_type="service",
        subject_id="project-test-fixture",
        authn_method="opaque_token",
        authn_confidence=0.9,
        session_locality="local",
    )
    runtime = WorkspaceToolRuntime(
        str(tmp_path), allow_mutations=True, authorization_context=context.to_dict()
    )
    pending = runtime.execute("run_project_tests", {"target": "tests"})
    assert not pending["ok"] and pending["approval_required"], pending
    assert command_receipt == []
    broker.respond_legacy(
        pending["approval_request_id"], "approve", _build_context(), gate=gate
    )
    result = runtime.execute("run_project_tests", {"target": "tests"})
    assert result["ok"] and len(command_receipt) == 1, result
    assert result["test_outcome"] == "PASS"
    assert (
        result["execution_scope"] == "runtime-service"
        and result["kernel_traversed"] is False
    )
