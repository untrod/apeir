from __future__ import annotations

from nous_runtime.events import RunState
from nous_runtime.planner import GoalStatus
from nous_runtime.work import (
    DecisionStatus,
    PlanStepDraft,
    WorkDecision,
    WorkHarness,
)


class StubTools:
    def __init__(self, results=None):
        self.results = list(results or ({"ok": True},))
        self.calls: list[tuple[str, dict]] = []

    def specifications(self):
        return (
            {
                "type": "function",
                "function": {
                    "name": "workspace_action",
                    "description": "bounded test action",
                    "parameters": {"type": "object"},
                },
            },
        )

    def execute(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return self.results.pop(0) if self.results else {"ok": True}


class DispatchInspectingTools(StubTools):
    def __init__(self, harness, run_id):
        super().__init__()
        self.harness = harness
        self.run_id = run_id

    def require(self, _name):
        return type(
            "Definition",
            (),
            {"effect_class": "write", "capability_id": "filesystem.write"},
        )()

    def execute(self, name, arguments):
        durable = self.harness.require(self.run_id)
        assert durable.pending_action["tool"] == name
        assert durable.pending_action["effect_class"] == "write"
        result = super().execute(name, arguments)
        result["change"] = {
            "path": "result.txt",
            "operation": "write",
            "before_digest": "",
            "after_digest": "sha256:" + "a" * 64,
            "lines_added": 1,
            "lines_removed": 0,
            "work_id": "",
            "tool_call_id": "",
        }
        return result


def test_simple_work_skips_plan_and_completes(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain recursion clearly")

    assert created.analysis.needs_plan is False
    assert created.plan is None

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE,
            "Explanation is ready",
            output="Recursion solves a problem using smaller instances of itself.",
        ),
    )

    assert completed.state is RunState.COMPLETED
    assert completed.goal.status is GoalStatus.COMPLETED
    assert harness.require(created.run_id).result.startswith("Recursion")
    assert harness.events.get_run(created.run_id).state is RunState.COMPLETED


def test_kernel_unavailable_requires_recovery_and_resumes_same_work(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one local module")

    def unavailable(_context):
        raise RuntimeError(
            "APEIR Kernel is unavailable; direct provider execution is disabled"
        )

    interrupted = harness.run(created.run_id, deliberator=unavailable)

    assert interrupted.state is RunState.RECOVERY_REQUIRED
    assert interrupted.terminal is False
    assert interrupted.agent_run_id == ""
    assert harness.events.load_events(created.run_id)[-1].event_type == (
        "work.recovery.required"
    )

    recovered = harness.resume(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE,
            "Runtime recovered and the explanation is complete",
            output="done",
        ),
    )

    assert recovered.run_id == created.run_id
    assert recovered.state is RunState.COMPLETED


def test_resume_migrates_recoverable_terminal_runtime_failure(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one local module")
    harness.fail(
        created.run_id,
        reason="APEIR Kernel is unavailable; direct provider execution is disabled",
    )

    recovered = harness.resume(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE,
            "Recovered the previously terminal runtime failure",
            output="done",
        ),
    )

    assert recovered.run_id == created.run_id
    assert recovered.state is RunState.COMPLETED
    events = harness.events.load_events(created.run_id)
    assert any(event.event_type == "work.recovery.required" for event in events)


def test_provider_transport_failure_is_recoverable() -> None:
    assert WorkHarness.is_recoverable_runtime_failure(
        "provider process error: error sending request for url "
        "(http://127.0.0.1:11434/v1/chat/completions)"
    )
    assert WorkHarness.is_recoverable_runtime_failure(
        "all safe model routes failed: local/model: invocation timed out; "
        "overall request timed out"
    )


def test_recovery_uses_monotonic_checkpoint_sequence(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain checkpoint ordering")
    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: WorkDecision(
            DecisionStatus.COMPLETE,
            "The final result is durable",
            output="latest",
        ),
    )

    restored = WorkHarness(tmp_path).require(created.run_id)

    assert restored.result == "latest"
    assert restored.checkpoint_sequence == completed.checkpoint_sequence
    assert restored.state is RunState.COMPLETED


