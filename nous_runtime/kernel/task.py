# -*- coding: utf-8 -*-
"""
Task object model for Nous Runtime.

Implements §6.3 (Task State Extension), §8.4 (Execution Ticket),
and §13 (Evidence-Driven Joint Scheduling) of the master plan.

Task lifecycle:
    CREATED → QUEUED → PLANNING → AWAITING_APPROVAL → DISPATCHING
    → RUNNING → VERIFYING → COMPLETED / COMPLETED_WITH_WARNINGS
    → FAILED / FAILED_VERIFICATION / CANCELLED
    → WAITING_FOR_MODEL / WAITING_FOR_NODE
    → PAUSED / RECOVERING
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.kernel.object_model import (
    NousObject,
    Phase,
)
from nous_runtime.kernel.state_machine import (
    Checkpoint,
    StateMachine,
    TransitionRecord,
)
from nous_runtime.compat.ids import make_id


# Task phase

class TaskPhase(str, Enum):
    """Extended task lifecycle states — unified per Desktop Control Plane spec §6.

    States:
        DRAFT → ANALYZING → PLANNING → AWAITING_APPROVAL → QUEUED → PREPARING
        → RUNNING → PAUSED / WAITING_FOR_INPUT / WAITING_FOR_RESOURCE
        → VERIFYING → COMPLETED / COMPLETED_WITH_WARNINGS
        → RECOVERING → (resume state)
        → FAILED / FAILED_VERIFICATION
        → CANCEL_REQUESTED → CANCELLED
        → BLOCKED
    """

    DRAFT = "draft"                             # Initial, not yet submitted
    CREATED = "created"                         # Submitted (backward compat alias for DRAFT)
    ANALYZING = "analyzing"                     # Analyzing task requirements
    QUEUED = "queued"                           # Queued for scheduling
    PLANNING = "planning"                       # Planner generating approach
    AWAITING_APPROVAL = "awaiting_approval"     # Waiting for user approval
    PREPARING = "preparing"                     # Setting up execution environment
    DISPATCHING = "dispatching"                 # Assigning to node (backward compat)
    RUNNING = "running"                         # Executing on target node
    WAITING_FOR_MODEL = "waiting_for_model"     # Model not yet available (legacy)
    WAITING_FOR_NODE = "waiting_for_node"       # Node not yet available (legacy)
    WAITING_FOR_RESOURCE = "waiting_for_resource"  # Generic resource wait
    WAITING_FOR_INPUT = "waiting_for_input"     # Waiting for user input
    VERIFYING = "verifying"                     # Post-execution verification
    PAUSED = "paused"                           # User paused execution
    RECOVERING = "recovering"                   # Recovering from failure
    COMPLETED = "completed"                     # Successfully completed
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"  # Done but with issues
    FAILED = "failed"                           # Execution failed
    FAILED_VERIFICATION = "failed_verification"  # Verification rejected
    CANCEL_REQUESTED = "cancel_requested"       # Cancellation requested, waiting for cleanup
    CANCELLED = "cancelled"                     # User or system cancelled
    BLOCKED = "blocked"                         # Blocked by external dependency


# Valid task transitions (unified per Desktop Control Plane spec §6)
# Previous states are preserved for backward compatibility.
TASK_TRANSITIONS: dict[TaskPhase, frozenset[TaskPhase]] = {
    # Initial
    TaskPhase.DRAFT: frozenset({
        TaskPhase.ANALYZING, TaskPhase.CANCELLED,
    }),
    TaskPhase.CREATED: frozenset({
        TaskPhase.ANALYZING, TaskPhase.QUEUED, TaskPhase.CANCELLED,
    }),
    # Analysis & Planning
    TaskPhase.ANALYZING: frozenset({
        TaskPhase.PLANNING, TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.QUEUED: frozenset({
        TaskPhase.PLANNING, TaskPhase.PREPARING, TaskPhase.CANCELLED,
    }),
    TaskPhase.PLANNING: frozenset({
        TaskPhase.AWAITING_APPROVAL, TaskPhase.DISPATCHING,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.AWAITING_APPROVAL: frozenset({
        TaskPhase.PREPARING, TaskPhase.DISPATCHING, TaskPhase.PLANNING,  # modify & re-plan
        TaskPhase.CANCELLED,
    }),
    # Dispatching & Preparation
    TaskPhase.PREPARING: frozenset({
        TaskPhase.RUNNING, TaskPhase.WAITING_FOR_RESOURCE,
        TaskPhase.WAITING_FOR_NODE, TaskPhase.WAITING_FOR_MODEL,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.DISPATCHING: frozenset({
        TaskPhase.RUNNING, TaskPhase.WAITING_FOR_NODE,
        TaskPhase.WAITING_FOR_MODEL, TaskPhase.WAITING_FOR_RESOURCE,
        TaskPhase.CANCELLED,
    }),
    # Execution
    TaskPhase.RUNNING: frozenset({
        TaskPhase.VERIFYING, TaskPhase.PAUSED,
        TaskPhase.WAITING_FOR_NODE, TaskPhase.WAITING_FOR_MODEL,
        TaskPhase.WAITING_FOR_RESOURCE, TaskPhase.WAITING_FOR_INPUT,
        TaskPhase.RECOVERING, TaskPhase.FAILED,
        TaskPhase.CANCEL_REQUESTED, TaskPhase.CANCELLED,
    }),
    # Wait states
    TaskPhase.WAITING_FOR_MODEL: frozenset({
        TaskPhase.DISPATCHING, TaskPhase.PREPARING, TaskPhase.RUNNING,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.WAITING_FOR_NODE: frozenset({
        TaskPhase.DISPATCHING, TaskPhase.PREPARING, TaskPhase.RECOVERING,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.WAITING_FOR_RESOURCE: frozenset({
        TaskPhase.RUNNING, TaskPhase.PREPARING, TaskPhase.RECOVERING,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    TaskPhase.WAITING_FOR_INPUT: frozenset({
        TaskPhase.RUNNING, TaskPhase.CANCELLED,
    }),
    # Interruptions
    TaskPhase.PAUSED: frozenset({
        TaskPhase.RUNNING, TaskPhase.CANCEL_REQUESTED, TaskPhase.CANCELLED,
    }),
    TaskPhase.RECOVERING: frozenset({
        TaskPhase.DISPATCHING, TaskPhase.RUNNING, TaskPhase.PREPARING,
        TaskPhase.VERIFYING,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    }),
    # Verification
    TaskPhase.VERIFYING: frozenset({
        TaskPhase.COMPLETED, TaskPhase.COMPLETED_WITH_WARNINGS,
        TaskPhase.FAILED_VERIFICATION, TaskPhase.RECOVERING,
    }),
    # Cancellation flow
    TaskPhase.CANCEL_REQUESTED: frozenset({
        TaskPhase.CANCELLED, TaskPhase.FAILED,
    }),
    # Terminal states
    TaskPhase.COMPLETED: frozenset(),
    TaskPhase.COMPLETED_WITH_WARNINGS: frozenset(),
    TaskPhase.FAILED: frozenset(),
    TaskPhase.FAILED_VERIFICATION: frozenset(),
    TaskPhase.CANCELLED: frozenset(),
    TaskPhase.BLOCKED: frozenset({
        TaskPhase.RUNNING, TaskPhase.CANCELLED,  # Can be unblocked
    }),
}


def is_task_terminal(phase: TaskPhase) -> bool:
    return len(TASK_TRANSITIONS.get(phase, frozenset())) == 0


def is_task_active(phase: TaskPhase) -> bool:
    return not is_task_terminal(phase)


# Task budget

@dataclass
class TaskBudget:
    """Per-task resource budget per master plan §17.4."""

    max_cost_cents: int = 0               # 0 = unlimited
    max_tokens: int = 0                   # 0 = unlimited
    max_model_calls: int = 0              # 0 = unlimited
    max_agents: int = 0                   # 0 = unlimited
    max_execution_seconds: int = 0        # 0 = unlimited
    max_retries: int = 3
    max_concurrent_agents: int = 1

    # Actuals (tracked during execution)
    cost_cents_spent: int = 0
    tokens_spent: int = 0
    model_calls_made: int = 0
    agents_spawned: int = 0
    started_at: str = ""
    retries_used: int = 0

    @property
    def cost_exceeded(self) -> bool:
        if self.max_cost_cents <= 0:
            return False
        return self.cost_cents_spent >= self.max_cost_cents

    @property
    def tokens_exceeded(self) -> bool:
        if self.max_tokens <= 0:
            return False
        return self.tokens_spent >= self.max_tokens

    @property
    def model_calls_exceeded(self) -> bool:
        if self.max_model_calls <= 0:
            return False
        return self.model_calls_made >= self.max_model_calls

    @property
    def any_budget_exceeded(self) -> bool:
        return self.cost_exceeded or self.tokens_exceeded or self.model_calls_exceeded


# Task fingerprint

@dataclass
class TaskFingerprint:
    """Task characteristics for evidence-driven scheduling (§13.1).

    Generated at CREATED → QUEUED transition. Used by the scheduler
    to match tasks to the best model + node + tool combination.
    """

    fingerprint_id: str = field(default_factory=lambda: make_id(prefix="fp"))
    task_type: str = ""                  # code_fix, data_analysis, document_gen, etc.
    required_capabilities: list[str] = field(default_factory=list)
    input_modalities: list[str] = field(default_factory=list)  # text, image, audio
    estimated_context_tokens: int = 0
    privacy_level: str = "standard"      # standard | sensitive | confidential
    tool_requirements: list[str] = field(default_factory=list)
    target_node_roles: list[str] = field(default_factory=list)  # worker, edge, etc.
    latency_requirement_ms: int = 0       # 0 = no requirement
    risk_level: str = "LOW"
    requires_approval: bool = True
    requires_verification: bool = True
    is_long_running: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint_id": self.fingerprint_id,
            "task_type": self.task_type,
            "required_capabilities": self.required_capabilities,
            "input_modalities": self.input_modalities,
            "estimated_context_tokens": self.estimated_context_tokens,
            "privacy_level": self.privacy_level,
            "tool_requirements": self.tool_requirements,
            "target_node_roles": self.target_node_roles,
            "latency_requirement_ms": self.latency_requirement_ms,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "requires_verification": self.requires_verification,
            "is_long_running": self.is_long_running,
        }


# Execution Ticket

@dataclass
class ExecutionTicket:
    """Immutable execution authorization per master plan §8.4.

    Creates an unforgeable chain: Plan → Approval → ExecutionTicket → TaskGraph → Execution.
    """

    ticket_id: str = field(default_factory=lambda: make_id(prefix="ticket"))
    plan_id: str = ""
    task_id: str = ""
    approved_by: str = ""                # user_id
    approved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_node_id: str = ""
    assigned_model_id: str = ""          # Model instance ID
    step_count: int = 0
    budget: TaskBudget = field(default_factory=TaskBudget)
    expires_at: str = ""                 # Auto-expire if not started
    signature: str = ""                  # HMAC signature for non-repudiation

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc).isoformat() >= self.expires_at


# Task object

@dataclass
class Task(NousObject):
    """A schedulable, executable, verifiable unit of work.

    Represents the full lifecycle from user intent to verified completion.
    """

    kind: str = field(default="Task", init=False)

    # State machine
    phase_sm: StateMachine[TaskPhase] = field(
        default_factory=lambda: StateMachine(
            transitions=TASK_TRANSITIONS,
            current=TaskPhase.CREATED,
        )
    )

    # Task identity
    objective: str = ""                  # Human-readable goal
    conversation_id: str = ""            # Originating conversation
    user_id: str = ""                    # Who requested it

    # Scheduling
    fingerprint: TaskFingerprint = field(default_factory=TaskFingerprint)
    target_node_id: str = ""
    assigned_model_id: str = ""          # Model instance ID chosen by scheduler

    # Authorization
    ticket: ExecutionTicket | None = None

    # Budget
    budget: TaskBudget = field(default_factory=TaskBudget)

    # Execution tracking
    current_step: int = 0
    total_steps: int = 0
    agent_graph_id: str = ""             # Reference to AgentGraph (Batch 8)
    checkpoints: list[Checkpoint] = field(default_factory=list)

    # Results
    result_summary: str = ""
    result_artifacts: list[str] = field(default_factory=list)  # Artifact IDs
    verification_result: str = ""        # PASS | FAIL | PARTIAL
    rollback_performed: bool = False

    # Properties

    @property
    def phase(self) -> TaskPhase:
        return self.phase_sm.current

    @phase.setter
    def phase(self, value: Phase | TaskPhase) -> None:
        """Accept the inherited dataclass field during initialization.

        ``phase_sm`` remains the runtime source of truth once constructed.
        """
        if "phase_sm" not in self.__dict__:
            self.__dict__["_base_phase"] = value
            return
        raw = value.value if isinstance(value, Enum) else value
        try:
            self.phase_sm.current = TaskPhase(raw)
        except (TypeError, ValueError):
            self.__dict__["_base_phase"] = value

    @property
    def is_terminal(self) -> bool:
        return is_task_terminal(self.phase)

    @property
    def is_active(self) -> bool:
        return is_task_active(self.phase)

    @property
    def needs_approval(self) -> bool:
        return self.phase == TaskPhase.AWAITING_APPROVAL

    # State transitions

    def set_phase(self, phase: Phase, message: str = "") -> None:
        """Update base metadata without touching the 'phase' property.

        Task uses a TaskPhase state machine (phase_sm) as the source of truth.
        The base NousObject.phase field is shadowed by the @property and not
        directly settable. We update only the metadata tracking fields here.
        """
        self.message = message
        self.observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.metadata.updated_at = self.observed_at
        self.metadata.generation += 1

    def transition(self, to: TaskPhase, reason: str = "",
                   triggered_by: str = "system",
                   trace_id: str = "") -> TransitionRecord:
        """Execute a validated task phase transition."""
        record = self.phase_sm.transition(
            to, reason=reason, triggered_by=triggered_by, trace_id=trace_id
        )
        # Update metadata (cannot set self.phase — it's a read-only property
        # backed by phase_sm.current)
        self.message = reason
        self.observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.metadata.updated_at = self.observed_at
        self.metadata.generation += 1
        return record

    def create_checkpoint(self, node_id: str = "") -> Checkpoint:
        """Create a recovery checkpoint of current task state."""
        ckpt = Checkpoint(
            object_id=self.metadata.id,
            object_kind="Task",
            node_id=node_id,
            sequence_number=len(self.checkpoints),
            state_snapshot={
                "phase": self.phase.value,
                "current_step": self.current_step,
                "total_steps": self.total_steps,
                "budget": {
                    "cost_cents_spent": self.budget.cost_cents_spent,
                    "tokens_spent": self.budget.tokens_spent,
                    "retries_used": self.budget.retries_used,
                },
            },
        )
        self.checkpoints.append(ckpt)
        return ckpt

    def restore_from_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Restore task state from a checkpoint."""
        snap = checkpoint.state_snapshot
        if "phase" in snap:
            self.phase_sm.current = TaskPhase(snap["phase"])
        if "current_step" in snap:
            self.current_step = snap["current_step"]
        if "budget" in snap:
            b = snap["budget"]
            self.budget.cost_cents_spent = b.get("cost_cents_spent", 0)
            self.budget.tokens_spent = b.get("tokens_spent", 0)
            self.budget.retries_used = b.get("retries_used", 0)

    # Serialization

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["task"] = {
            "objective": self.objective,
            "phase": self.phase.value,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "target_node_id": self.target_node_id,
            "assigned_model_id": self.assigned_model_id,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "fingerprint": self.fingerprint.to_dict(),
            "ticket": {
                "ticket_id": self.ticket.ticket_id,
                "approved_by": self.ticket.approved_by,
                "approved_at": self.ticket.approved_at,
                "is_expired": self.ticket.is_expired,
            } if self.ticket else None,
            "budget": {
                "max_cost_cents": self.budget.max_cost_cents,
                "max_tokens": self.budget.max_tokens,
                "cost_cents_spent": self.budget.cost_cents_spent,
                "tokens_spent": self.budget.tokens_spent,
                "any_exceeded": self.budget.any_budget_exceeded,
            },
            "result": {
                "summary": self.result_summary,
                "verification": self.verification_result,
                "rollback_performed": self.rollback_performed,
            },
            "transition_history": [
                {"from": h.from_state, "to": h.to_state, "at": h.timestamp, "reason": h.reason}
                for h in self.phase_sm.history[-20:]
            ],
            "checkpoint_count": len(self.checkpoints),
        }
        return base
