# -*- coding: utf-8 -*-
"""TaskGraph → Run Console progress mapping.

Maps TaskGraph nodes to measurable step states with evidence-based progress.
Never fabricates arbitrary completion percentages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.plan import TaskStatus


class StepState(str, Enum):
    """Step states for Run Console display."""
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


_TASK_TO_STEP: dict[TaskStatus, StepState] = {
    TaskStatus.PENDING: StepState.PENDING,
    TaskStatus.READY: StepState.READY,
    TaskStatus.RUNNING: StepState.RUNNING,
    TaskStatus.COMPLETED: StepState.COMPLETED,
    TaskStatus.FAILED: StepState.FAILED,
    TaskStatus.SKIPPED: StepState.SKIPPED,
}


@dataclass
class StepInfo:
    """Human-readable step information for the Run Console."""
    step_id: str
    description: str
    state: StepState = StepState.PENDING
    depends_on: list[str] = field(default_factory=list)
    agent_id: str = ""
    capability_id: str = ""


@dataclass
class RunProgress:
    """Evidence-based progress report for a run.

    Never contains a fabricated percentage. Instead, reports:
    - completed_steps / total_known_steps
    - completed_tests / total_tests (when running tests)
    - other measurable quantities
    """

    run_id: str = ""
    task_id: str = ""
    plan_id: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    steps: list[StepInfo] = field(default_factory=list)
    current_step: str = ""
    current_step_index: int = 0
    elapsed_seconds: float = 0.0
    last_event: str = ""
    files_changed: int = 0
    tests_completed: int = 0
    tests_total: int = 0
    waiting_reason: str = ""
    selected_agent: str = ""
    selected_node: str = ""
    pending_approvals: int = 0
    artifacts_count: int = 0

    @property
    def step_ratio(self) -> tuple[int, int]:
        """(completed, total) — use this, not a percentage."""
        return (self.completed_steps, self.total_steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "current_step": self.current_step,
            "current_step_index": self.current_step_index,
            "elapsed_seconds": self.elapsed_seconds,
            "last_event": self.last_event,
            "files_changed": self.files_changed,
            "tests_completed": self.tests_completed,
            "tests_total": self.tests_total,
            "waiting_reason": self.waiting_reason,
            "selected_agent": self.selected_agent,
            "selected_node": self.selected_node,
            "pending_approvals": self.pending_approvals,
            "artifacts_count": self.artifacts_count,
            "steps": [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "state": s.state.value,
                    "depends_on": s.depends_on,
                }
                for s in self.steps
            ],
        }


class ProgressCalculator:
    """Calculates evidence-based progress from a TaskGraph."""

    @staticmethod
    def from_graph(
        run_id: str,
        task_id: str,
        graph: TaskGraph,
        *,
        current_step: str = "",
        elapsed_seconds: float = 0.0,
        last_event: str = "",
        selected_agent: str = "",
        selected_node: str = "",
        pending_approvals: int = 0,
        files_changed: int = 0,
        tests_completed: int = 0,
        tests_total: int = 0,
        artifacts_count: int = 0,
    ) -> RunProgress:
        """Build a RunProgress from a TaskGraph."""
        nodes = list(graph.nodes.values())
        total = len(nodes)
        completed = sum(
            1 for n in nodes
            if n.task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        failed = sum(1 for n in nodes if n.task.status == TaskStatus.FAILED)

        steps: list[StepInfo] = []
        for n in nodes:
            step_state = _TASK_TO_STEP.get(n.task.status, StepState.PENDING)
            steps.append(StepInfo(
                step_id=n.task_id,
                description=n.task.description,
                state=step_state,
                depends_on=list(n.task.depends_on),
                capability_id=n.task.capability_id,
            ))

        return RunProgress(
            run_id=run_id,
            task_id=task_id,
            total_steps=total,
            completed_steps=completed,
            failed_steps=failed,
            steps=steps,
            current_step=current_step,
            elapsed_seconds=elapsed_seconds,
            last_event=last_event,
            files_changed=files_changed,
            tests_completed=tests_completed,
            tests_total=tests_total,
            selected_agent=selected_agent,
            selected_node=selected_node,
            pending_approvals=pending_approvals,
            artifacts_count=artifacts_count,
        )

    @staticmethod
    def open_ended_summary(
        run_id: str,
        *,
        current_step: str = "",
        completed_steps: int = 0,
        elapsed_seconds: float = 0.0,
        last_event: str = "",
        files_changed: int = 0,
        tests_completed: int = 0,
        waiting_reason: str = "",
        selected_agent: str = "",
        selected_node: str = "",
        pending_approvals: int = 0,
        changed_files: list[str] | None = None,
    ) -> RunProgress:
        """Build a progress report for open-ended coding work.

        For open-ended work where the total number of steps is unknown,
        report measurable quantities without fabricating a percentage.
        """
        return RunProgress(
            run_id=run_id,
            total_steps=0,  # Unknown for open-ended work
            completed_steps=completed_steps,
            current_step=current_step,
            elapsed_seconds=elapsed_seconds,
            last_event=last_event,
            files_changed=files_changed,
            tests_completed=tests_completed,
            waiting_reason=waiting_reason,
            selected_agent=selected_agent,
            selected_node=selected_node,
            pending_approvals=pending_approvals,
        )
