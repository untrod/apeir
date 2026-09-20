# -*- coding: utf-8 -*-
"""Scheduler — decides when and how to execute tasks."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.planner.plan import Plan, Task, TaskStatus
from nous_runtime.planner.graph import TaskGraph

log = logging.getLogger("nous.planner.scheduler")


class Scheduler:
    """
    Schedules tasks from a Plan for execution.

    Supports sequential and parallel execution based on the task graph.
    """

    def __init__(self, max_parallel: int = 4):
        self.max_parallel = max_parallel

    def schedule(self, plan: Plan) -> list[list[Task]]:
        """
        Schedule a plan into execution waves.

        Each wave is a list of tasks that can run in parallel.
        Waves are executed sequentially.

        Returns:
            List of waves, each containing parallel-ready tasks.
        """
        graph = TaskGraph()
        graph.build(plan.tasks)
        completed: set[str] = set()

        waves: list[list[Task]] = []
        while not graph.is_complete():
            ready = graph.ready_nodes(completed)
            if not ready:
                # Check for deadlock (tasks stuck pending)
                pending = [n for n in graph.nodes.values() if n.task.status == TaskStatus.PENDING]
                if pending:
                    log.warning("Deadlock detected: %d tasks stuck pending", len(pending))
                break

            wave = [n.task for n in ready[:self.max_parallel]]
            for t in wave:
                t.status = TaskStatus.RUNNING
            waves.append(wave)

            # Mark as complete for scheduling purposes
            for t in wave:
                completed.add(t.task_id)

        return waves

    def next_wave(self, plan: Plan) -> list[Task] | None:
        """Get the next wave of ready tasks, or None if done."""
        completed = {
            t.task_id for t in plan.tasks
            if t.status == TaskStatus.COMPLETED
        }
        ready = [t for t in plan.tasks if t.status == TaskStatus.PENDING and t.is_ready(completed)]
        if not ready and plan.all_done():
            return None
        return ready[:self.max_parallel]

    def schedule_single(self, task: Task) -> dict[str, Any]:
        """Schedule a single task for immediate execution."""
        task.status = TaskStatus.RUNNING
        return {
            "task_id": task.task_id,
            "capability_id": task.capability_id,
            "params": task.params,
            "timeout_seconds": task.timeout_seconds,
        }
