"""Parallel DAG planner for analyzed Runtime tasks."""

from __future__ import annotations

from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.intelligence.task import TaskAnalysis


class ParallelTaskPlanner:
    """Build analyze -> parallel capability work -> verify DAGs."""

    def generate(self, analysis: TaskAnalysis) -> TaskPlan:
        steps = [
            PlanStep(
                "analyze",
                "Confirm task requirements",
                "reasoning",
            )
        ]
        dependencies: dict[str, tuple[str, ...]] = {}
        execution_steps: list[str] = []
        capabilities = (
            analysis.required_capabilities or ("reasoning",)
        )
        for index, capability in enumerate(capabilities, 1):
            step_id = f"execute_{index}"
            execution_steps.append(step_id)
            steps.append(
                PlanStep(
                    step_id,
                    f"Execute {capability} work",
                    capability,
                    metadata={
                        "retries": 1,
                        "timeout_seconds": 60,
                    },
                )
            )
            dependencies[step_id] = ("analyze",)
        steps.append(
            PlanStep(
                "verify",
                "Verify, score, and accept execution result",
                "evaluation",
            )
        )
        dependencies["verify"] = tuple(execution_steps)
        return TaskPlan(
            task_id=analysis.task_id,
            steps=tuple(steps),
            dependencies=dependencies,
            metadata={
                "task_type": analysis.task_type,
                "complexity": analysis.complexity,
                "execution_mode": "parallel_dag",
            },
        )


__all__ = ["ParallelTaskPlanner"]
