"""Shared dependency edges must not move execution before an approval barrier."""

from itertools import permutations

import pytest

from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.plan import Task
from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowStep,
)


@pytest.mark.parametrize("order", list(permutations(("source", "review", "effect"))))
def test_transitive_and_direct_edges_respect_all_dependencies(order):
    tasks = {
        "source": Task("Read", task_id="source"),
        "review": Task("Review", task_id="review", depends_on=["source"]),
        "effect": Task("Apply", task_id="effect", depends_on=["source", "review"]),
    }
    graph = TaskGraph()
    graph.build([tasks[key] for key in order])
    assert [[node.task_id for node in level] for level in graph.level_order()] == [
        ["source"],
        ["review"],
        ["effect"],
    ]


@pytest.mark.parametrize("fault", ["missing", "cycle", "duplicate"])
def test_invalid_graph_does_not_publish_execution_waves(fault):
    graph = TaskGraph()
    tasks = [
        Task("A", task_id="a", depends_on=["unknown" if fault == "missing" else "b"]),
        Task("B", task_id="b", depends_on=["a"]),
    ]
    if fault == "duplicate":
        tasks = [Task("A", task_id="a"), Task("A again", task_id="a")]
    with pytest.raises(ValueError):
        graph.build(tasks)


def test_original_workflow_cannot_pass_an_approval_via_shorter_edge(tmp_path):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": lambda *_: calls.append("effect") or {"result": True}},
    )
    definition = WorkflowDefinition(
        "barrier.workflow",
        "1",
        TriggerType.MANUAL,
        (
            WorkflowStep("source", StepType.TRANSFORM, params={"value": "reviewed"}),
            WorkflowStep("review", StepType.APPROVAL, depends_on=("source",)),
            WorkflowStep("effect", StepType.CAPABILITY, "effect", ("source", "review")),
        ),
    )
    runtime.register(definition)
    run = runtime.start(definition.workflow_id, definition.version)
    assert run.state.value == "waiting_approval" and calls == []
    assert "effect" not in runtime.store.checkpoints(run.run_id)
    assert runtime.resume(run.run_id).state.value == "waiting_approval" and calls == []
    assert (
        runtime.resume(run.run_id, approved_steps=("review",)).state.value
        == "completed"
    )
    assert calls == ["effect"]


def test_legacy_completed_step_before_unfinished_dependency_cannot_be_resumed(tmp_path):
    from nous_runtime.workflow.store import binding_digest

    runtime = WorkflowRuntime(str(tmp_path))
    child = WorkflowStep("effect", StepType.TRANSFORM, depends_on=("source", "review"))
    definition = WorkflowDefinition(
        "legacy.barrier",
        "1",
        TriggerType.MANUAL,
        (
            WorkflowStep("source", StepType.TRANSFORM, params={"value": 1}),
            WorkflowStep("review", StepType.APPROVAL, depends_on=("source",)),
            child,
        ),
    )
    runtime.register(definition)
    run = runtime.start(definition.workflow_id, definition.version)
    # Retain the inconsistent historical evidence instead of repairing it into
    # a successful new run or repeating an effect whose ordering is unknown.
    runtime.store.checkpoint(
        run.run_id,
        child.step_id,
        {
            "status": "completed",
            "attempts": 1,
            "binding_digest": runtime._step_binding(run, child),
            "output": {"recorded": True},
            "output_digest": binding_digest({"recorded": True}),
        },
    )
    restored = WorkflowRuntime(str(tmp_path)).resume(
        run.run_id, approved_steps=("review",)
    )
    assert restored.state.value == "unknown"
    assert (
        runtime.store.checkpoints(run.run_id)["review"]["status"] == "waiting_approval"
    )
