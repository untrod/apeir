"""Bridge Task Runtime records into an ExecutionContext without executing them."""

from __future__ import annotations

from nous_runtime.core.events import EventEnvelope
from nous_runtime.execution import ExecutionContext
from nous_runtime.intelligence.planning.models import TaskPlan
from nous_runtime.task import TaskManager


class PlanExecutorBridge:
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    def prepare(
        self,
        plan: TaskPlan,
        *,
        provider: str = "",
        agent_id: str = "",
    ) -> ExecutionContext:
        task = self.task_manager.require(plan.task_id)
        event = EventEnvelope(
            event_type="task.plan.prepared",
            source="intelligence.planning",
            payload={"task_id": task.id, "plan_id": plan.plan_id},
        )
        return ExecutionContext(
            task_id=task.id,
            provider=provider,
            agent_id=agent_id,
            events=[event],
            metadata={"task": task.to_dict(), "plan": plan.to_dict()},
        )


__all__ = ["PlanExecutorBridge"]
