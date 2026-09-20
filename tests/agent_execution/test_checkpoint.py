import pytest

from nous_runtime.agent.budget import AgentBudgetUsage
from nous_runtime.agent.checkpoint import AgentCheckpointManager
from nous_runtime.agent.errors import AgentCheckpointError, AgentLifecycleError
from nous_runtime.agent.execution_state import (
    AgentExecutionRecord,
    AgentExecutionState,
    transition_execution,
)
from nous_runtime.agent.runtime import AgentExecutionRuntime
from nous_runtime.agent.termination import TerminationPolicy
from nous_runtime.checkpoint import Checkpoint, InMemoryCheckpointStore


def checkpointed_execution() -> AgentExecutionRecord:
    execution = AgentExecutionRecord.create(task_id="task", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.STARTING)
    execution = transition_execution(execution, AgentExecutionState.RUNNING)
    return transition_execution(execution, AgentExecutionState.CHECKPOINTED)


def test_agent_checkpoint_round_trip() -> None:
    manager = AgentCheckpointManager()
    execution = checkpointed_execution()
    usage = AgentBudgetUsage(tokens=100, model_invocations=1, invocations=1)
    policy = TerminationPolicy(max_steps=5)

    checkpoint = manager.save(execution, usage, policy)
    restored = manager.restore(checkpoint.checkpoint_id)

    assert restored.execution.run_id == execution.run_id
    assert restored.execution.checkpoint_id == checkpoint.checkpoint_id
    assert restored.usage == usage
    assert restored.termination_policy == policy


def test_missing_agent_checkpoint_is_structured_error() -> None:
    with pytest.raises(AgentCheckpointError):
        AgentCheckpointManager().restore("missing")


def test_non_agent_checkpoint_is_rejected() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = store.save(Checkpoint(task_id="task", state={"x": 1}))

    with pytest.raises(AgentCheckpointError):
        AgentCheckpointManager(store).restore(checkpoint.checkpoint_id)


def test_runtime_restore_checks_agent_identity(agent_profile) -> None:
    runtime = AgentExecutionRuntime()
    execution = runtime.create(task_id="task", profile=agent_profile)
    runtime.start(execution.run_id)
    checkpoint = runtime.checkpoint(execution.run_id)
    wrong_profile = type(agent_profile)(
        manifest=type(agent_profile.manifest)(
            **{
                **agent_profile.manifest.__dict__,
                "identity": type(agent_profile.manifest.identity)(
                    agent_id="agent.other",
                    name="Other",
                ),
            }
        ),
        state=agent_profile.state,
    )

    with pytest.raises(AgentLifecycleError):
        runtime.restore(checkpoint.checkpoint_id, profile=wrong_profile)
