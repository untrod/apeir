"""Original Work resumes reviewed file effects, never the model's write tool."""

from __future__ import annotations

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.events import RunState
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.governance.cli import _build_context
from nous_runtime.tools import ToolCatalog
from nous_runtime.work import WorkHarness
from nous_runtime.workspace.proposals import WorkspaceProposalService


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous"))
    monkeypatch.setattr("nous_runtime.workspace.proposals.get_gate", lambda: gate)
    harness = WorkHarness(tmp_path)
    initial = harness.create(
        "Create first.txt and second.txt with approved file content"
    )
    service = WorkspaceProposalService(tmp_path, gate=gate)
    runtime = WorkspaceToolRuntime(
        str(tmp_path),
        allow_mutations=True,
        subject_id="agent.apeir.work",
        source_work_id=initial.run_id,
        plan_id=initial.plan.plan_id if initial.plan else "",
        proposal_service=service,
    )
    tools = ToolCatalog()
    tools.register_runtime(runtime)
    calls = []
    original_execute = tools.execute

    def counted(name, arguments):
        calls.append(name)
        return original_execute(name, arguments)

    tools.execute = counted
    decisions = iter(
        [
            {
                "status": "continue",
                "summary": "Discover file tools",
                "tool_name": "catalog_expand",
                "tool_arguments": {"category": "files"},
            },
            {
                "status": "continue",
                "summary": "Prepare reviewed files",
                "tool_name": "propose_files",
                "tool_arguments": {
                    "files": [
                        {"path": "first.txt", "content": "first\n"},
                        {"path": "second.txt", "content": "second\n"},
                    ]
                },
            },
        ]
    )
    waiting = harness.run(
        initial.run_id, deliberator=lambda _: next(decisions), tools=tools
    )
    assert waiting.state is RunState.WAITING_FOR_APPROVAL
    assert waiting.pending_action["recovery_policy"] == "workspace_proposal"
    assert not (tmp_path / "first.txt").exists()
    assert not (tmp_path / "second.txt").exists()
    return harness, waiting, service, tools, calls


def test_approve_once_restart_resumes_exact_original_proposal(scenario):
    harness, waiting, service, tools, calls = scenario
    pending = dict(waiting.pending_action)
    resumed_deliberation = []
    before = list(calls)
    assert (
        harness.resume(
            waiting.run_id,
            deliberator=lambda _: resumed_deliberation.append(True),
            tools=tools,
        ).state
        is RunState.WAITING_FOR_APPROVAL
    )
    assert calls == before and resumed_deliberation == []
    service.broker.respond_operation(
        pending["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    restarted = WorkHarness(harness.root)
    result = restarted.resume(
        waiting.run_id,
        deliberator=lambda _: {
            "status": "ask_user",
            "summary": "File effect matched; further tests require a qualified backend",
            "question": "Continue remaining checks",
        },
        tools=tools,
    )
    assert result.run_id == waiting.run_id
    assert (harness.root / "first.txt").read_text() == "first\n"
    assert (harness.root / "second.txt").read_text() == "second\n"
    assert calls == before
    original = service.read(pending["proposal_id"])
    assert original["authorization_id"] == pending["authorization_id"]
    assert original["verification"]["verdict"] == "MATCH"
    assert original["source_work_id"] == waiting.run_id
    assert result.pending_action == {}
    assert original["manifest_ref"] in result.artifacts
    assert original["verification"]["observation_ref"] in result.artifacts
    assert any(
        item.get("recovered")
        and item["result"]["proposal_id"] == original["proposal_id"]
        for item in result.observations
    )


def test_deny_never_calls_model_or_changes_files(scenario):
    harness, waiting, service, tools, calls = scenario
    pending = dict(waiting.pending_action)
    before = list(calls)
    service.broker.respond_operation(
        pending["approval_request_id"], "deny", _build_context(), gate=service.gate
    )
    result = harness.resume(
        waiting.run_id,
        deliberator=lambda _: pytest.fail("Deny cannot enter model execution"),
        tools=tools,
    )
    assert result.state is RunState.BLOCKED
    assert not (harness.root / "first.txt").exists()
    assert not (harness.root / "second.txt").exists()
    assert calls == before and calls.count("propose_files") == 1


def test_mismatched_original_work_binding_cannot_apply(scenario):
    harness, waiting, service, tools, calls = scenario
    before = list(calls)
    other = service.prepare(
        [{"path": "other.txt", "content": "other\n"}],
        subject_id="agent.apeir.work",
        source_work_id="different-work",
    )
    waiting.pending_action.update(
        proposal_id=other["proposal_id"],
        manifest_ref=other["manifest_ref"],
        authorization_id=other["authorization_id"],
        approval_request_id=other["approval_request_id"],
    )
    harness._persist(waiting, "work.test.boundary", {})
    service.broker.respond_operation(
        other["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    result = harness.resume(
        waiting.run_id,
        deliberator=lambda _: pytest.fail(
            "Wrong original binding cannot enter model execution"
        ),
        tools=tools,
    )
    assert result.state is RunState.RECOVERY_REQUIRED
    assert not (harness.root / "other.txt").exists()
    assert calls == before and calls.count("propose_files") == 1


@pytest.mark.parametrize("fail_after", [1, 2])
def test_response_loss_reconciles_original_files_without_replay(
    scenario, monkeypatch, fail_after
):
    harness, waiting, service, tools, calls = scenario
    pending = dict(waiting.pending_action)
    service.broker.respond_operation(
        pending["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    effects = []
    write = service.workbench._write_file

    def lose_response(*args, **kwargs):
        result = write(*args, **kwargs)
        effects.append(args[0])
        if len(effects) == fail_after:
            raise RuntimeError("effect completed but response was lost")
        return result

    monkeypatch.setattr(service.workbench, "_write_file", lose_response)
    uncertain = service.apply(pending["proposal_id"])
    assert uncertain["recovery_required"] and not uncertain["applied"]
    assert len(effects) == fail_after
    before = list(calls)
    restarted = WorkHarness(harness.root)
    result = restarted.resume(
        waiting.run_id,
        deliberator=lambda _: (
            {
                "status": "ask_user",
                "summary": "Inspect remaining qualified checks",
                "question": "Continue",
            }
            if fail_after == 2
            else pytest.fail("Partial effects remain UNKNOWN")
        ),
        tools=tools,
    )
    assert calls == before and calls.count("propose_files") == 1
    assert len(effects) == fail_after
    current = service.read(pending["proposal_id"])
    assert current["proposal_id"] == pending["proposal_id"]
    if fail_after == 1:
        assert result.state is RunState.RECOVERY_REQUIRED
        assert current["verification"]["verdict"] == "UNKNOWN"
        assert not (harness.root / "second.txt").exists()
    else:
        assert current["verification"]["verdict"] == "MATCH"
        assert any(item.get("recovered") for item in result.observations)
