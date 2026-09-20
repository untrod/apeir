"""Durable bridge between interactive requests and long-running projects.

This module does not execute model or device operations.  The Runtime remains
the only production execution path; this service records its project cursor,
work-item lifecycle, attempts, artifacts, and recovery checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nous_runtime.compat import time as _time
from nous_runtime.runtime.response import RuntimeResponse

from .coordinator import ProjectCoordinator
from .models import ExecutionAttempt, ProjectEvent, ProjectState, WorkItemState
from .store import ProjectStore


@dataclass(frozen=True)
class ProjectExecutionBinding:
    conversation_id: str
    project_id: str
    work_item_id: str
    run_id: str
    resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "run_id": self.run_id,
            "resumed": self.resumed,
        }


class ProjectExecutionService:
    """Own the durable project view of requests executed by the Runtime."""

    def __init__(
        self,
        coordinator: ProjectCoordinator | None = None,
        store: ProjectStore | None = None,
    ) -> None:
        self.store = store or ProjectStore()
        self.coordinator = coordinator or ProjectCoordinator(self.store)

    def begin(
        self,
        *,
        conversation_id: str,
        objective: str,
        owner: str,
        run_id: str,
        required_capability: str,
        target_node: str = "",
        risk_level: str = "low",
        params: Mapping[str, Any] | None = None,
    ) -> ProjectExecutionBinding:
        """Create or resume the durable work item for a Runtime request."""
        previous = self.store.get_runtime_binding(conversation_id)
        if previous:
            resumed = self._resume_previous(previous, run_id)
            if resumed is not None:
                return resumed

        project_id = self._active_project(previous, objective, owner)
        item = self.coordinator.add_work_item(
            project_id,
            objective,
            required_capability=required_capability,
            target_node=target_node,
            params=dict(params or {}),
            risk_level=risk_level,
        )
        if not item:
            raise RuntimeError("could not create durable project work item")
        work_item_id = str(item["work_item_id"])
        self.store.update_work_item_status(work_item_id, WorkItemState.READY.value)
        self.store.update_work_item_status(work_item_id, WorkItemState.QUEUED.value)
        self.store.update_work_item_status(
            work_item_id,
            WorkItemState.RUNNING.value,
            task_id=run_id,
        )
        self.store.save_runtime_binding(
            conversation_id,
            project_id,
            work_item_id,
            run_id,
        )
        self._event(
            project_id,
            "RUNTIME_BOUND",
            work_item_id,
            {"run_id": run_id, "conversation_id": conversation_id},
        )
        return ProjectExecutionBinding(
            conversation_id,
            project_id,
            work_item_id,
            run_id,
        )

    def finish(
        self,
        binding: ProjectExecutionBinding,
        response: RuntimeResponse,
    ) -> dict[str, Any]:
        """Commit the Runtime outcome and return public project linkage."""
        product_status = self._product_status(response)
        artifact_ids = self._artifact_ids(response.result)
        agent_execution = self._agent_execution_ids(response.result)
        checkpoint_reason = "Runtime request completed"
        binding_status = "succeeded"

        if product_status == "tool_limit_reached":
            self.store.update_work_item_status(
                binding.work_item_id,
                WorkItemState.RECOVERY_REQUIRED.value,
                task_id=binding.run_id,
            )
            self.coordinator.pause(
                binding.project_id,
                "Execution paused at the governed step budget",
            )
            checkpoint_reason = "Governed step budget reached; continuation required"
            binding_status = "recovery_required"
        else:
            succeeded = response.status == "ok"
            self.coordinator.complete_work_item(
                binding.work_item_id,
                binding.run_id,
                succeeded,
                result={
                    "trace_id": response.trace_id,
                    "runtime_status": response.status,
                    "product_status": product_status,
                    "artifact_ids": artifact_ids,
                    **agent_execution,
                },
                error="" if succeeded else response.message,
            )
            if not succeeded:
                checkpoint_reason = "Runtime request failed; state retained for diagnosis"
                binding_status = "failed"

        self.store.append_attempt(
            ExecutionAttempt(
                work_item_id=binding.work_item_id,
                task_id=binding.run_id,
                status=binding_status,
                result={
                    "trace_id": response.trace_id,
                    "product_status": product_status,
                    "artifact_ids": artifact_ids,
                    **agent_execution,
                },
                error="" if binding_status == "succeeded" else response.message,
                started_at="",
                completed_at=_time.utc_now(),
            )
        )
        checkpoint = self.coordinator.create_checkpoint(
            binding.project_id,
            checkpoint_reason,
        ) or {}
        checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
        self.store.save_runtime_binding(
            binding.conversation_id,
            binding.project_id,
            binding.work_item_id,
            binding.run_id,
            status=binding_status,
            checkpoint_id=checkpoint_id,
        )
        self._event(
            binding.project_id,
            "RUNTIME_OUTCOME_RECORDED",
            binding.work_item_id,
            {
                "run_id": binding.run_id,
                "status": binding_status,
                "checkpoint_id": checkpoint_id,
                "artifact_count": len(artifact_ids),
                **agent_execution,
            },
        )
        progress = self.coordinator.get_progress(binding.project_id)
        return {
            **binding.to_dict(),
            "status": binding_status,
            "checkpoint_id": checkpoint_id,
            "artifact_ids": artifact_ids,
            **agent_execution,
            "progress": progress.to_dict() if progress is not None else {},
        }

    def _active_project(
        self,
        previous: Mapping[str, Any] | None,
        objective: str,
        owner: str,
    ) -> str:
        if previous:
            project_id = str(previous.get("project_id") or "")
            project = self.store.get_project(project_id)
            if project and project.get("status") not in {
                ProjectState.COMPLETED.value,
                ProjectState.CANCELLED.value,
                ProjectState.ARCHIVED.value,
            }:
                if project.get("status") == ProjectState.PAUSED.value:
                    self.coordinator.resume(project_id)
                elif project.get("status") == ProjectState.BLOCKED.value:
                    self.coordinator.activate(project_id)
                return project_id

        project = self.coordinator.create_project(
            objective.strip()[:80] or "Runtime project",
            description=objective,
            owner=owner,
        )
        if not project:
            raise RuntimeError("could not create durable project")
        project_id = str(project["project_id"])
        if not self.coordinator.activate(project_id):
            raise RuntimeError("could not activate durable project")
        self.coordinator.add_goal(
            project_id,
            objective,
            success_criteria=["Runtime verification accepted"],
        )
        return project_id

    def _resume_previous(
        self,
        previous: Mapping[str, Any],
        run_id: str,
    ) -> ProjectExecutionBinding | None:
        if str(previous.get("status") or "") not in {
            "running",
            "recovery_required",
        }:
            return None
        project_id = str(previous.get("project_id") or "")
        work_item_id = str(previous.get("work_item_id") or "")
        project = self.store.get_project(project_id)
        work_item = self.store.get_work_item(work_item_id)
        if not project or not work_item:
            return None
        item_status = str(work_item.get("status") or "")
        if item_status not in {
            WorkItemState.READY.value,
            WorkItemState.QUEUED.value,
            WorkItemState.RUNNING.value,
            WorkItemState.RECOVERY_REQUIRED.value,
        }:
            return None
        if project.get("status") == ProjectState.PAUSED.value:
            self.coordinator.resume(project_id)
        elif project.get("status") == ProjectState.BLOCKED.value:
            self.coordinator.activate(project_id)
        if item_status == WorkItemState.RECOVERY_REQUIRED.value:
            self.store.update_work_item_status(
                work_item_id,
                WorkItemState.READY.value,
            )
            item_status = WorkItemState.READY.value
        if item_status == WorkItemState.READY.value:
            self.store.update_work_item_status(
                work_item_id,
                WorkItemState.QUEUED.value,
            )
        self.store.update_work_item_status(
            work_item_id,
            WorkItemState.RUNNING.value,
            task_id=run_id,
        )
        self.store.save_runtime_binding(
            str(previous["conversation_id"]),
            project_id,
            work_item_id,
            run_id,
        )
        self._event(
            project_id,
            "RUNTIME_RESUMED",
            work_item_id,
            {"run_id": run_id},
        )
        return ProjectExecutionBinding(
            str(previous["conversation_id"]),
            project_id,
            work_item_id,
            run_id,
            resumed=True,
        )

    def _event(
        self,
        project_id: str,
        event_type: str,
        work_item_id: str,
        data: Mapping[str, Any],
    ) -> None:
        self.store.append_event(
            ProjectEvent(
                project_id=project_id,
                event_type=event_type,
                work_item_id=work_item_id,
                data=dict(data),
            )
        )

    @staticmethod
    def _product_status(response: RuntimeResponse) -> str:
        execution = response.result.get("execution")
        if not isinstance(execution, Mapping):
            return response.status
        product = execution.get("result")
        if isinstance(product, Mapping):
            return str(product.get("status") or execution.get("status") or response.status)
        return str(execution.get("status") or response.status)

    @staticmethod
    def _agent_execution_ids(value: Any) -> dict[str, str]:
        if not isinstance(value, Mapping):
            return {"agent_run_id": "", "agent_checkpoint_id": ""}
        execution = value.get("execution")
        if not isinstance(execution, Mapping):
            return {"agent_run_id": "", "agent_checkpoint_id": ""}
        product = execution.get("result")
        if not isinstance(product, Mapping):
            return {"agent_run_id": "", "agent_checkpoint_id": ""}
        agent = product.get("agent_execution")
        if not isinstance(agent, Mapping):
            return {"agent_run_id": "", "agent_checkpoint_id": ""}
        return {
            "agent_run_id": str(agent.get("run_id") or ""),
            "agent_checkpoint_id": str(agent.get("checkpoint_id") or ""),
        }

    @classmethod
    def _artifact_ids(cls, value: Any) -> list[str]:
        found: list[str] = []

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                artifact_id = item.get("artifact_id")
                if artifact_id and str(artifact_id) not in found:
                    found.append(str(artifact_id))
                for nested in item.values():
                    visit(nested)
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    visit(nested)

        visit(value)
        return found
