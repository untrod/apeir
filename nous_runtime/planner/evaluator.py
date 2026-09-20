# -*- coding: utf-8 -*-
"""Evaluator — assesses execution results against success criteria."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.planner.plan import Plan, Task, TaskStatus


@dataclass
class EvaluationResult:
    """The result of evaluating a plan or task execution."""
    plan_id: str = ""
    success: bool = False
    score: float = 0.0
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    duration_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class Evaluator:
    """
    Evaluates plan execution results.

    Scoring:
    - Task completion rate (weight: 0.6)
    - Error-free execution (weight: 0.2)
    - Within time budget (weight: 0.2)
    """

    def evaluate_plan(self, plan: Plan, duration_s: float = 0.0) -> EvaluationResult:
        """Evaluate a completed plan."""
        progress = plan.progress()
        total = progress["total"]
        done = progress["done"]
        failed = progress["failed"]

        # Completion rate score
        completion_rate = done / max(total, 1)
        completion_score = completion_rate * 0.6

        # Error score
        error_rate = failed / max(total, 1)
        error_score = max(0, (1 - error_rate * 2)) * 0.2

        # Time budget score (assume 5 min per task)
        budget_seconds = total * 300
        time_score = max(0, min(1, budget_seconds / max(duration_s, 1))) * 0.2

        score = completion_score + error_score + time_score
        success = score >= 0.7

        recommendations = []
        if completion_rate < 1.0:
            recommendations.append(f"{failed} task(s) failed — check provider health")
        if duration_s > budget_seconds:
            recommendations.append("Execution exceeded time budget — consider parallel execution")

        return EvaluationResult(
            plan_id=plan.plan_id,
            success=success,
            score=round(score, 4),
            tasks_total=total,
            tasks_completed=done,
            tasks_failed=failed,
            duration_seconds=round(duration_s, 1),
            recommendations=recommendations,
        )

    def evaluate_task(self, task: Task) -> dict[str, Any]:
        """Evaluate a single task."""
        return {
            "task_id": task.task_id,
            "success": task.status == TaskStatus.COMPLETED,
            "status": task.status.value,
            "error": task.error,
            "retries": task.retry_count,
        }
