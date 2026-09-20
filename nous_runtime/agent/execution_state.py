"""Long-lived Agent execution instance state and invocation audit records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from nous_runtime.agent.errors import AgentLifecycleError


def execution_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class AgentExecutionState(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    CHECKPOINTED = "CHECKPOINTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    TERMINATED = "TERMINATED"


class InvocationKind(str, Enum):
    TOOL = "tool"
    MODEL = "model"


class InvocationStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True)
class InvocationRecord:
    invocation_id: str
    kind: InvocationKind
    target: str
    capability_id: str
    status: InvocationStatus
    started_at: str
    completed_at: str
    estimated_cost_usd: float = 0.0
    estimated_tokens: int = 0
    duration_ms: int = 0
    error_code: str = ""
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "kind": self.kind.value,
            "target": self.target,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_tokens": self.estimated_tokens,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvocationRecord":
        return cls(
            invocation_id=str(data.get("invocation_id") or ""),
            kind=InvocationKind(str(data.get("kind") or "tool")),
            target=str(data.get("target") or ""),
            capability_id=str(data.get("capability_id") or ""),
            status=InvocationStatus(str(data.get("status") or "failed")),
            started_at=str(data.get("started_at") or ""),
            completed_at=str(data.get("completed_at") or ""),
            estimated_cost_usd=float(data.get("estimated_cost_usd") or 0.0),
            estimated_tokens=int(data.get("estimated_tokens") or 0),
            duration_ms=int(data.get("duration_ms") or 0),
            error_code=str(data.get("error_code") or ""),
            message=str(data.get("message") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AgentExecutionRecord:
    run_id: str
    task_id: str
    agent_id: str
    state: AgentExecutionState = AgentExecutionState.CREATED
    created_at: str = field(default_factory=execution_timestamp)
    updated_at: str = field(default_factory=execution_timestamp)
    started_at: str = ""
    ended_at: str = ""
    step_count: int = 0
    checkpoint_id: str = ""
    termination_reason: str = ""
    termination_message: str = ""
    invocations: tuple[InvocationRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        agent_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AgentExecutionRecord":
        return cls(
            run_id=f"agent_run_{uuid.uuid4().hex}",
            task_id=str(task_id),
            agent_id=str(agent_id),
            metadata=dict(metadata or {}),
        )

    def with_invocation(self, invocation: InvocationRecord) -> "AgentExecutionRecord":
        return replace(
            self,
            invocations=(*self.invocations, invocation),
            step_count=self.step_count + 1,
            updated_at=execution_timestamp(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "step_count": self.step_count,
            "checkpoint_id": self.checkpoint_id,
            "termination_reason": self.termination_reason,
            "termination_message": self.termination_message,
            "invocations": [item.to_dict() for item in self.invocations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentExecutionRecord":
        return cls(
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            state=AgentExecutionState(
                str(data.get("state") or AgentExecutionState.CREATED.value)
            ),
            created_at=str(data.get("created_at") or execution_timestamp()),
            updated_at=str(data.get("updated_at") or execution_timestamp()),
            started_at=str(data.get("started_at") or ""),
            ended_at=str(data.get("ended_at") or ""),
            step_count=int(data.get("step_count") or 0),
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            termination_reason=str(data.get("termination_reason") or ""),
            termination_message=str(data.get("termination_message") or ""),
            invocations=tuple(
                InvocationRecord.from_dict(item)
                for item in data.get("invocations") or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


_ALLOWED_EXECUTION_TRANSITIONS = {
    AgentExecutionState.CREATED: {
        AgentExecutionState.STARTING,
        AgentExecutionState.CANCELLED,
    },
    AgentExecutionState.STARTING: {
        AgentExecutionState.RUNNING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
    },
    AgentExecutionState.RUNNING: {
        AgentExecutionState.WAITING,
        AgentExecutionState.CHECKPOINTED,
        AgentExecutionState.COMPLETED,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMED_OUT,
        AgentExecutionState.TERMINATED,
    },
    AgentExecutionState.WAITING: {
        AgentExecutionState.RUNNING,
        AgentExecutionState.CHECKPOINTED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMED_OUT,
        AgentExecutionState.TERMINATED,
    },
    AgentExecutionState.CHECKPOINTED: {
        AgentExecutionState.RUNNING,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TERMINATED,
    },
    AgentExecutionState.COMPLETED: set(),
    AgentExecutionState.FAILED: set(),
    AgentExecutionState.CANCELLED: set(),
    AgentExecutionState.TIMED_OUT: set(),
    AgentExecutionState.TERMINATED: set(),
}


def transition_execution(
    execution: AgentExecutionRecord,
    target: AgentExecutionState,
    *,
    reason: str = "",
    message: str = "",
) -> AgentExecutionRecord:
    if execution.state is target:
        return execution
    if target not in _ALLOWED_EXECUTION_TRANSITIONS[execution.state]:
        raise AgentLifecycleError(
            f"invalid execution transition: {execution.state.value} -> {target.value}",
            context={"run_id": execution.run_id},
        )
    now = execution_timestamp()
    started_at = execution.started_at
    if target is AgentExecutionState.STARTING and not started_at:
        started_at = now
    terminal = target in {
        AgentExecutionState.COMPLETED,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMED_OUT,
        AgentExecutionState.TERMINATED,
    }
    return replace(
        execution,
        state=target,
        updated_at=now,
        started_at=started_at,
        ended_at=now if terminal else execution.ended_at,
        termination_reason=reason or execution.termination_reason,
        termination_message=message or execution.termination_message,
    )


__all__ = [
    "AgentExecutionRecord",
    "AgentExecutionState",
    "InvocationKind",
    "InvocationRecord",
    "InvocationStatus",
    "execution_timestamp",
    "transition_execution",
]
