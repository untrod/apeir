"""Deterministic first-version task planner."""

from __future__ import annotations

from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.intelligence.task import TaskAnalysis


class TaskPlanner:
    def generate(self, analysis: TaskAnalysis) -> TaskPlan:
        steps: list[PlanStep] = [PlanStep("analyze", "Confirm task requirements", "reasoning")]
        dependencies: dict[str, tuple[str, ...]] = {}
        previous = "analyze"
        for index, capability in enumerate(analysis.required_capabilities, 1):
            step_id = f"execute_{index}"
            steps.append(PlanStep(step_id, f"Execute {capability} work", capability))
            dependencies[step_id] = (previous,)
            previous = step_id
        steps.append(PlanStep("verify", "Verify execution result", "evaluation"))
        dependencies["verify"] = (previous,)
        return TaskPlan(
            task_id=analysis.task_id,
            steps=tuple(steps),
            dependencies=dependencies,
            metadata={"task_type": analysis.task_type, "complexity": analysis.complexity},
        )


__all__ = ["TaskPlanner"]
