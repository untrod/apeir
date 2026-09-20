from __future__ import annotations

import time

import pytest

from nous_runtime.workflow import StepType, TriggerType, WorkflowDefinition, WorkflowRuntime, WorkflowState, WorkflowStep, WorkflowValidationError


def definition(*steps):
    return WorkflowDefinition("workflow.test", "1.0.0", TriggerType.MANUAL, tuple(steps))


def test_linear_and_parallel_workflow_with_history(tmp_path):
    calls = []
    def handler(step, context):
        calls.append(step.step_id)
        return {"step": step.step_id}
    runtime = WorkflowRuntime(str(tmp_path), handlers={"capability": handler}, max_parallel=2)
    spec = definition(
        WorkflowStep("a", StepType.CAPABILITY, "capability"),
        WorkflowStep("b", StepType.CAPABILITY, "capability", ("a",)),
        WorkflowStep("c", StepType.CAPABILITY, "capability", ("a",)),
        WorkflowStep("d", StepType.CAPABILITY, "capability", ("b", "c")),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, idempotency_key="once")
    assert run.state == WorkflowState.COMPLETED
    assert set(calls) == {"a", "b", "c", "d"}
    assert runtime.store.history(spec.workflow_id)[0].run_id == run.run_id
    assert runtime.start(spec.workflow_id, spec.version, idempotency_key="once").run_id == run.run_id


def test_conditional_branch_is_skipped(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(WorkflowStep("condition", StepType.CONDITION, params={"input": "enabled", "equals": True}))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, {"enabled": False})
    assert run.state == WorkflowState.COMPLETED
    assert run.step_states["condition"] == "skipped"


def test_approval_pause_restart_and_resume(tmp_path):
    spec = definition(WorkflowStep("approve", StepType.APPROVAL), WorkflowStep("after", StepType.TRANSFORM, depends_on=("approve",), params={"value": "done"}))
    first = WorkflowRuntime(str(tmp_path))
    first.register(spec)
    waiting = first.start(spec.workflow_id, spec.version)
    assert waiting.state == WorkflowState.WAITING_APPROVAL
    second = WorkflowRuntime(str(tmp_path))
    resumed = second.resume(waiting.run_id, approved_steps=("approve",))
    assert resumed.state == WorkflowState.COMPLETED
    assert resumed.outputs["after"]["value"] == "done"


def test_retry_then_success(tmp_path):
    attempts = {"count": 0}
    def flaky(step, context):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return {"ok": True}
    runtime = WorkflowRuntime(str(tmp_path), handlers={"flaky": flaky})
    spec = definition(WorkflowStep("retry", StepType.CAPABILITY, "flaky", retries=1))
    runtime.register(spec)
    assert runtime.start(spec.workflow_id, spec.version).state == WorkflowState.COMPLETED
    assert attempts["count"] == 2


def test_timeout_and_cancel(tmp_path):
    def slow(step, context):
        time.sleep(0.05)
        return {}
    runtime = WorkflowRuntime(str(tmp_path), handlers={"slow": slow})
    spec = definition(WorkflowStep("slow", StepType.CAPABILITY, "slow", timeout_seconds=0.001))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state == WorkflowState.FAILED
    assert "timed out" in run.error
    cancelled = runtime.cancel(run.run_id)
    assert cancelled.state == WorkflowState.FAILED


def test_failed_compensation_is_recorded(tmp_path):
    def ok(step, context):
        return {"ok": True}
    def fail(step, context):
        raise RuntimeError("execution failed")
    def compensate(step, context):
        raise RuntimeError("compensation failed")
    runtime = WorkflowRuntime(str(tmp_path), handlers={"ok": ok, "fail": fail, "undo": compensate})
    spec = definition(WorkflowStep("first", StepType.CAPABILITY, "ok", compensation="undo"), WorkflowStep("second", StepType.CAPABILITY, "fail", depends_on=("first",)))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state == WorkflowState.COMPENSATION_FAILED
    assert runtime.store.checkpoints(run.run_id)["compensate:first"]["status"] == "failed"


def test_cycle_and_unbounded_retry_are_rejected(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    with pytest.raises(WorkflowValidationError, match="cycle"):
        runtime.register(definition(WorkflowStep("a", StepType.TRANSFORM, depends_on=("b",)), WorkflowStep("b", StepType.TRANSFORM, depends_on=("a",))))
    with pytest.raises(WorkflowValidationError, match="retries"):
        runtime.register(definition(WorkflowStep("a", StepType.TRANSFORM, retries=100)))


def test_connector_agent_and_knowledge_steps_use_registered_handlers(tmp_path):
    seen = []
    def handler(step, context):
        seen.append(step.step_type.value)
        return {"ok": True}
    runtime = WorkflowRuntime(str(tmp_path), handlers={"connector": handler, "agent": handler, "knowledge.search": handler})
    spec = definition(
        WorkflowStep("connector", StepType.CONNECTOR, "connector"),
        WorkflowStep("knowledge", StepType.CAPABILITY, "knowledge.search", depends_on=("connector",)),
        WorkflowStep("agent", StepType.AGENT, "agent", depends_on=("knowledge",)),
    )
    runtime.register(spec)
    assert runtime.start(spec.workflow_id, spec.version).state == WorkflowState.COMPLETED
    assert seen == ["connector", "capability", "agent"]