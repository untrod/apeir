# -*- coding: utf-8 -*-
"""
Canonical project models -immutable, versioned, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time


# State enums
class ProjectState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class WorkItemState(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_NODE = "waiting_node"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    RECOVERY_REQUIRED = "recovery_required"


class ContinuationAction(str, Enum):
    RESUME_EXISTING = "resume_existing"
    START_NEXT_READY = "start_next_ready"
    WAIT_FOR_NODE = "wait_for_node"
    REQUEST_APPROVAL = "request_approval"
    REPLAN_REQUIRED = "replan_required"
    NO_REMAINING_WORK = "no_remaining_work"
    AMBIGUOUS_PROJECT = "ambiguous_project"
    BLOCKED = "blocked"


# Transition tables
VALID_PROJECT_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.DRAFT: {ProjectState.ACTIVE, ProjectState.CANCELLED, ProjectState.ARCHIVED},
    ProjectState.ACTIVE: {ProjectState.PAUSED, ProjectState.BLOCKED, ProjectState.COMPLETED, ProjectState.CANCELLED},
    ProjectState.PAUSED: {ProjectState.ACTIVE, ProjectState.CANCELLED},
    ProjectState.BLOCKED: {ProjectState.ACTIVE, ProjectState.CANCELLED},
    ProjectState.COMPLETED: {ProjectState.ARCHIVED},
    ProjectState.CANCELLED: {ProjectState.ARCHIVED},
    ProjectState.ARCHIVED: set(),
}

VALID_WORK_ITEM_TRANSITIONS: dict[WorkItemState, set[WorkItemState]] = {
    WorkItemState.PLANNED: {WorkItemState.READY, WorkItemState.BLOCKED, WorkItemState.CANCELLED, WorkItemState.SKIPPED},
    WorkItemState.READY: {WorkItemState.QUEUED, WorkItemState.WAITING_APPROVAL, WorkItemState.WAITING_NODE, WorkItemState.BLOCKED, WorkItemState.SKIPPED},
    WorkItemState.QUEUED: {WorkItemState.RUNNING, WorkItemState.FAILED, WorkItemState.CANCELLED, WorkItemState.RECOVERY_REQUIRED},
    WorkItemState.RUNNING: {WorkItemState.SUCCEEDED, WorkItemState.FAILED, WorkItemState.CANCELLED, WorkItemState.RECOVERY_REQUIRED},
    WorkItemState.WAITING_APPROVAL: {WorkItemState.QUEUED, WorkItemState.CANCELLED},
    WorkItemState.WAITING_NODE: {WorkItemState.QUEUED, WorkItemState.CANCELLED},
    WorkItemState.BLOCKED: {WorkItemState.READY, WorkItemState.SKIPPED, WorkItemState.CANCELLED},
    WorkItemState.SUCCEEDED: set(),     # terminal
    WorkItemState.FAILED: {WorkItemState.READY, WorkItemState.RECOVERY_REQUIRED},  # can retry
    WorkItemState.CANCELLED: set(),     # terminal
    WorkItemState.SKIPPED: set(),       # terminal
    WorkItemState.RECOVERY_REQUIRED: {WorkItemState.READY, WorkItemState.QUEUED},
}


# Models
@dataclass(frozen=True)
class Project:
    project_id: str = ""
    name: str = ""
    description: str = ""
    status: str = "draft"
    owner: str = ""
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = "1.0"

    def __post_init__(self):
        if not self.project_id:
            object.__setattr__(self, "project_id", _ids.make_id("proj"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at)

    @classmethod
    def create(cls, name: str, description: str = "", owner: str = "") -> Project:
        return cls(name=name, description=description, owner=owner)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "name": self.name,
            "description": self.description, "status": self.status,
            "owner": self.owner, "created_at": self.created_at,
            "updated_at": self.updated_at, "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        return cls(**{k: d.get(k, "") for k in [
            "project_id", "name", "description", "status", "owner",
            "created_at", "updated_at", "schema_version",
        ]})


@dataclass(frozen=True)
class ProjectGoal:
    goal_id: str = ""
    project_id: str = ""
    description: str = ""
    success_criteria: tuple[str, ...] = ()
    priority: str = "medium"
    status: str = "pending"

    def __post_init__(self):
        if not self.goal_id:
            object.__setattr__(self, "goal_id", _ids.make_id("goal"))

    @classmethod
    def create(cls, project_id: str, description: str, success_criteria: list[str] | None = None, priority: str = "medium") -> ProjectGoal:
        return cls(project_id=project_id, description=description,
                   success_criteria=tuple(success_criteria or []), priority=priority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id, "project_id": self.project_id,
            "description": self.description,
            "success_criteria": list(self.success_criteria),
            "priority": self.priority, "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectGoal:
        return cls(
            goal_id=d.get("goal_id", ""), project_id=d.get("project_id", ""),
            description=d.get("description", ""),
            success_criteria=tuple(d.get("success_criteria", [])),
            priority=d.get("priority", "medium"), status=d.get("status", "pending"),
        )


@dataclass(frozen=True)
class Milestone:
    milestone_id: str = ""
    project_id: str = ""
    goal_id: str = ""
    description: str = ""
    target_date: str = ""
    status: str = "pending"
    work_item_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.milestone_id:
            object.__setattr__(self, "milestone_id", _ids.make_id("ms"))

    @classmethod
    def create(cls, project_id: str, description: str, goal_id: str = "") -> Milestone:
        return cls(project_id=project_id, goal_id=goal_id, description=description)

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id, "project_id": self.project_id,
            "goal_id": self.goal_id, "description": self.description,
            "target_date": self.target_date, "status": self.status,
            "work_item_ids": list(self.work_item_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Milestone:
        return cls(
            milestone_id=d.get("milestone_id", ""), project_id=d.get("project_id", ""),
            goal_id=d.get("goal_id", ""), description=d.get("description", ""),
            target_date=d.get("target_date", ""), status=d.get("status", "pending"),
            work_item_ids=tuple(d.get("work_item_ids", [])),
        )


@dataclass(frozen=True)
class WorkPlan:
    plan_id: str = ""
    project_id: str = ""
    version: int = 1
    work_item_ids: tuple[str, ...] = ()
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)
    status: str = "draft"
    created_at: str = ""

    def __post_init__(self):
        if not self.plan_id:
            object.__setattr__(self, "plan_id", _ids.make_id("plan"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    @classmethod
    def create(cls, project_id: str, work_item_ids: list[str] | None = None,
               dependency_graph: dict[str, list[str]] | None = None) -> WorkPlan:
        return cls(project_id=project_id, work_item_ids=tuple(work_item_ids or []),
                   dependency_graph=dependency_graph or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id, "project_id": self.project_id,
            "version": self.version, "work_item_ids": list(self.work_item_ids),
            "dependency_graph": self.dependency_graph,
            "status": self.status, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkPlan:
        return cls(
            plan_id=d.get("plan_id", ""), project_id=d.get("project_id", ""),
            version=d.get("version", 1), work_item_ids=tuple(d.get("work_item_ids", [])),
            dependency_graph=d.get("dependency_graph", {}),
            status=d.get("status", "draft"), created_at=d.get("created_at", ""),
        )


@dataclass(frozen=True)
class WorkItem:
    work_item_id: str = ""
    project_id: str = ""
    milestone_id: str = ""
    description: str = ""
    target_node: str = ""
    required_capability: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    status: str = "planned"
    depends_on: tuple[str, ...] = ()
    task_id: str = ""  # Linked Phase 1 task
    budget_max_time_ms: int = 30000
    completion_condition: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.work_item_id:
            object.__setattr__(self, "work_item_id", _ids.make_id("wi"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at)

    @classmethod
    def create(cls, project_id: str, description: str, required_capability: str = "system.echo",
               milestone_id: str = "", target_node: str = "", params: dict | None = None,
               depends_on: list[str] | None = None, risk_level: str = "low") -> WorkItem:
        return cls(project_id=project_id, milestone_id=milestone_id,
                   description=description, required_capability=required_capability,
                   target_node=target_node, params=params or {},
                   depends_on=tuple(depends_on or []), risk_level=risk_level)

    def is_idempotent(self) -> bool:
        return self.required_capability == "system.echo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id, "project_id": self.project_id,
            "milestone_id": self.milestone_id, "description": self.description,
            "target_node": self.target_node, "required_capability": self.required_capability,
            "params": self.params, "risk_level": self.risk_level,
            "status": self.status, "depends_on": list(self.depends_on),
            "task_id": self.task_id, "budget_max_time_ms": self.budget_max_time_ms,
            "completion_condition": self.completion_condition,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItem:
        return cls(
            work_item_id=d.get("work_item_id", ""), project_id=d.get("project_id", ""),
            milestone_id=d.get("milestone_id", ""), description=d.get("description", ""),
            target_node=d.get("target_node", ""), required_capability=d.get("required_capability", ""),
            params=d.get("params", {}), risk_level=d.get("risk_level", "low"),
            status=d.get("status", "planned"), depends_on=tuple(d.get("depends_on", [])),
            task_id=d.get("task_id", ""), budget_max_time_ms=d.get("budget_max_time_ms", 30000),
            completion_condition=d.get("completion_condition", ""),
            created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
        )


@dataclass(frozen=True)
class ExecutionAttempt:
    attempt_id: str = ""
    work_item_id: str = ""
    task_id: str = ""
    node_id: str = ""
    status: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0
    started_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.attempt_id:
            object.__setattr__(self, "attempt_id", _ids.make_id("att"))

    @classmethod
    def create(cls, work_item_id: str, task_id: str, node_id: str) -> ExecutionAttempt:
        return cls(work_item_id=work_item_id, task_id=task_id, node_id=node_id,
                   status="running", started_at=_time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id, "work_item_id": self.work_item_id,
            "task_id": self.task_id, "node_id": self.node_id,
            "status": self.status, "result": self.result,
            "error": self.error, "duration_ms": self.duration_ms,
            "started_at": self.started_at, "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutionAttempt:
        return cls(**{k: d.get(k, "") for k in [
            "attempt_id", "work_item_id", "task_id", "node_id", "status", "error",
            "started_at", "completed_at",
        ]})


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str = ""
    project_id: str = ""
    description: str = ""
    work_item_states: dict[str, str] = field(default_factory=dict)
    artifact_hashes: tuple[str, ...] = ()
    created_at: str = ""

    def __post_init__(self):
        if not self.checkpoint_id:
            object.__setattr__(self, "checkpoint_id", _ids.make_id("cp"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    @classmethod
    def create(cls, project_id: str, description: str, work_item_states: dict[str, str] | None = None) -> Checkpoint:
        return cls(project_id=project_id, description=description,
                   work_item_states=work_item_states or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "project_id": self.project_id,
            "description": self.description, "work_item_states": self.work_item_states,
            "artifact_hashes": list(self.artifact_hashes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=d.get("checkpoint_id", ""), project_id=d.get("project_id", ""),
            description=d.get("description", ""),
            work_item_states=d.get("work_item_states", {}),
            artifact_hashes=tuple(d.get("artifact_hashes", [])),
            created_at=d.get("created_at", ""),
        )


@dataclass(frozen=True)
class ContinuationRequest:
    request_id: str = ""
    project_id: str = ""
    scope: str = "any_pending"
    requested_at: str = ""
    requested_by: str = ""

    def __post_init__(self):
        if not self.request_id:
            object.__setattr__(self, "request_id", _ids.make_id("cont"))
        if not self.requested_at:
            object.__setattr__(self, "requested_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "project_id": self.project_id,
            "scope": self.scope, "requested_at": self.requested_at,
            "requested_by": self.requested_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContinuationRequest:
        return cls(**{k: d.get(k, "") for k in [
            "request_id", "project_id", "scope", "requested_at", "requested_by",
        ]})


@dataclass(frozen=True)
class ContinuationDecision:
    decision_id: str = ""
    request_id: str = ""
    project_id: str = ""
    action: str = ""
    resolved_work_item: str = ""
    reason: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.decision_id:
            object.__setattr__(self, "decision_id", _ids.make_id("cdec"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "request_id": self.request_id,
            "project_id": self.project_id, "action": self.action,
            "resolved_work_item": self.resolved_work_item,
            "reason": self.reason, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContinuationDecision:
        return cls(**{k: d.get(k, "") for k in [
            "decision_id", "request_id", "project_id", "action",
            "resolved_work_item", "reason", "created_at",
        ]})


@dataclass(frozen=True)
class PauseRequest:
    pause_id: str = ""
    project_id: str = ""
    work_item_id: str = ""
    reason: str = ""
    requested_at: str = ""
    requested_by: str = ""

    def __post_init__(self):
        if not self.pause_id:
            object.__setattr__(self, "pause_id", _ids.make_id("pause"))
        if not self.requested_at:
            object.__setattr__(self, "requested_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "pause_id": self.pause_id, "project_id": self.project_id,
            "work_item_id": self.work_item_id, "reason": self.reason,
            "requested_at": self.requested_at, "requested_by": self.requested_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PauseRequest:
        return cls(**{k: d.get(k, "") for k in [
            "pause_id", "project_id", "work_item_id", "reason",
            "requested_at", "requested_by",
        ]})


@dataclass(frozen=True)
class ResumeRecord:
    record_id: str = ""
    project_id: str = ""
    decision_id: str = ""
    paused_at: str = ""
    resumed_at: str = ""

    def __post_init__(self):
        if not self.record_id:
            object.__setattr__(self, "record_id", _ids.make_id("res"))
        if not self.resumed_at:
            object.__setattr__(self, "resumed_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id, "project_id": self.project_id,
            "decision_id": self.decision_id, "paused_at": self.paused_at,
            "resumed_at": self.resumed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResumeRecord:
        return cls(**{k: d.get(k, "") for k in [
            "record_id", "project_id", "decision_id", "paused_at", "resumed_at",
        ]})


@dataclass(frozen=True)
class ProjectArtifactReference:
    artifact_id: str = ""
    project_id: str = ""
    work_item_id: str = ""
    artifact_type: str = ""
    hash: str = ""
    size_bytes: int = 0
    secret_free: bool = True
    created_at: str = ""

    def __post_init__(self):
        if not self.artifact_id:
            object.__setattr__(self, "artifact_id", _ids.make_id("art"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id, "project_id": self.project_id,
            "work_item_id": self.work_item_id, "artifact_type": self.artifact_type,
            "hash": self.hash, "size_bytes": self.size_bytes,
            "secret_free": self.secret_free, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectArtifactReference:
        return cls(**{k: d.get(k, "") if k != "size_bytes" else d.get(k, 0)
                      for k in ["artifact_id", "project_id", "work_item_id",
                                "artifact_type", "hash", "size_bytes", "created_at"]})


@dataclass(frozen=True)
class ProgressSnapshot:
    snapshot_id: str = ""
    project_id: str = ""
    total_work_items: int = 0
    completed: int = 0
    running: int = 0
    blocked: int = 0
    progress_pct: float = 0.0
    current_summary: str = ""
    last_completed: str = ""
    next_action: str = ""
    requires_user_action: bool = False
    health: str = "ok"
    taken_at: str = ""

    def __post_init__(self):
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", _ids.make_id("snap"))
        if not self.taken_at:
            object.__setattr__(self, "taken_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id, "project_id": self.project_id,
            "total_work_items": self.total_work_items, "completed": self.completed,
            "running": self.running, "blocked": self.blocked,
            "progress_pct": self.progress_pct, "current_summary": self.current_summary,
            "last_completed": self.last_completed, "next_action": self.next_action,
            "requires_user_action": self.requires_user_action, "health": self.health,
            "taken_at": self.taken_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProgressSnapshot:
        return cls(**{k: d.get(k, "" if isinstance(d.get(k, ""), str) else 0)
                      for k in ["snapshot_id", "project_id", "total_work_items",
                                "completed", "running", "blocked", "progress_pct",
                                "current_summary", "last_completed", "next_action",
                                "requires_user_action", "health", "taken_at"]})


@dataclass(frozen=True)
class ProjectEvent:
    event_id: str = ""
    project_id: str = ""
    event_type: str = ""
    work_item_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.event_id:
            object.__setattr__(self, "event_id", _ids.make_id("pevt"))
        if not self.created_at:
            object.__setattr__(self, "created_at", _time.utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "project_id": self.project_id,
            "event_type": self.event_type, "work_item_id": self.work_item_id,
            "data": self.data, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectEvent:
        return cls(
            event_id=d.get("event_id", ""), project_id=d.get("project_id", ""),
            event_type=d.get("event_type", ""), work_item_id=d.get("work_item_id", ""),
            data=d.get("data", {}), created_at=d.get("created_at", ""),
        )

