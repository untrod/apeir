import pytest

from nous_runtime.agent.errors import AgentLifecycleError
from nous_runtime.agent.execution_state import (
    AgentExecutionRecord,
    AgentExecutionState,
    InvocationKind,
    InvocationRecord,
    InvocationStatus,
    transition_execution,
)


def test_execution_lifecycle_start_and_complete() -> None:
    execution = AgentExecutionRecord.create(task_id="task-1", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.STARTING)
    execution = transition_execution(execution, AgentExecutionState.RUNNING)
    execution = transition_execution(execution, AgentExecutionState.COMPLETED)

    assert execution.state is AgentExecutionState.COMPLETED
    assert execution.started_at
    assert execution.ended_at


def test_terminal_execution_rejects_restart() -> None:
    execution = AgentExecutionRecord.create(task_id="task-1", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.CANCELLED)

    with pytest.raises(AgentLifecycleError):
        transition_execution(execution, AgentExecutionState.STARTING)


def test_wait_checkpoint_and_resume_transitions() -> None:
    execution = AgentExecutionRecord.create(task_id="task-1", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.STARTING)
    execution = transition_execution(execution, AgentExecutionState.RUNNING)
    execution = transition_execution(execution, AgentExecutionState.WAITING)
    execution = transition_execution(execution, AgentExecutionState.CHECKPOINTED)
    execution = transition_execution(execution, AgentExecutionState.RUNNING)

    assert execution.state is AgentExecutionState.RUNNING


def test_invocation_record_increments_step_and_round_trips() -> None:
    execution = AgentExecutionRecord.create(task_id="task-1", agent_id="agent.x")
    invocation = InvocationRecord(
        "invoke-1",
        InvocationKind.TOOL,
        "tool.echo",
        "tool.echo",
        InvocationStatus.COMPLETED,
        "start",
        "end",
    )

    updated = execution.with_invocation(invocation)
    restored = AgentExecutionRecord.from_dict(updated.to_dict())

    assert restored.step_count == 1
    assert restored.invocations[0] == invocation


def test_execution_transition_records_termination_reason() -> None:
    execution = AgentExecutionRecord.create(task_id="task-1", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.STARTING)
    execution = transition_execution(execution, AgentExecutionState.RUNNING)
    execution = transition_execution(
        execution,
        AgentExecutionState.TERMINATED,
        reason="max_steps",
        message="limit reached",
    )

    assert execution.termination_reason == "max_steps"
    assert execution.termination_message == "limit reached"
