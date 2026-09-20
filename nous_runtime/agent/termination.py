"""Termination conditions and deterministic decision rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping

from nous_runtime.agent.budget import AgentBudgetLedger
from nous_runtime.agent.execution_state import (
    AgentExecutionRecord,
    AgentExecutionState,
)


class TerminationReason(str, Enum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    MAX_STEPS = "max_steps"
    CANCELLED = "cancelled"
    ERROR = "error"
    EXTERNAL_SIGNAL = "external_signal"
    CONDITION_MET = "condition_met"


@dataclass(frozen=True)
class TerminationPolicy:
    max_steps: int = 0
    max_runtime_ms: int = 0
    stop_on_invocation_failure: bool = True
    require_completion_signal: bool = False
    version: str = "agent-termination-v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "TerminationPolicy":
        data = data or {}
        return cls(
            max_steps=int(data.get("max_steps") or 0),
            max_runtime_ms=int(data.get("max_runtime_ms") or 0),
            stop_on_invocation_failure=bool(
                data.get("stop_on_invocation_failure", True)
            ),
            require_completion_signal=bool(
                data.get("require_completion_signal", False)
            ),
            version=str(data.get("version") or "agent-termination-v1"),
        )


@dataclass(frozen=True)
class TerminationDecision:
    terminate: bool
    reason: TerminationReason | None = None
    message: str = ""


class TerminationController:
    def evaluate(
        self,
        execution: AgentExecutionRecord,
        policy: TerminationPolicy,
        ledger: AgentBudgetLedger,
    ) -> TerminationDecision:
        if execution.state in {
            AgentExecutionState.COMPLETED,
            AgentExecutionState.FAILED,
            AgentExecutionState.CANCELLED,
            AgentExecutionState.TIMED_OUT,
            AgentExecutionState.TERMINATED,
        }:
            return TerminationDecision(
                True,
                _state_reason(execution.state),
                execution.termination_message,
            )
        exceeded = ledger.exceeded_limits()
        if exceeded:
            return TerminationDecision(
                True,
                TerminationReason.BUDGET_EXHAUSTED,
                "budget limits exceeded: " + ",".join(exceeded),
            )
        usage = ledger.usage
        if policy.max_runtime_ms and usage.runtime_ms >= policy.max_runtime_ms:
            return TerminationDecision(
                True,
                TerminationReason.TIMEOUT,
                "maximum runtime reached",
            )
        if policy.max_steps and execution.step_count >= policy.max_steps:
            return TerminationDecision(
                True,
                TerminationReason.MAX_STEPS,
                "maximum execution steps reached",
            )
        if (
            policy.stop_on_invocation_failure
            and execution.invocations
            and execution.invocations[-1].status.value == "failed"
        ):
            return TerminationDecision(
                True,
                TerminationReason.ERROR,
                "invocation failed",
            )
        return TerminationDecision(False)


def _state_reason(state: AgentExecutionState) -> TerminationReason:
    return {
        AgentExecutionState.COMPLETED: TerminationReason.COMPLETED,
        AgentExecutionState.FAILED: TerminationReason.ERROR,
        AgentExecutionState.CANCELLED: TerminationReason.CANCELLED,
        AgentExecutionState.TIMED_OUT: TerminationReason.TIMEOUT,
        AgentExecutionState.TERMINATED: TerminationReason.CONDITION_MET,
    }[state]


__all__ = [
    "TerminationController",
    "TerminationDecision",
    "TerminationPolicy",
    "TerminationReason",
]
