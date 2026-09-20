# -*- coding: utf-8 -*-
"""Unified RuntimeEvent type constants — canonical event taxonomy.

Every event in the Nous Runtime follows the ``<domain>.<action>`` convention.
This module defines the authoritative set of event type strings used by
EventBus, ExecutionTrace, SSE streaming, and all UI/mobile/remote consumers.
"""

from __future__ import annotations

from enum import Enum


class RuntimeEventDomain(str, Enum):
    """Top-level event domains."""
    TASK = "task"
    MODEL = "model"
    CAPABILITY = "capability"
    NODE = "node"
    APPROVAL = "approval"
    SESSION = "session"
    PLAN = "plan"
    ARTIFACT = "artifact"
    VERIFICATION = "verification"
    SANDBOX = "sandbox"
    EVIDENCE = "evidence"
    RUN = "run"
    ERROR = "error"
    SYSTEM = "system"



# Canonical event type constants


class RuntimeEvent:
    """Structured registry of all canonical runtime event types.

    Usage::

        bus.publish(RuntimeEvent.TASK_CREATED, payload={...})
        bus.publish(RuntimeEvent.model_invoked("chat"), payload={...})
    """

    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_QUEUED = "task.queued"
    TASK_PLANNING = "task.planning"
    TASK_AWAITING_APPROVAL = "task.awaiting_approval"
    TASK_DISPATCHING = "task.dispatching"
    TASK_RUNNING = "task.running"
    TASK_WAITING_FOR_MODEL = "task.waiting_for_model"
    TASK_WAITING_FOR_NODE = "task.waiting_for_node"
    TASK_PAUSED = "task.paused"
    TASK_RECOVERING = "task.recovering"
    TASK_VERIFYING = "task.verifying"
    TASK_COMPLETED = "task.completed"
    TASK_COMPLETED_WITH_WARNINGS = "task.completed_with_warnings"
    TASK_FAILED = "task.failed"
    TASK_FAILED_VERIFICATION = "task.failed_verification"
    TASK_CANCELLED = "task.cancelled"
    TASK_STEP_STARTED = "task.step.started"
    TASK_STEP_COMPLETED = "task.step.completed"
    TASK_STEP_FAILED = "task.step.failed"

    # Model invocation
    MODEL_INVOKED = "model.invoked"
    MODEL_STREAMING = "model.streaming"
    MODEL_COMPLETED = "model.completed"
    MODEL_FAILED = "model.failed"
    MODEL_RETRY = "model.retry"
    MODEL_FALLBACK = "model.fallback"
    MODEL_TOKEN_USAGE = "model.token_usage"

    @staticmethod
    def model_invoked(operation: str) -> str:
        return f"model.invoked.{operation}"

    @staticmethod
    def model_completed(operation: str) -> str:
        return f"model.completed.{operation}"

    # Capability execution
    CAPABILITY_REQUESTED = "capability.requested"
    CAPABILITY_RESOLVED = "capability.resolved"
    CAPABILITY_ADMITTED = "capability.admitted"
    CAPABILITY_DENIED = "capability.denied"
    CAPABILITY_APPROVED = "capability.approved"
    CAPABILITY_STARTED = "capability.started"
    CAPABILITY_COMPLETED = "capability.completed"
    CAPABILITY_FAILED = "capability.failed"
    CAPABILITY_TIMEOUT = "capability.timeout"

    # Node / Device
    NODE_REGISTERED = "node.registered"
    NODE_ONLINE = "node.online"
    NODE_OFFLINE = "node.offline"
    NODE_HEARTBEAT = "node.heartbeat"
    NODE_HEARTBEAT_LOST = "node.heartbeat_lost"
    NODE_REVOKED = "node.revoked"
    NODE_PAIRED = "node.paired"
    NODE_UNPAIRED = "node.unpaired"
    NODE_RECONNECTED = "node.reconnected"
    NODE_SESSION_EXPIRED = "node.session_expired"

    # Approval
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    APPROVAL_EXPIRED = "approval.expired"
    APPROVAL_SUPERSEDED = "approval.superseded"
    APPROVAL_ESCALATED = "approval.escalated"

    # Session
    SESSION_CREATED = "session.created"
    SESSION_RESUMED = "session.resumed"
    SESSION_EXPIRED = "session.expired"
    SESSION_CLOSED = "session.closed"
    SESSION_MESSAGE_RECEIVED = "session.message.received"
    SESSION_REPLY_SENT = "session.reply.sent"

    # Plan
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    PLAN_COMPLETED = "plan.completed"
    PLAN_FAILED = "plan.failed"

    # Artifact
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_UPDATED = "artifact.updated"
    ARTIFACT_DELETED = "artifact.deleted"

    # Verification
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"
    VERIFICATION_REPAIRED = "verification.repaired"

    # Sandbox
    SANDBOX_VALIDATED = "sandbox.validated"
    SANDBOX_REJECTED = "sandbox.rejected"
    SANDBOX_LIMIT_HIT = "sandbox.limit_hit"

    # Evidence
    EVIDENCE_RECORDED = "evidence.recorded"
    EVIDENCE_PROFILE_UPDATED = "evidence.profile_updated"

    # Run
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"

    # Error
    ERROR_OCCURRED = "error.occurred"
    ERROR_RECOVERED = "error.recovered"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_HEALTH_CHECK = "system.health_check"



