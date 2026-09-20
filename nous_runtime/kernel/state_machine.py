# -*- coding: utf-8 -*-
"""
State machine helpers for Nous Runtime objects.

Provides transition validation, hooks, and audit trail for all
object state changes. Used by Node, Task, Agent, Session, and
any other stateful object.

Design principle (§3.3): deterministic systems surround probabilistic
intelligence. State transitions are always validated before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Generic, TypeVar

from nous_runtime.compat.ids import make_id

S = TypeVar("S")


# Transition record

@dataclass
class TransitionRecord:
    """Immutable record of a single state transition."""

    transition_id: str = field(default_factory=lambda: make_id(prefix="trans"))
    from_state: str = ""
    to_state: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    triggered_by: str = ""               # user_id, node_id, or "system"
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "trace_id": self.trace_id,
        }


# State machine

class InvalidTransitionError(ValueError):
    """Raised when a state transition is not permitted."""


@dataclass
class StateMachine(Generic[S]):
    """Generic state machine for any enumerated state type.

    Usage:
        sm = StateMachine[NodeConnectivity](
            transitions=NODE_CONNECTIVITY_TRANSITIONS,
            initial=NodeConnectivity.ONLINE,
        )
        sm.transition(NodeConnectivity.DEGRADED, reason="High latency")
    """

    transitions: dict[Any, frozenset[Any]] = field(default_factory=dict)
    current: Any = None
    history: list[TransitionRecord] = field(default_factory=list)
    max_history: int = 100
    on_transition: Callable[[TransitionRecord], None] | None = None

    def __post_init__(self):
        if len(self.history) == 0 and self.current is not None:
            init = TransitionRecord(
                from_state="(initial)",
                to_state=self.current if isinstance(self.current, str) else self.current.value,
                reason="Initial state",
            )
            self.history.append(init)

    def can_transition(self, to: Any) -> bool:
        """Check if a transition is valid without executing it."""
        allowed = self.transitions.get(self.current)
        if allowed is None:
            return True  # No constraints defined
        return to in allowed

    def transition(self, to: Any, reason: str = "",
                   triggered_by: str = "system",
                   trace_id: str = "") -> TransitionRecord:
        """Execute a state transition. Raises InvalidTransitionError if invalid."""
        if to == self.current:
            return TransitionRecord(
                from_state=self.current.value if hasattr(self.current, "value") else str(self.current),
                to_state=to.value if hasattr(to, "value") else str(to),
                reason=reason or "Idempotent transition",
                triggered_by=triggered_by,
                trace_id=trace_id,
            )

        allowed = self.transitions.get(self.current)
        if allowed is not None and to not in allowed:
            raise InvalidTransitionError(
                f"Invalid transition: {self.current} → {to}. "
                f"Allowed: {[s.value if hasattr(s, 'value') else s for s in allowed]}"
            )

        from_str = self.current.value if hasattr(self.current, 'value') else str(self.current)
        to_str = to.value if hasattr(to, 'value') else str(to)

        record = TransitionRecord(
            from_state=from_str,
            to_state=to_str,
            reason=reason,
            triggered_by=triggered_by,
            trace_id=trace_id,
        )

        self.current = to
        self.history.append(record)

        # Trim history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Fire hook
        if self.on_transition is not None:
            self.on_transition(record)

        return record

    @property
    def last_transition(self) -> TransitionRecord | None:
        return self.history[-1] if self.history else None

    @property
    def transition_count(self) -> int:
        return len(self.history)


# Checkpoint

@dataclass
class Checkpoint:
    """A recovery checkpoint for stateful objects.

    Per master plan §5.4, tasks support WAITING_FOR_NODE, RUNNING_OFFLINE,
    RECOVERING, and MIGRATING states. Checkpoints enable recovery across
    node failures.
    """

    checkpoint_id: str = field(default_factory=lambda: make_id(prefix="ckpt"))
    object_id: str = ""
    object_kind: str = ""
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    node_id: str = ""
    sequence_number: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "object_id": self.object_id,
            "object_kind": self.object_kind,
            "state_snapshot": self.state_snapshot,
            "created_at": self.created_at,
            "node_id": self.node_id,
            "sequence_number": self.sequence_number,
        }


# Lease

@dataclass
class Lease:
    """A time-bounded lease for exclusive access to a resource.

    Used for node-task binding, primary node election, and
    distributed coordination.
    """

    lease_id: str = field(default_factory=lambda: make_id(prefix="lease"))
    holder_id: str = ""                  # node_id or task_id holding the lease
    resource_id: str = ""                # What is being leased
    acquired_at: str = ""
    expires_at: str = ""
    renewed_at: str | None = None
    released_at: str | None = None

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.acquired_at:
            self.acquired_at = now

    @property
    def is_expired(self) -> bool:
        if self.released_at is not None:
            return True
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc).isoformat() >= self.expires_at

    @property
    def is_active(self) -> bool:
        return not self.is_expired

    def release(self) -> None:
        self.released_at = datetime.now(timezone.utc).isoformat()

    def renew(self, new_expires_at: str) -> None:
        self.renewed_at = datetime.now(timezone.utc).isoformat()
        self.expires_at = new_expires_at
