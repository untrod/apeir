from nous_runtime.agent.budget import AgentBudgetLedger
from nous_runtime.agent.execution_state import (
    AgentExecutionRecord,
    AgentExecutionState,
    InvocationKind,
    InvocationRecord,
    InvocationStatus,
    transition_execution,
)
from nous_runtime.agent.models import AgentBudget
from nous_runtime.agent.termination import (
    TerminationController,
    TerminationPolicy,
    TerminationReason,
)


def running_execution() -> AgentExecutionRecord:
    execution = AgentExecutionRecord.create(task_id="task", agent_id="agent.x")
    execution = transition_execution(execution, AgentExecutionState.STARTING)
    return transition_execution(execution, AgentExecutionState.RUNNING)


def invocation(status: InvocationStatus) -> InvocationRecord:
    return InvocationRecord(
        "invocation",
        InvocationKind.TOOL,
        "tool.echo",
        "tool.echo",
        status,
        "start",
        "end",
    )


def test_max_steps_termination() -> None:
    execution = running_execution().with_invocation(
        invocation(InvocationStatus.COMPLETED)
    )
    decision = TerminationController().evaluate(
        execution,
        TerminationPolicy(max_steps=1),
        AgentBudgetLedger(AgentBudget(max_invocations=5)),
    )

    assert decision.terminate
    assert decision.reason is TerminationReason.MAX_STEPS


def test_runtime_timeout_termination() -> None:
    ledger = AgentBudgetLedger(
        AgentBudget(max_runtime_ms=1000, max_invocations=5)
    )
    ledger.consume(runtime_ms=500)
    decision = TerminationController().evaluate(
        running_execution(),
        TerminationPolicy(max_runtime_ms=500),
        ledger,
    )

    assert decision.reason is TerminationReason.TIMEOUT


def test_failed_invocation_termination() -> None:
    execution = running_execution().with_invocation(
        invocation(InvocationStatus.FAILED)
    )
    decision = TerminationController().evaluate(
        execution,
        TerminationPolicy(stop_on_invocation_failure=True),
        AgentBudgetLedger(AgentBudget(max_invocations=5)),
    )

    assert decision.reason is TerminationReason.ERROR


def test_no_condition_keeps_execution_running() -> None:
    decision = TerminationController().evaluate(
        running_execution(),
        TerminationPolicy(max_steps=5),
        AgentBudgetLedger(AgentBudget(max_invocations=5)),
    )

    assert not decision.terminate
    assert decision.reason is None


def test_terminal_state_is_reported() -> None:
    execution = transition_execution(
        running_execution(),
        AgentExecutionState.COMPLETED,
    )
    decision = TerminationController().evaluate(
        execution,
        TerminationPolicy(),
        AgentBudgetLedger(AgentBudget()),
    )

    assert decision.reason is TerminationReason.COMPLETED


def test_termination_policy_round_trip() -> None:
    policy = TerminationPolicy(
        max_steps=4,
        max_runtime_ms=500,
        stop_on_invocation_failure=False,
        require_completion_signal=True,
    )

    assert TerminationPolicy.from_dict(policy.to_dict()) == policy