def test_tool_failure_causes_reanalysis_and_versioned_replan(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create(
        "Fix the code in this project and run targeted tests",
        completion_criteria=("targeted verification passes",),
    )
    tools = StubTools(({"ok": False, "error": "test failed"}, {"ok": True}))
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Run the current implementation check",
                tool_name="workspace_action",
                step_id="execute_1",
            ),
            WorkDecision(
                DecisionStatus.REPLAN,
                "The first check exposed a different implementation path",
                reason="test failure changed the implementation hypothesis",
                plan_revision_required=True,
                replacement_steps=(
                    PlanStepDraft(
                        "Apply the corrected implementation",
                        "workspace_action",
                        "fix",
                    ),
                    PlanStepDraft(
                        "Verify the corrected implementation",
                        "evaluation",
                        "verify",
                        ("fix",),
                    ),
                ),
            ),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Apply the corrected implementation",
                tool_name="workspace_action",
                step_id="fix",
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "Implementation and verification are complete",
                output={"changed": True},
            ),
        )
    )
    contexts = []

    def deliberate(context):
        contexts.append(context)
        return next(decisions)

    completed = harness.run(
        created.run_id,
        deliberator=deliberate,
        tools=tools,
        verifier=lambda _context: {"ok": True, "checks": ["targeted"]},
    )

    assert completed.state is RunState.COMPLETED
    assert len(tools.calls) == 2
    assert completed.plan is not None
    assert completed.plan.revision == 2
    assert completed.plan.revision_history[0].reason == (
        "test failure changed the implementation hypothesis"
    )
    assert any(
        "tool workspace_action failed" in item.reanalysis_reason for item in contexts
    )
    assert any(item.get("kind") == "verification" for item in completed.observations)


def test_restart_resume_reassesses_without_replaying_last_tool(tmp_path):
    tools = StubTools(({"ok": True, "value": "durable-effect"},))
    first = WorkHarness(tmp_path)
    created = first.create("Inspect one value and wait for my confirmation")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect the requested value",
                tool_name="workspace_action",
            ),
            WorkDecision(
                DecisionStatus.ASK_USER,
                "The value is available",
                next_action="Confirm whether to finish",
            ),
        )
    )
    waiting = first.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
    )

    assert waiting.state is RunState.WAITING_USER
    assert len(tools.calls) == 1

    restarted = WorkHarness(tmp_path)
    seen_contexts = []

    def finish(context):
        seen_contexts.append(context)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "The resumed task was re-evaluated and is complete",
            output="done",
        )

    completed = restarted.resume(
        created.run_id,
        deliberator=finish,
        tools=tools,
    )

    assert completed.state is RunState.COMPLETED
    assert len(tools.calls) == 1
    assert seen_contexts[0].recovering is True
    assert "re-evaluate" in seen_contexts[0].reanalysis_reason


