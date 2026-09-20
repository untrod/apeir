import pytest

from nous_runtime.core.errors import CapabilityError
from nous_runtime.intelligence.planning import (
    PlanExecutorBridge,
    PlanStep,
    TaskPlan,
    TaskPlanner,
)
from nous_runtime.intelligence.task import analyze_task
from nous_runtime.task import TaskManager


def test_planner_generates_ordered_dependencies() -> None:
    plan = TaskPlanner().generate(analyze_task("Debug Python code", task_id="t1"))

    assert [step.step_id for step in plan.steps] == ["analyze", "execute_1", "execute_2", "verify"]
    assert plan.dependencies["execute_1"] == ("analyze",)
    assert plan.dependencies["execute_2"] == ("execute_1",)
    assert plan.dependencies["verify"] == ("execute_2",)


def test_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(CapabilityError):
        TaskPlan("t1", (PlanStep("one", "One"),), {"one": ("missing",)})


def test_plan_bridge_prepares_execution_context() -> None:
    manager = TaskManager()
    task = manager.create("Debug code")
    plan = TaskPlanner().generate(analyze_task(task))

    context = PlanExecutorBridge(manager).prepare(plan, provider="openai")

    assert context.task_id == task.id
    assert context.provider == "openai"
    assert context.metadata["plan"]["plan_id"] == plan.plan_id
    assert context.events[0].event_type == "task.plan.prepared"
