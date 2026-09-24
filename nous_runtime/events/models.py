# -*- coding: utf-8 -*-
"""Canonical run state and event definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.schema_registry import EVENT_SCHEMA_VERSION as SCHEMA_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class RunState(str, Enum):
    """Canonical run states."""

    CREATED = "CREATED"
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    PREPARING = "PREPARING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    REPLANNING = "REPLANNING"
    VERIFYING = "VERIFYING"
    WAITING_FOR_NODE = "WAITING_FOR_NODE"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_USER = "WAITING_USER"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    EVALUATING = "EVALUATING"
    RECOVERING = "RECOVERING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    """Canonical event types."""

    RUN_CREATED = "run.created"
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    CONTEXT_LOADED = "context.loaded"
    PLAN_CREATED = "plan.created"
    STEP_STARTED = "step.started"
    STEP_PROGRESS = "step.progress"
    COMMAND_PROPOSED = "command.proposed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    COMMAND_STARTED = "command.started"
    COMMAND_OUTPUT = "command.output"
    FILE_CHANGED = "file.changed"
    TEST_STARTED = "test.started"
    TEST_COMPLETED = "test.completed"
    NETWORK_REQUESTED = "network.requested"
    NETWORK_APPROVAL_REQUIRED = "network.approval_required"
    NETWORK_APPROVED = "network.approved"
    NETWORK_CONNECTED = "network.connected"
    NETWORK_RESPONSE_RECEIVED = "network.response_received"
    NETWORK_SNAPSHOT_CREATED = "network.snapshot_created"
    NETWORK_FAILED = "network.failed"
    NETWORK_COMPLETED = "network.completed"
    ARTIFACT_CREATED = "artifact.created"
    CLAIM_CREATED = "claim.created"
    CLAIM_EVIDENCE_ATTACHED = "claim.evidence_attached"
    CLAIM_VERIFIED = "claim.verified"
    CLAIM_CONFLICTED = "claim.conflicted"
    CLAIM_REJECTED = "claim.rejected"
    DOCUMENT_CREATED = "document.created"
    DOCUMENT_RENDERED = "document.rendered"
    DOCUMENT_VERIFIED = "document.verified"
    DOCUMENT_FAILED = "document.failed"
    ENVIRONMENT_CREATED = "environment.created"
    ENVIRONMENT_PREPARING = "environment.preparing"
    ENVIRONMENT_READY = "environment.ready"
    ENVIRONMENT_RUNNING = "environment.running"
    ENVIRONMENT_SUSPENDED = "environment.suspended"
    ENVIRONMENT_STOPPING = "environment.stopping"
    ENVIRONMENT_STOPPED = "environment.stopped"
    ENVIRONMENT_STARTED = "environment.started"
    ENVIRONMENT_DESTROYED = "environment.destroyed"
    ENVIRONMENT_FAILED = "environment.failed"
    SIMULATION_CREATED = "simulation.created"
    SIMULATION_STARTED = "simulation.started"
    SIMULATION_RETRYING = "simulation.retrying"
    SIMULATION_COMPLETED = "simulation.completed"
    SIMULATION_REPLAYED = "simulation.replayed"
    SIMULATION_CANCELLED = "simulation.cancelled"
    SIMULATION_FAILED = "simulation.failed"
    STEP_COMPLETED = "step.completed"
    RUN_PAUSED = "run.paused"
    RUN_RESUMED = "run.resumed"
    RUN_RECOVERING = "run.recovering"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_COMPLETED = "run.completed"
    WORK_RECEIVED = "work.received"
    WORK_ANALYSIS = "work.analysis"
    WORK_PREPARING = "work.preparing"
    WORK_PLAN_CREATED = "work.plan.created"
    WORK_PLAN_UPDATED = "work.plan.updated"
    WORK_PROGRESS = "work.progress"
    WORK_OBSERVING = "work.observing"
    WORK_MILESTONE = "work.milestone"
    WORK_BLOCKED = "work.blocked"
    WORK_WAITING_USER = "work.waiting_user"
    WORK_WAITING_APPROVAL = "work.waiting_approval"
    WORK_ACTION_DISPATCHED = "work.action.dispatched"
    WORK_RECOVERY_REQUIRED = "work.recovery.required"
    WORK_VERIFYING = "work.verifying"
    WORK_COMPLETED = "work.completed"


@dataclass
class RunEvent:
    """A canonical event emitted during a run.

    Every event contains:
    - event_id: unique identifier
    - sequence: monotonic per-run sequence number
    - timestamp: ISO-8601 UTC
    - run_id: the run this event belongs to
    - task_id: the task this run addresses
    - event_type: canonical event type string
    - actor: who or what produced this event
    - payload: event-type-specific data
    - schema_version: event schema version
    """

    event_id: str = field(default_factory=lambda: _new_id("evt"))
    sequence: int = 0
    timestamp: str = field(default_factory=_utc_now)
    run_id: str = ""
    task_id: str = ""
    event_type: str = ""
    actor: str = "runtime"
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": self.payload,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunEvent":
        return cls(
            event_id=str(data.get("event_id") or ""),
            sequence=int(data.get("sequence") or 0),
            timestamp=str(data.get("timestamp") or ""),
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            event_type=str(data.get("event_type") or ""),
            actor=str(data.get("actor") or "runtime"),
            payload=dict(data.get("payload") or {}),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass
class RunRecord:
    """A persistent record of a run's state and progress."""

    run_id: str = ""
    task_id: str = ""
    state: RunState = RunState.CREATED
    plan: dict[str, Any] = field(default_factory=dict)
    current_step: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    agent_id: str = ""
    node_id: str = ""
    workspace_id: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    completed_at: str = ""
    last_sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "state": self.state.value,
            "plan": self.plan,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "agent_id": self.agent_id,
            "node_id": self.node_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "last_sequence": self.last_sequence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        state_val = data.get("state", "CREATED")
        if isinstance(state_val, RunState):
            state = state_val
        else:
            state = RunState(str(state_val))
        return cls(
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            state=state,
            plan=dict(data.get("plan") or {}),
            current_step=str(data.get("current_step") or ""),
            total_steps=int(data.get("total_steps") or 0),
            completed_steps=int(data.get("completed_steps") or 0),
            agent_id=str(data.get("agent_id") or ""),
            node_id=str(data.get("node_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            completed_at=str(data.get("completed_at") or ""),
            last_sequence=int(data.get("last_sequence") or 0),
            metadata=dict(data.get("metadata") or {}),
        )
