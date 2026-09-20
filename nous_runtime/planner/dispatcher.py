# -*- coding: utf-8 -*-
"""Dispatcher — routes tasks to capability execution."""

from __future__ import annotations

import logging
import time
from typing import Any

from nous_runtime.core.errors import TaskError
from nous_runtime.planner.observation import Observation
from nous_runtime.planner.plan import Task, TaskStatus

log = logging.getLogger("nous.planner.dispatcher")


class Dispatcher:
    """
    Dispatches tasks to the capability execution pipeline.

    For each task:
        1. Resolve capability
        2. Select provider (via intelligent router if available)
        3. Execute
        4. Record result
        5. Record experience
    """

    def dispatch_observation(self, task: Task) -> Observation:
        """Execute a single task and return a structured Observation."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        start = time.time()
        capability_obs: Observation | None = None

        try:
            if not task.capability_id:
                raise TaskError("Task has no capability_id")

            from nous_runtime.capability.resolver import execute_capability_observation
            capability_obs = execute_capability_observation(
                task.capability_id,
                **task.params,
            )

            if capability_obs.status == "success":
                task.status = TaskStatus.COMPLETED
                task.result = capability_obs.data.get("result", capability_obs.data)
            else:
                task.status = TaskStatus.FAILED
                task.error = "; ".join(capability_obs.errors) or "Unknown error"

            self._record_experience(task, capability_obs, time.time() - start)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            log.error("Task %s failed: %s", task.task_id, e)

        task.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        duration_ms = (time.time() - start) * 1000
        metadata = {
            "task_id": task.task_id,
            "capability_id": task.capability_id,
            "stage": "task.dispatch",
        }
        if capability_obs is not None:
            metadata["capability_observation_id"] = capability_obs.observation_id
            if capability_obs.metadata.get("provider_id"):
                metadata["provider_id"] = capability_obs.metadata["provider_id"]
            if capability_obs.metadata.get("error_code"):
                metadata["error_code"] = capability_obs.metadata["error_code"]

        if task.status == TaskStatus.COMPLETED:
            obs = Observation.success(
                "task.execute",
                {
                    "task_id": task.task_id,
                    "capability_id": task.capability_id,
                    "result": task.result,
                    "capability_observation": (
                        capability_obs.summary() if capability_obs else {}
                    ),
                },
                capability=task.capability_id,
                duration_ms=duration_ms,
                metadata=metadata,
            )
        else:
            obs = Observation.failure(
                "task.execute",
                [task.error or "task execution failed"],
                capability=task.capability_id,
                duration_ms=duration_ms,
                metadata=metadata,
            )

        task.observations.append(obs.summary())
        self._persist_observation(obs)
        return obs

    def dispatch(self, task: Task) -> dict[str, Any]:
        """Execute a single task through the capability pipeline."""
        obs = self.dispatch_observation(task)
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "error": task.error,
            "observation_id": obs.observation_id,
        }

    def dispatch_plan_observation(self, plan) -> Observation:
        """Execute an entire plan and return a plan-level Observation."""
        start = time.time()
        result = self.dispatch_plan(plan)
        status = "success" if result["success"] else "failed"
        data = {
            "plan_id": plan.plan_id,
            "waves": result["waves"],
            "results": result["results"],
            "progress": result["progress"],
            "task_observations": [
                obs
                for task in plan.tasks
                for obs in task.observations
                if isinstance(obs, dict)
            ],
        }
        metadata = {
            "plan_id": plan.plan_id,
            "stage": "plan.dispatch",
        }
        duration_ms = (time.time() - start) * 1000
        if status == "success":
            obs = Observation.success(
                "plan.execute",
                data,
                duration_ms=duration_ms,
                metadata=metadata,
            )
            self._persist_observation(obs)
            return obs
        obs = Observation.failure(
            "plan.execute",
            [r.get("error", "") for r in result["results"] if r.get("error")] or ["plan execution failed"],
            duration_ms=duration_ms,
            metadata=metadata,
        )
        obs.data = data
        self._persist_observation(obs)
        return obs

    def dispatch_plan(self, plan) -> dict[str, Any]:
        """Execute an entire plan, wave by wave."""
        from nous_runtime.planner.scheduler import Scheduler
        scheduler = Scheduler()

        results = []
        wave_num = 0
        while True:
            wave = scheduler.next_wave(plan)
            if wave is None:
                break
            wave_num += 1
            log.info("Wave %d: %d tasks", wave_num, len(wave))
            for task in wave:
                r = self.dispatch(task)
                r["wave"] = wave_num
                results.append(r)

            if plan.any_failed():
                log.warning("Plan %s: some tasks failed, stopping", plan.plan_id)
                break

        return {
            "plan_id": plan.plan_id,
            "waves": wave_num,
            "results": results,
            "progress": plan.progress(),
            "success": plan.all_done() and not plan.any_failed(),
        }

    @staticmethod
    def _record_experience(task: Task, result, duration_s: float) -> None:
        try:
            from nous_runtime.learning.experience import record
            if isinstance(result, Observation):
                ok = result.status == "success"
                provider_id = result.metadata.get("provider_id", "")
                error_code = result.metadata.get("error_code", "") if not ok else ""
            else:
                ok = result.ok if hasattr(result, 'ok') else False
                provider_id = getattr(result, 'provider_id', '')
                error_code = getattr(result, 'error_code', '') if not ok else ''
            record(
                capability_id=task.capability_id,
                provider_id=provider_id,
                ok=ok,
                duration_ms=duration_s * 1000,
                error_code=error_code,
            )
        except Exception:
            pass

    @staticmethod
    def _persist_observation(obs: Observation) -> None:
        try:
            from nous_runtime.project.workspace import find_workspace
            ws = find_workspace()
            if ws is None:
                return
            from nous_runtime.project.memory_ingestor import ingest_observation
            ingest_observation(str(ws), obs)
        except Exception:
            pass
