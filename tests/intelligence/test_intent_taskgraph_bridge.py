from __future__ import annotations

from threading import Lock
from time import sleep

from nous_runtime.intelligence.planning.parallel import (
    ParallelTaskPlanner,
)
from nous_runtime.intelligence.planning.workflow import PlanWorkflowBridge
from nous_runtime.interaction.intent import EXECUTE
from nous_runtime.interaction.intent_resolver import IntentResolver
from nous_runtime.interaction.models import IntentRequest
from nous_runtime.workflow.models import WorkflowState


def test_intent_resolver_understands_engineering_goal():
    resolution = IntentResolver().resolve(
        IntentRequest("帮我设计智能坐垫系统，使用 STM32 和传感器")
    )

    assert resolution.decision.intent == EXECUTE
    assert not resolution.decision.requires_confirmation
    assert resolution.analysis.task_type == "engineering_design"
    assert resolution.analysis.complexity == "high"
    assert {
        "embedded",
        "hardware",
        "coding",
        "documentation",
    }.issubset(resolution.analysis.required_capabilities)


def test_parallel_planner_builds_dag_and_workflow_executes_it(
    tmp_path,
):
    resolution = IntentResolver().resolve(
        IntentRequest("Design an embedded sensor system")
    )
    plan = ParallelTaskPlanner().generate(resolution.analysis)

    execution_ids = [
        step.step_id
        for step in plan.steps
        if step.step_id.startswith("execute_")
    ]
    assert all(
        plan.dependencies[step_id] == ("analyze",)
        for step_id in execution_ids
    )
    assert plan.dependencies["verify"] == tuple(execution_ids)

    lock = Lock()
    active = 0
    maximum = 0

    def handler(step, context):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        if step.step_id.startswith("execute_"):
            sleep(0.02)
        with lock:
            active -= 1
        return {"step": step.step_id}

    handlers = {
        step.capability: handler
        for step in plan.steps
    }
    run = PlanWorkflowBridge().execute(
        plan,
        root=str(tmp_path),
        handlers=handlers,
        max_parallel=8,
    )

    assert run.state is WorkflowState.COMPLETED
    assert maximum >= 2
    assert set(run.outputs) == {
        step.step_id for step in plan.steps
    }


def test_plan_workflow_bridge_preserves_human_approval(tmp_path):
    resolution = IntentResolver().resolve(
        IntentRequest("Design a sensor system")
    )
    plan = ParallelTaskPlanner().generate(resolution.analysis)
    first = plan.steps[1]
    first.metadata["approval_required"] = True

    run = PlanWorkflowBridge().execute(
        plan,
        root=str(tmp_path),
        handlers={
            step.capability: (
                lambda step, context: {"step": step.step_id}
            )
            for step in plan.steps
        },
    )

    assert run.state is WorkflowState.WAITING_APPROVAL
    assert run.step_states[first.step_id] == "waiting_approval"
