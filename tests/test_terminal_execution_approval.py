from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace


from nous_runtime.cli.execution_ui import (
    presentation_state,
    render_approval_panel,
    render_run_view,
    render_runs_queue,
    render_tool_action_cards,
)
from nous_runtime.events.models import RunEvent, RunRecord, RunState
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance.store import GovernanceStore


def _event(event_type: str, **payload: object) -> RunEvent:
    return RunEvent(
        run_id="run_terminal",
        task_id="task_terminal",
        event_type=event_type,
        payload=dict(payload),
    )


def _proposal() -> ActionProposal:
    return ActionProposal(
        action_type="workspace.mutate",
        capability_id="file.write",
        parameter_summary="write configuration",
        target_workspace="workspace-a",
        affected_resources=("settings.toml",),
        side_effect_class="local_write",
        reversibility="reversible",
        required_permissions=("workspace.write",),
    )


def _context(subject_id: str = "requester") -> AuthorizationContext:
    return AuthorizationContext(
        subject_type="agent",
        subject_id=subject_id,
        authn_method="runtime",
        authn_confidence=1.0,
        session_locality="local",
    )


def test_execution_timeline_uses_canonical_state_without_fake_progress():
    record = RunRecord(
        run_id="run_terminal",
        task_id="task_terminal",
        state=RunState.RUNNING,
        plan={"steps": [{"name": "Inspect", "status": "completed"}, "Apply"]},
    )
    events = [
        _event("run.created"),
        _event("plan.created"),
        _event("run.started"),
        _event("step.completed", name="Inspect"),
        _event("step.started", name="Apply"),
    ]

    rendered = render_run_view(record, events, width=92)

    assert presentation_state(record, events) == "running"
    assert "Execution" in rendered
    assert "Running" in rendered
    assert "Completed" in rendered
    assert "%" not in rendered
    assert presentation_state(
        RunRecord(run_id="run_paused", state=RunState.PAUSED),
        [],
    ) == "paused"
    completed = RunRecord(run_id="run_done", state=RunState.COMPLETED)
    assert presentation_state(completed, [_event("approval.denied")]) == "succeeded"


def test_tool_cards_fold_logs_and_redact_secret_values():
    events = [
        _event(
            "command.started",
            command="deploy --token=private-value",
            workspace="workspace-a",
            purpose="Validate deployment",
            risk="medium",
        ),
        _event("command.output", detail="line one"),
        _event("command.output", detail="line two"),
    ]

    rendered = render_tool_action_cards(events, width=88)

    assert "Shell command" in rendered
    assert "private-value" not in rendered
    assert "[redacted]" in rendered
    assert "Folded" in rendered
    assert "2 events" in rendered


def test_queue_groups_runs_and_marks_focus():
    records = [
        RunRecord(run_id="run_active", state=RunState.RUNNING),
        RunRecord(run_id="run_queued", state=RunState.CREATED),
        RunRecord(run_id="run_approval", state=RunState.WAITING_FOR_APPROVAL),
        RunRecord(run_id="run_done", state=RunState.COMPLETED),
    ]

    rendered = render_runs_queue(records, focused_run_id="run_active")

    for section in ("Active", "Queued", "Approval required", "Recent"):
        assert section in rendered
    assert "run_active" in rendered
    assert "/run focus RUN_ID" in rendered