def test_resume_reattaches_persistent_shell_without_replaying_start(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Run a persistent targeted test")
    created.pending_action = {
        "tool": "shell_start",
        "step_id": "run-tests",
        "arguments_digest": "sha256:" + "c" * 64,
        "effect_class": "execute",
        "capability_id": "process.session.start",
        "action_sequence": 1,
        "recovery_policy": "kernel_or_manual",
    }
    harness.persist_progress(
        created,
        "work.action.dispatched",
        {"action": dict(created.pending_action)},
    )

    class RecoveringShellTools(StubTools):
        def execute(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            assert name == "shell_recover"
            return {
                "ok": True,
                "found": True,
                "recovery_required": False,
                "automatic_replay": False,
                "session_id": "ps_existing",
                "state": "RUNNING",
                "artifacts": {},
            }

    tools = RecoveringShellTools()
    contexts = []

    def finish(context):
        contexts.append(context)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "The existing process was inspected without replay",
            output="reattached",
        )

    completed = WorkHarness(tmp_path).resume(
        created.run_id,
        deliberator=finish,
        tools=tools,
    )

    assert completed.state is RunState.COMPLETED
    assert completed.pending_action == {}
    assert tools.calls == [
        (
            "shell_recover",
            {"work_id": created.run_id, "action_sequence": 1},
        )
    ]
    assert contexts[0].recovering is True
    assert "without replay" in contexts[0].reanalysis_reason
    assert any(item.get("recovered") for item in completed.observations)


def test_steering_updates_same_goal_and_plan_revision_durably(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Fix the code in this repository")
    original_goal_id = created.goal.goal_id
    original_revision = created.plan.revision

    steered = harness.steer(
        created.run_id,
        "Do not change the database layer",
        constraints={"forbidden_paths": ["database/"]},
    )
    restored = WorkHarness(tmp_path).require(created.run_id)

    assert steered.goal.goal_id == original_goal_id
    assert restored.goal.goal_id == original_goal_id
    assert restored.goal.constraints["forbidden_paths"] == ["database/"]
    assert restored.goal.requirements[-1] == "Do not change the database layer"
    assert restored.plan.revision == original_revision + 1
    assert restored.state is RunState.REPLANNING


def test_pause_during_deliberation_discards_stale_tool_decision(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect one workspace value")
    tools = StubTools()

    def pause_then_decide(_context):
        harness.pause(created.run_id, reason="user changed direction")
        return WorkDecision(
            DecisionStatus.CONTINUE,
            "Use the now-stale action",
            tool_name="workspace_action",
        )

    paused = harness.run(
        created.run_id,
        deliberator=pause_then_decide,
        tools=tools,
    )

    assert paused.state is RunState.PAUSED
    assert tools.calls == []
    restored = WorkHarness(tmp_path).require(created.run_id)
    assert restored.state is RunState.PAUSED
    assert restored.agent_checkpoint_id


def test_completion_reverifies_after_a_later_action(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create(
        "Fix code and run targeted tests",
        completion_criteria=("targeted verification passes",),
    )
    harness.replace_plan(
        created,
        (
            PlanStepDraft("Apply the change", "workspace_action", "change"),
            PlanStepDraft("Verify the change", "evaluation", "verify", ("change",)),
        ),
        reason="focus the verification freshness test",
    )
    tools = StubTools(({"ok": True}, {"ok": True}))
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Apply the change",
                tool_name="workspace_action",
                step_id="change",
            ),
            WorkDecision(DecisionStatus.VERIFY, "Check the first result"),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Apply a follow-up change",
                tool_name="workspace_action",
                step_id="change",
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "The follow-up change is verified",
                output="done",
            ),
        )
    )
    verification_calls = []

    def verify(_context):
        verification_calls.append(True)
        return {"ok": True}

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
        verifier=verify,
    )

    assert completed.state is RunState.COMPLETED
    assert completed.action_sequence == 2
    assert len(verification_calls) == 2


def test_tool_dispatch_is_durable_before_invocation_and_closed_by_observation(
    tmp_path,
):
    harness = WorkHarness(tmp_path)
    created = harness.create("Perform one durable workspace action")
    tools = DispatchInspectingTools(harness, created.run_id)
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Apply one bounded change",
                tool_name="workspace_action",
            ),
            WorkDecision(
                DecisionStatus.COMPLETE,
                "The observed action is complete",
                output="done",
            ),
        )
    )

    completed = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=tools,
    )

    assert completed.pending_action == {}
    event_types = [
        event.event_type for event in harness.events.load_events(created.run_id)
    ]
    assert event_types.index("work.action.dispatched") < event_types.index(
        "work.observing"
    )
    change = next(
        item["result"]["change"]
        for item in completed.observations
        if item.get("kind") == "tool"
    )
    assert change["work_id"] == created.run_id
    assert change["tool_call_id"].startswith("invoke_")