# Event category mapping (for filtering/subscription)


EVENT_CATEGORIES: dict[str, set[str]] = {
    "task": {
        RuntimeEvent.TASK_CREATED, RuntimeEvent.TASK_QUEUED,
        RuntimeEvent.TASK_PLANNING, RuntimeEvent.TASK_AWAITING_APPROVAL,
        RuntimeEvent.TASK_DISPATCHING, RuntimeEvent.TASK_RUNNING,
        RuntimeEvent.TASK_WAITING_FOR_MODEL, RuntimeEvent.TASK_WAITING_FOR_NODE,
        RuntimeEvent.TASK_PAUSED, RuntimeEvent.TASK_RECOVERING,
        RuntimeEvent.TASK_VERIFYING, RuntimeEvent.TASK_COMPLETED,
        RuntimeEvent.TASK_COMPLETED_WITH_WARNINGS, RuntimeEvent.TASK_FAILED,
        RuntimeEvent.TASK_FAILED_VERIFICATION, RuntimeEvent.TASK_CANCELLED,
        RuntimeEvent.TASK_STEP_STARTED, RuntimeEvent.TASK_STEP_COMPLETED,
        RuntimeEvent.TASK_STEP_FAILED,
    },
    "model": {
        RuntimeEvent.MODEL_INVOKED, RuntimeEvent.MODEL_STREAMING,
        RuntimeEvent.MODEL_COMPLETED, RuntimeEvent.MODEL_FAILED,
        RuntimeEvent.MODEL_RETRY, RuntimeEvent.MODEL_FALLBACK,
        RuntimeEvent.MODEL_TOKEN_USAGE,
    },
    "capability": {
        RuntimeEvent.CAPABILITY_REQUESTED, RuntimeEvent.CAPABILITY_RESOLVED,
        RuntimeEvent.CAPABILITY_ADMITTED, RuntimeEvent.CAPABILITY_DENIED,
        RuntimeEvent.CAPABILITY_APPROVED, RuntimeEvent.CAPABILITY_STARTED,
        RuntimeEvent.CAPABILITY_COMPLETED, RuntimeEvent.CAPABILITY_FAILED,
        RuntimeEvent.CAPABILITY_TIMEOUT,
    },
    "node": {
        RuntimeEvent.NODE_REGISTERED, RuntimeEvent.NODE_ONLINE,
        RuntimeEvent.NODE_OFFLINE, RuntimeEvent.NODE_HEARTBEAT,
        RuntimeEvent.NODE_HEARTBEAT_LOST, RuntimeEvent.NODE_REVOKED,
        RuntimeEvent.NODE_PAIRED, RuntimeEvent.NODE_UNPAIRED,
        RuntimeEvent.NODE_RECONNECTED, RuntimeEvent.NODE_SESSION_EXPIRED,
    },
    "approval": {
        RuntimeEvent.APPROVAL_REQUESTED, RuntimeEvent.APPROVAL_GRANTED,
        RuntimeEvent.APPROVAL_DENIED, RuntimeEvent.APPROVAL_EXPIRED,
        RuntimeEvent.APPROVAL_SUPERSEDED, RuntimeEvent.APPROVAL_ESCALATED,
    },
    "session": {
        RuntimeEvent.SESSION_CREATED, RuntimeEvent.SESSION_RESUMED,
        RuntimeEvent.SESSION_EXPIRED, RuntimeEvent.SESSION_CLOSED,
        RuntimeEvent.SESSION_MESSAGE_RECEIVED, RuntimeEvent.SESSION_REPLY_SENT,
    },
}


def get_event_domain(event_type: str) -> str:
    """Extract the top-level domain from an event type string."""
    return event_type.split(".")[0] if "." in event_type else event_type


def is_event_in_category(event_type: str, category: str) -> bool:
    """Check if an event belongs to a given category."""
    return event_type in EVENT_CATEGORIES.get(category, set())


__all__ = [
    "RuntimeEventDomain",
    "RuntimeEvent",
    "EVENT_CATEGORIES",
    "get_event_domain",
    "is_event_in_category",
]
