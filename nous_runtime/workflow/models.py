"""Durable Workflow Runtime contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    EVENT = "event"
    WEBHOOK = "webhook"


class StepType(str, Enum):
    AGENT = "agent"
    CAPABILITY = "capability"
    CONNECTOR = "connector"
    COMMAND = "command"
    APPROVAL = "approval"
    CONDITION = "condition"
    WAIT = "wait"
    TRANSFORM = "transform"


class WorkflowState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATION_FAILED = "compensation_failed"


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    step_type: StepType
    action: str = ""
    depends_on: tuple[str, ...] = ()
    condition: str = ""
    retries: int = 0
    timeout_seconds: float = 60.0
    approval_required: bool = False
    compensation: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    trigger: TriggerType
    steps: tuple[WorkflowStep, ...]
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    audit_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    workflow_id: str
    workflow_version: str
    inputs: dict[str, Any]
    run_id: str = field(default_factory=lambda: f"wfr_{uuid.uuid4().hex}")
    state: WorkflowState = WorkflowState.PENDING
    step_states: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    idempotency_key: str = ""
    cancellation_requested: bool = False