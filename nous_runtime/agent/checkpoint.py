"""Agent execution checkpoint adapter over the shared checkpoint store."""

from __future__ import annotations

from dataclasses import dataclass, replace

from nous_runtime.agent.budget import AgentBudgetUsage
from nous_runtime.agent.errors import AgentCheckpointError
from nous_runtime.agent.execution_state import AgentExecutionRecord
from nous_runtime.agent.termination import TerminationPolicy
from nous_runtime.checkpoint import (
    Checkpoint,
    CheckpointStore,
    CheckpointStoreError,
    InMemoryCheckpointStore,
)
from nous_runtime.core.redaction import redact_sensitive_data


@dataclass(frozen=True)
class AgentCheckpointSnapshot:
    checkpoint: Checkpoint
    execution: AgentExecutionRecord
    usage: AgentBudgetUsage
    termination_policy: TerminationPolicy


class AgentCheckpointManager:
    def __init__(
        self,
        store: CheckpointStore | None = None,
    ) -> None:
        self.store = store or InMemoryCheckpointStore()

    def save(
        self,
        execution: AgentExecutionRecord,
        usage: AgentBudgetUsage,
        termination_policy: TerminationPolicy,
    ) -> Checkpoint:
        provisional = Checkpoint(
            task_id=execution.task_id,
            state={},
            metadata={
                "kind": "agent_execution",
                "run_id": execution.run_id,
                "agent_id": execution.agent_id,
            },
        )
        stored_execution = replace(
            execution,
            checkpoint_id=provisional.checkpoint_id,
        )
        checkpoint = Checkpoint(
            checkpoint_id=provisional.checkpoint_id,
            task_id=execution.task_id,
            timestamp=provisional.timestamp,
            state=redact_sensitive_data(
                {
                    "execution": stored_execution.to_dict(),
                    "budget_usage": usage.to_dict(),
                    "termination_policy": termination_policy.to_dict(),
                }
            ),
            metadata=provisional.metadata,
        )
        return self.store.save(checkpoint)

    def restore(self, checkpoint_id: str) -> AgentCheckpointSnapshot:
        try:
            checkpoint = self.store.load(checkpoint_id)
        except CheckpointStoreError as exc:
            raise AgentCheckpointError(
                "agent checkpoint storage is invalid",
                context={"checkpoint_id": checkpoint_id},
            ) from exc
        if checkpoint is None:
            raise AgentCheckpointError(
                f"agent checkpoint not found: {checkpoint_id}",
                context={"checkpoint_id": checkpoint_id},
            )
        if checkpoint.metadata.get("kind") != "agent_execution":
            raise AgentCheckpointError(
                "checkpoint is not an Agent execution checkpoint",
                context={"checkpoint_id": checkpoint_id},
            )
        try:
            execution = AgentExecutionRecord.from_dict(
                checkpoint.state.get("execution") or {}
            )
            usage = AgentBudgetUsage.from_dict(
                checkpoint.state.get("budget_usage")
            )
            policy = TerminationPolicy.from_dict(
                checkpoint.state.get("termination_policy")
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise AgentCheckpointError(
                "agent checkpoint payload is invalid",
                context={"checkpoint_id": checkpoint_id},
            ) from exc
        return AgentCheckpointSnapshot(
            checkpoint=checkpoint,
            execution=execution,
            usage=usage,
            termination_policy=policy,
        )


__all__ = ["AgentCheckpointManager", "AgentCheckpointSnapshot"]
