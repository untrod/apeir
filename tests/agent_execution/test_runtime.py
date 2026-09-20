from dataclasses import replace

import pytest

from nous_runtime.agent import (
    AgentExecutionRuntime,
    AgentExecutionState,
    InvocationStatus,
    TerminationPolicy,
)
from nous_runtime.agent.errors import AgentLifecycleError
from nous_runtime.agent.models import AgentBudget
from nous_runtime.execution import ExecutionContext
from nous_runtime.task import Task


def started_runtime(agent_profile, *, policy=None):
    runtime = AgentExecutionRuntime()
    execution = runtime.create(
        task_id="task-1",
        profile=agent_profile,
        context=ExecutionContext(task_id="task-1"),
        termination_policy=policy,
    )
    execution = runtime.start(execution.run_id)
    return runtime, execution


def test_runtime_create_start_and_events(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)

    assert execution.state is AgentExecutionState.RUNNING
    assert [event.event_type for event in runtime.context_for(execution.run_id).events] == [
        "agent.execution.created",
        "agent.execution.started",
    ]


def test_tool_invocation_boundary(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)

    record = runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        parameters={"message": "hello"},
        handler=lambda request: request.parameters["message"],
    )

    assert record.status is InvocationStatus.COMPLETED
    assert runtime.require(execution.run_id).step_count == 1
    assert runtime.budget_for(execution.run_id).usage.tool_invocations == 1


def test_model_invocation_boundary(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)

    record = runtime.invoke_model(
        execution.run_id,
        model_id="test-model",
        capability_id="model.reason",
        estimated_tokens=50,
        handler=lambda request: {"answer": 42},
    )

    assert record.status is InvocationStatus.COMPLETED
    assert runtime.budget_for(execution.run_id).usage.model_invocations == 1


def test_unbound_model_is_denied_without_handler_call(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)
    called = False

    def handler(_):
        nonlocal called
        called = True

    record = runtime.invoke_model(
        execution.run_id,
        model_id="unbound-model",
        capability_id="model.reason",
        handler=handler,
    )

    assert record.status is InvocationStatus.DENIED
    assert not called
    assert runtime.require(execution.run_id).state is AgentExecutionState.RUNNING


def test_budget_denial_terminates_execution(agent_profile) -> None:
    limited_manifest = replace(
        agent_profile.manifest,
        budget=AgentBudget(max_cost_usd=0.01, max_invocations=5),
    )
    limited_profile = replace(agent_profile, manifest=limited_manifest)
    runtime, execution = started_runtime(limited_profile)

    record = runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        estimated_cost_usd=1.0,
        handler=lambda request: None,
    )

    assert record.status is InvocationStatus.DENIED
    current = runtime.require(execution.run_id)
    assert current.state is AgentExecutionState.TERMINATED
    assert current.termination_reason == "budget_exhausted"


def test_handler_failure_fails_execution(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)

    def fail(_):
        raise RuntimeError("tool failed")

    record = runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        handler=fail,
    )

    assert record.status is InvocationStatus.FAILED
    assert runtime.require(execution.run_id).state is AgentExecutionState.FAILED


def test_max_steps_terminates_after_invocation(agent_profile) -> None:
    runtime, execution = started_runtime(
        agent_profile,
        policy=TerminationPolicy(max_steps=1),
    )
    runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        handler=lambda request: "ok",
    )

    current = runtime.require(execution.run_id)
    assert current.state is AgentExecutionState.TERMINATED
    assert current.termination_reason == "max_steps"


def test_checkpoint_resume_and_restore(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)
    runtime.invoke_tool(
        execution.run_id,
        tool_id="tool.echo",
        capability_id="tool.echo",
        handler=lambda request: "ok",
    )

    checkpoint = runtime.checkpoint(execution.run_id)
    assert runtime.require(execution.run_id).state is AgentExecutionState.CHECKPOINTED
    resumed = runtime.resume(execution.run_id)
    assert resumed.state is AgentExecutionState.RUNNING

    restored_runtime = AgentExecutionRuntime(checkpoints=runtime.checkpoints)
    restored = restored_runtime.restore(
        checkpoint.checkpoint_id,
        profile=agent_profile,
    )
    assert restored.run_id == execution.run_id
    assert restored.state is AgentExecutionState.CHECKPOINTED
    assert restored_runtime.budget_for(restored.run_id).usage.tool_invocations == 1


def test_complete_and_cancel(agent_profile) -> None:
    runtime, execution = started_runtime(agent_profile)
    completed = runtime.complete(execution.run_id, message="done")
    assert completed.state is AgentExecutionState.COMPLETED

    second = runtime.create(task_id="task-2", profile=agent_profile)
    cancelled = runtime.cancel(second.run_id, message="cancelled")
    assert cancelled.state is AgentExecutionState.CANCELLED


def test_non_running_execution_cannot_invoke(agent_profile) -> None:
    runtime = AgentExecutionRuntime()
    execution = runtime.create(task_id="task", profile=agent_profile)

    with pytest.raises(AgentLifecycleError):
        runtime.invoke_tool(
            execution.run_id,
            tool_id="tool.echo",
            capability_id="tool.echo",
            handler=lambda request: None,
        )


def test_task_lifecycle_is_not_mutated(agent_profile) -> None:
    task = Task(id="task-1", name="Agent task")
    original_status = task.status
    runtime, execution = started_runtime(agent_profile)
    runtime.complete(execution.run_id)

    assert task.status is original_status
