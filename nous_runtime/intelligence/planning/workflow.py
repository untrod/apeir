"""Compile intelligence TaskPlan objects into the existing Workflow Runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nous_runtime.intelligence.planning.models import TaskPlan
from nous_runtime.workflow.models import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
)
from nous_runtime.workflow.runtime import StepHandler, WorkflowRuntime


class PlanWorkflowBridge:
    """Reuse Workflow Runtime for DAG, retry, checkpoint and approval."""

    def compile(self, plan: TaskPlan) -> WorkflowDefinition:
        steps = tuple(
            WorkflowStep(
                step_id=step.step_id,
                step_type=self._step_type(step.capability),
                action=step.capability,
                depends_on=tuple(
                    plan.dependencies.get(step.step_id, ())
                ),
                retries=max(
                    0,
                    min(10, int(step.metadata.get("retries") or 0)),
                ),
                timeout_seconds=max(
                    0.001,
                    float(
                        step.metadata.get("timeout_seconds") or 60
                    ),
                ),
                approval_required=bool(
                    step.metadata.get("approval_required", False)
                ),
                params={
                    "name": step.name,
                    **dict(step.metadata),
                },
            )
            for step in plan.steps
        )
        return WorkflowDefinition(
            workflow_id=f"task-plan-{plan.plan_id}",
            version="1",
            trigger=TriggerType.MANUAL,
            steps=steps,
            audit_metadata={
                "task_id": plan.task_id,
                "plan_id": plan.plan_id,
                **dict(plan.metadata),
            },
        )

    def execute(
        self,
        plan: TaskPlan,
        *,
        root: str = ".",
        handlers: Mapping[str, StepHandler] | None = None,
        inputs: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
        max_parallel: int = 4,
    ) -> WorkflowRun:
        definition = self.compile(plan)
        runtime = WorkflowRuntime(
            root,
            handlers=dict(handlers or {}),
            max_parallel=max_parallel,
        )
        runtime.register(definition)
        return runtime.start(
            definition.workflow_id,
            definition.version,
            dict(inputs or {}),
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _step_type(capability: str) -> StepType:
        if capability == "governance.approval":
            return StepType.APPROVAL
        if capability == "workflow.wait":
            return StepType.WAIT
        if capability == "workflow.transform":
            return StepType.TRANSFORM
        return StepType.CAPABILITY


__all__ = ["PlanWorkflowBridge"]
