# -*- coding: utf-8 -*-
"""
ProjectCoordinator -orchestrates project lifecycle, continuation, and task linkage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nous_runtime.compat import time as _time

from .models import (
    Project, ProjectGoal, Milestone, WorkItem,
    ExecutionAttempt, Checkpoint, ContinuationDecision, ProgressSnapshot, ProjectEvent,
    ProjectState, WorkItemState, ContinuationAction,
    VALID_PROJECT_TRANSITIONS,
)
from .store import ProjectStore

_log = logging.getLogger("nous.project.coordinator")


class ProjectCoordinator:
    """Coordinates project lifecycle, continuation, and task linking."""

    def __init__(self, store: ProjectStore | None = None):
        self.store = store or ProjectStore()

    # Project Lifecycle

    def create_project(self, name: str, description: str = "", owner: str = "") -> dict[str, Any] | None:
        project = Project.create(name=name, description=description, owner=owner)
        if self.store.create_project(project):
            self._emit_event(project.project_id, "PROJECT_CREATED")
            return self.store.get_project(project.project_id)
        return None

    def activate(self, project_id: str) -> bool:
        p = self.store.get_project(project_id)
        if not p:
            return False
        current = ProjectState(p["status"])
        if ProjectState.ACTIVE not in VALID_PROJECT_TRANSITIONS.get(current, set()):
            return False
        ok = self.store.update_project_status(project_id, ProjectState.ACTIVE.value)
        if ok:
            self._emit_event(project_id, "PROJECT_ACTIVATED")
        return ok

    def pause(self, project_id: str, reason: str = "") -> bool:
        p = self.store.get_project(project_id)
        if not p or p["status"] not in (ProjectState.ACTIVE.value,):
            return False
        ok = self.store.update_project_status(project_id, ProjectState.PAUSED.value)
        if ok:
            self._emit_event(project_id, "PROJECT_PAUSED", data={"reason": reason})
        return ok

    def resume(self, project_id: str) -> bool:
        p = self.store.get_project(project_id)
        if not p or p["status"] != ProjectState.PAUSED.value:
            return False
        ok = self.store.update_project_status(project_id, ProjectState.ACTIVE.value)
        if ok:
            self._emit_event(project_id, "PROJECT_RESUMED")
        return ok

    def cancel_project(self, project_id: str) -> bool:
        p = self.store.get_project(project_id)
        if not p:
            return False
        current = ProjectState(p["status"])
        if current in (ProjectState.COMPLETED, ProjectState.ARCHIVED):
            return False
        ok = self.store.update_project_status(project_id, ProjectState.CANCELLED.value)
        if ok:
            self._emit_event(project_id, "PROJECT_CANCELLED")
        return ok

    def complete_project(self, project_id: str) -> bool:
        p = self.store.get_project(project_id)
        if not p or p["status"] != ProjectState.ACTIVE.value:
            return False
        items = self.store.list_work_items(project_id)
        all_done = all(i["status"] in (WorkItemState.SUCCEEDED.value, WorkItemState.SKIPPED.value) for i in items)
        if not all_done:
            return False
        ok = self.store.update_project_status(project_id, ProjectState.COMPLETED.value)
        if ok:
            self._emit_event(project_id, "PROJECT_COMPLETED")
        return ok

    # Goal / Milestone / WorkItem

    def add_goal(self, project_id: str, description: str, success_criteria: list[str] | None = None,
                 priority: str = "medium") -> dict[str, Any] | None:
        goal = ProjectGoal.create(project_id, description, success_criteria, priority)
        if self.store.save_goal(goal):
            return goal.to_dict()
        return None

    def add_milestone(self, project_id: str, description: str, goal_id: str = "") -> dict[str, Any] | None:
        ms = Milestone.create(project_id, description, goal_id)
        if self.store.save_milestone(ms):
            return ms.to_dict()
        return None

    def add_work_item(self, project_id: str, description: str, required_capability: str = "system.echo",
                      milestone_id: str = "", target_node: str = "", params: dict[str, Any] | None = None,
                      depends_on: list[str] | None = None, risk_level: str = "low") -> dict[str, Any] | None:
        wi = WorkItem.create(project_id=project_id, description=description,
                             required_capability=required_capability,
                             milestone_id=milestone_id, target_node=target_node,
                             params=params, depends_on=depends_on, risk_level=risk_level)
        if self.store.save_work_item(wi):
            self._emit_event(project_id, "WORK_ITEM_ADDED", work_item_id=wi.work_item_id)
            return wi.to_dict()
        return None

    # Continuation Resolver (deterministic)

    def continue_project(self, project_id: str, scope: str = "any_pending") -> ContinuationDecision:
        """
        Deterministic continuation resolution.
        Returns a ContinuationDecision -never guesses.
        """
        p = self.store.get_project(project_id)
        if not p:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.AMBIGUOUS_PROJECT.value,
                reason=f"Project {project_id} not found",
            )

        status = p["status"]
        if status == ProjectState.CANCELLED.value:
            return ContinuationDecision(project_id=project_id, action=ContinuationAction.NO_REMAINING_WORK.value,
                                        reason="Project cancelled")
        if status == ProjectState.COMPLETED.value:
            return ContinuationDecision(project_id=project_id, action=ContinuationAction.NO_REMAINING_WORK.value,
                                        reason="Project completed")
        if status == ProjectState.PAUSED.value:
            return ContinuationDecision(project_id=project_id, action=ContinuationAction.BLOCKED.value,
                                        reason="Project paused -resume first")

        # Get all work items
        items = self.store.list_work_items(project_id)

        # Find recoverable items
        recovery = [i for i in items if i["status"] == WorkItemState.RECOVERY_REQUIRED.value]
        if recovery:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.RESUME_EXISTING.value,
                resolved_work_item=recovery[0]["work_item_id"],
                reason=f"Recovery required for {recovery[0]['work_item_id']}",
            )

        # Find running items to resume
        running = [i for i in items if i["status"] == WorkItemState.RUNNING.value]
        if running:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.RESUME_EXISTING.value,
                resolved_work_item=running[0]["work_item_id"],
                reason=f"Resuming running item {running[0]['work_item_id']}",
            )

        # Find items waiting for node
        waiting_node = [i for i in items if i["status"] == WorkItemState.WAITING_NODE.value]
        if waiting_node:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.WAIT_FOR_NODE.value,
                reason=f"Waiting for node for {waiting_node[0]['work_item_id']}",
            )

        # Find items waiting for approval
        waiting_approval = [i for i in items if i["status"] == WorkItemState.WAITING_APPROVAL.value]
        if waiting_approval:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.REQUEST_APPROVAL.value,
                reason=f"Approval required for {waiting_approval[0]['work_item_id']}",
            )

        # Find READY items (dependencies satisfied)
        ready = self._find_ready(items)
        if len(ready) == 1:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.START_NEXT_READY.value,
                resolved_work_item=ready[0]["work_item_id"],
                reason=f"Ready: {ready[0]['description']}",
            )
        elif len(ready) > 1:
            # Multiple ready -pick first by creation order (deterministic)
            ready.sort(key=lambda i: i["created_at"])
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.START_NEXT_READY.value,
                resolved_work_item=ready[0]["work_item_id"],
                reason=f"Multiple ready ({len(ready)}), selected first: {ready[0]['description']}",
            )

        # Check for blocked items
        blocked = [i for i in items if i["status"] == WorkItemState.BLOCKED.value]
        if blocked:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.BLOCKED.value,
                reason=f"All pending items blocked ({len(blocked)} blocked)",
            )

        # Check for remaining planned items with unmet dependencies
        planned = [i for i in items if i["status"] == WorkItemState.PLANNED.value]
        if planned:
            unmet = []
            for wi in planned:
                deps = json.loads(wi.get("depends_on", "[]")) if isinstance(wi.get("depends_on"), str) else wi.get("depends_on", [])
                for dep_id in deps:
                    dep = self.store.get_work_item(dep_id)
                    if dep and dep["status"] not in (WorkItemState.SUCCEEDED.value, WorkItemState.SKIPPED.value):
                        unmet.append(dep_id)
            if unmet:
                return ContinuationDecision(
                    project_id=project_id, action=ContinuationAction.BLOCKED.value,
                    reason=f"Unmet dependencies: {unmet[:3]}",
                )

        # Nothing to do
        remaining = [i for i in items if i["status"] not in (
            WorkItemState.SUCCEEDED.value, WorkItemState.SKIPPED.value,
            WorkItemState.CANCELLED.value, WorkItemState.FAILED.value,
        )]
        if not remaining:
            return ContinuationDecision(
                project_id=project_id, action=ContinuationAction.NO_REMAINING_WORK.value,
                reason="All work items completed or cancelled",
            )

        return ContinuationDecision(
            project_id=project_id, action=ContinuationAction.REPLAN_REQUIRED.value,
            reason=f"Ambiguous: {len(remaining)} items remaining, no ready",
        )

    def _find_ready(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Find work items that have all dependencies satisfied and are in PLANNED state."""
        import json as _json
        ready = []
        for item in items:
            if item["status"] not in (WorkItemState.PLANNED.value, WorkItemState.READY.value):
                continue
            deps_raw = item.get("depends_on", "[]")
            dep_ids = _json.loads(deps_raw) if isinstance(deps_raw, str) else deps_raw
            deps_satisfied = True
            for dep_id in dep_ids:
                dep = self.store.get_work_item(dep_id)
                if not dep or dep["status"] not in (WorkItemState.SUCCEEDED.value, WorkItemState.SKIPPED.value):
                    deps_satisfied = False
                    break
            if deps_satisfied:
                # Promote PLANNED ->READY
                if item["status"] == WorkItemState.PLANNED.value:
                    self.store.update_work_item_status(item["work_item_id"], WorkItemState.READY.value)
                    item["status"] = WorkItemState.READY.value
                ready.append(item)
        return ready

    # WorkItem ->Task linking

    def start_work_item(self, work_item_id: str, node_id: str = "") -> dict[str, Any] | None:
        """Start a work item by creating a Phase 1 task."""
        wi = self.store.get_work_item(work_item_id)
        if not wi:
            return None
        if wi["status"] not in (WorkItemState.READY.value, WorkItemState.QUEUED.value,
                                 WorkItemState.RECOVERY_REQUIRED.value):
            return None

        # Create task
        from ..control_plane.task_coordinator import TaskCoordinator
        from ..protocol.task import TaskSubmission
        import json as _json
        params = _json.loads(wi.get("params_json", "{}")) if isinstance(wi.get("params_json"), str) else wi.get("params", {})
        sub = TaskSubmission.create(
            capability_id=wi["required_capability"] or "system.echo",
            params=params,
            target_node=node_id or wi.get("target_node", ""),
            risk_level=wi.get("risk_level", "low"),
            budget_max_time_ms=wi.get("budget_max_time_ms", 30000),
        )
        tc = TaskCoordinator()
        success, msg, task = tc.submit(sub)
        if not success:
            return None

        # Link task to work item
        self.store.update_work_item_status(work_item_id, WorkItemState.QUEUED.value, task_id=sub.task_id)

        # Record attempt
        attempt = ExecutionAttempt.create(work_item_id, sub.task_id, node_id or "unknown")
        self.store.append_attempt(attempt)

        self._emit_event(wi["project_id"], "WORK_ITEM_STARTED", work_item_id=work_item_id,
                         data={"task_id": sub.task_id})
        return task

    def complete_work_item(self, work_item_id: str, task_id: str, success: bool,
                           result: dict[str, Any] | None = None, error: str = "",
                           duration_ms: int = 0) -> bool:
        """Mark a work item as complete."""
        wi = self.store.get_work_item(work_item_id)
        if not wi:
            return False
        new_status = WorkItemState.SUCCEEDED.value if success else WorkItemState.FAILED.value
        ok = self.store.update_work_item_status(work_item_id, new_status, task_id=task_id)
        if ok:
            event_type = "WORK_ITEM_COMPLETED" if success else "WORK_ITEM_FAILED"
            self._emit_event(wi["project_id"], event_type, work_item_id=work_item_id,
                             data={"result": result or {}, "error": error})
        return ok

    # Checkpoints

    def create_checkpoint(self, project_id: str, description: str = "") -> dict[str, Any] | None:
        """Create an append-only checkpoint of current project state."""
        items = self.store.list_work_items(project_id)
        states = {i["work_item_id"]: i["status"] for i in items}
        cp = Checkpoint.create(project_id, description or f"Checkpoint at {_time.utc_now()}", states)
        if self.store.append_checkpoint(cp):
            self._emit_event(project_id, "CHECKPOINT_CREATED", data={"checkpoint_id": cp.checkpoint_id})
            return cp.to_dict()
        return None

    # Progress Snapshot

    def get_progress(self, project_id: str) -> ProgressSnapshot | None:
        """Compute current progress snapshot."""
        p = self.store.get_project(project_id)
        if not p:
            return None
        items = self.store.list_work_items(project_id)
        total = len(items)
        if total == 0:
            return ProgressSnapshot(project_id=project_id, total_work_items=0, progress_pct=0.0,
                                    current_summary="No work items", health="ok")

        completed = sum(1 for i in items if i["status"] == WorkItemState.SUCCEEDED.value)
        running = sum(1 for i in items if i["status"] == WorkItemState.RUNNING.value)
        blocked = sum(1 for i in items if i["status"] == WorkItemState.BLOCKED.value)

        pct = (completed / total) * 100.0 if total > 0 else 0.0

        # Determine next action from continuation
        decision = self.continue_project(project_id)
        next_action = decision.action
        requires_user = decision.action in (
            ContinuationAction.REQUEST_APPROVAL.value,
            ContinuationAction.REPLAN_REQUIRED.value,
            ContinuationAction.AMBIGUOUS_PROJECT.value,
        )

        health = "ok"
        if blocked > 0 and running == 0 and completed < total:
            health = "blocked"
        elif running == 0 and completed < total and p["status"] == ProjectState.ACTIVE.value:
            health = "stalled" if decision.action == ContinuationAction.BLOCKED.value else "ok"

        return ProgressSnapshot(
            project_id=project_id, total_work_items=total,
            completed=completed, running=running, blocked=blocked,
            progress_pct=round(pct, 1), current_summary=f"{completed}/{total} complete",
            next_action=next_action, requires_user_action=requires_user,
            health=health,
        )

    # Events

    def _emit_event(self, project_id: str, event_type: str, work_item_id: str = "",
                    data: dict[str, Any] | None = None) -> None:
        event = ProjectEvent(project_id=project_id, event_type=event_type,
                             work_item_id=work_item_id, data=data or {})
        self.store.append_event(event)

    def get_events(self, project_id: str) -> list[dict[str, Any]]:
        return self.store.list_events(project_id)