def test_approval_panel_contains_decision_evidence_and_controls():
    request = {
        "request_id": "apr_terminal",
        "summary": "workspace.mutate: file.write",
        "risk_summary": "Risk: high",
        "scope_summary": "Workspace: workspace-a, Resources: 1",
        "requested_by": "agent-a",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    rendered = render_approval_panel(
        request,
        _proposal().to_dict(),
        selected=2,
        details=True,
        width=90,
    )

    for label in (
        "Action",
        "Target",
        "Workspace",
        "Permissions",
        "Risk",
        "Actor",
        "Allow once",
        "Allow for session",
        "Edit action",
        "Deny",
    ):
        assert label in rendered
    assert "apr_terminal" in rendered


def test_interactive_approval_reader_supports_details_and_direct_choice(monkeypatch):
    from nous_runtime.cli import terminal_ui

    keys = iter(("CTRL_O", "2"))
    monkeypatch.setattr(terminal_ui, "_interactive_editor_supported", lambda: True)
    monkeypatch.setattr(terminal_ui, "_raw_input_mode", nullcontext)
    monkeypatch.setattr(terminal_ui, "_read_key", lambda: next(keys))
    monkeypatch.setattr(terminal_ui, "_clear_rendered_region", lambda *_: None)

    decision = terminal_ui.read_approval_decision(
        {"request_id": "apr_terminal", "summary": "write"},
        _proposal().to_dict(),
    )

    assert decision == "session"


def test_approval_modes_reuse_policy_and_keep_high_risk_human_gated(
    monkeypatch,
    tmp_path,
):
    from nous_runtime.cli import shell_v2
    from nous_runtime.governance import broker as broker_module

    broker = ApprovalBroker(store=GovernanceStore(str(tmp_path)))
    monkeypatch.setattr(broker_module, "get_broker", lambda store=None: broker)
    monkeypatch.setenv("NOUS_SUBJECT_ID", "reviewer")

    for mode in ("strict", "balanced", "assisted"):
        result = shell_v2._set_approval_mode(mode)
        policy = broker.get_policy("reviewer")
        assert policy is not None
        assert policy.evaluate("high", False, False) == "ask"
        assert policy.evaluate("critical", True, True) == "ask"
        assert f"Approval mode: {mode}" in result


def test_terminal_decision_flows_through_broker_and_prevents_self_approval(
    monkeypatch,
    tmp_path,
):
    from nous_runtime.cli import shell_v2
    from nous_runtime.governance import broker as broker_module

    broker = ApprovalBroker(store=GovernanceStore(str(tmp_path)))
    monkeypatch.setattr(broker_module, "get_broker", lambda store=None: broker)
    monkeypatch.setenv("NOUS_SUBJECT_ID", "requester")
    proposal = _proposal()
    request = broker.request_approval(
        run_id="run_terminal",
        task_id="task_terminal",
        proposal=proposal,
        context=_context(),
        requester="requester",
    )

    result = shell_v2._approval(["once", request.request_id])

    assert "DENIED" in result
    assert broker.get_pending() == []


def test_edit_revalidates_scope_and_leaves_original_request_pending(
    monkeypatch,
    tmp_path,
):
    from nous_runtime.cli import shell_v2
    from nous_runtime.governance import broker as broker_module
    from nous_runtime.governance import gate as gate_module

    broker = ApprovalBroker(store=GovernanceStore(str(tmp_path)))
    monkeypatch.setattr(broker_module, "get_broker", lambda store=None: broker)
    monkeypatch.setenv("NOUS_SUBJECT_ID", "reviewer")
    proposal = _proposal()
    assert broker._store.save_proposal(proposal.to_dict())
    request = broker.request_approval(
        run_id="run_terminal",
        task_id="task_terminal",
        proposal=proposal,
        context=_context(),
        requester="requester",
    )
    evaluated: list[ActionProposal] = []

    class Gate:
        def evaluate(self, edited: ActionProposal, context: AuthorizationContext):
            evaluated.append(edited)
            return SimpleNamespace(action_mode="ASK_APPROVAL", reason="Scope changed")

    monkeypatch.setattr(gate_module, "get_gate", lambda: Gate())

    result = shell_v2._edit_approval(
        request.request_id,
        ["affected_resources=docs/guide.md", "side_effect_class=local_write"],
    )

    assert evaluated
    assert evaluated[0].affected_resources == ("docs/guide.md",)
    assert "Revalidation: ASK_APPROVAL" in result
    assert broker.get_pending()[0]["request_id"] == request.request_id


def test_sprint12_commands_and_keyboard_mappings_are_registered():
    from nous_runtime.cli import shell_v2, terminal_ui

    assert {"tasks", "approval", "approve"} <= set(shell_v2.COMMANDS)
    assert terminal_ui._map_character("\x0f") == "CTRL_O"
    assert terminal_ui._map_character("\x10") == "CTRL_P"
    assert terminal_ui._map_character("\x12") == "CTRL_R"