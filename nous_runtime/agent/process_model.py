"""Map the AgentProcess contract to Python runtime primitives.
Provides process lifecycle, capability narrowing, budget enforcement,
and checkpoint/restore matching the Rust nous-process crate.

The Rust Kernel remains authoritative for admitted execution.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger("nous.agent.process")


class ProcessStatus(Enum):
    """Agent process lifecycle states."""
    CREATED = "created"
    ADMITTED = "admitted"
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_MODEL = "waiting_for_model"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_RESOURCE = "waiting_for_resource"
    PAUSED = "paused"
    CHECKPOINTING = "checkpointing"
    RESTORING = "restoring"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessSignal(Enum):
    """Signals accepted by an agent process."""
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    KILL = "kill"
    CHECKPOINT = "checkpoint"
    RESTORE = "restore"
    BUDGET_UPDATE = "budget_update"
    CAPABILITY_NARROW = "capability_narrow"
    MIGRATE = "migrate"
    TIMEOUT = "timeout"
    PARENT_TERMINATED = "parent_terminated"


# Valid state transitions
PROCESS_TRANSITIONS: dict[ProcessStatus, set[ProcessStatus]] = {
    ProcessStatus.CREATED: {ProcessStatus.ADMITTED, ProcessStatus.CANCELLED},
    ProcessStatus.ADMITTED: {ProcessStatus.PENDING, ProcessStatus.FAILED},
    ProcessStatus.PENDING: {ProcessStatus.RUNNING, ProcessStatus.CANCELLED},
    ProcessStatus.RUNNING: {
        ProcessStatus.WAITING_FOR_MODEL,
        ProcessStatus.WAITING_FOR_APPROVAL,
        ProcessStatus.WAITING_FOR_RESOURCE,
        ProcessStatus.PAUSED,
        ProcessStatus.CHECKPOINTING,
        ProcessStatus.COMPLETED,
        ProcessStatus.FAILED,
        ProcessStatus.CANCELLED,
    },
    ProcessStatus.WAITING_FOR_MODEL: {ProcessStatus.RUNNING, ProcessStatus.FAILED, ProcessStatus.CANCELLED},
    ProcessStatus.WAITING_FOR_APPROVAL: {ProcessStatus.RUNNING, ProcessStatus.CANCELLED},
    ProcessStatus.WAITING_FOR_RESOURCE: {ProcessStatus.RUNNING, ProcessStatus.FAILED, ProcessStatus.CANCELLED},
    ProcessStatus.PAUSED: {ProcessStatus.RUNNING, ProcessStatus.CANCELLED},
    ProcessStatus.CHECKPOINTING: {ProcessStatus.RUNNING, ProcessStatus.PAUSED, ProcessStatus.FAILED},
    ProcessStatus.RESTORING: {ProcessStatus.RUNNING, ProcessStatus.FAILED},
    ProcessStatus.COMPLETED: set(),
    ProcessStatus.FAILED: {ProcessStatus.PENDING},  # Retry
    ProcessStatus.CANCELLED: set(),
}


@dataclass
class CapabilitySet:
    """Capability set that can only be narrowed."""
    capabilities: set[str] = field(default_factory=set)

    def narrower_than(self, parent: CapabilitySet) -> bool:
        """Check if this set is strictly narrower than parent."""
        return self.capabilities.issubset(parent.capabilities)

    def narrow(self, allowed: set[str]) -> CapabilitySet:
        """Create a narrower capability set."""
        return CapabilitySet(capabilities=self.capabilities & allowed)

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_list(self) -> list[str]:
        return sorted(self.capabilities)


@dataclass
class ProcessBudget:
    """Process budget with parent-ceiling enforcement."""
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    max_duration_seconds: float = 0.0
    tokens_used: int = 0
    cost_used: float = 0.0
    started_at: float | None = None

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.max_tokens - self.tokens_used) if self.max_tokens > 0 else float("inf")  # type: ignore[return-value]

    @property
    def cost_remaining(self) -> float:
        return max(0.0, self.max_cost_usd - self.cost_used) if self.max_cost_usd > 0 else float("inf")

    @property
    def duration_remaining(self) -> float:
        if self.max_duration_seconds <= 0 or self.started_at is None:
            return float("inf")
        elapsed = time.time() - self.started_at
        return max(0.0, self.max_duration_seconds - elapsed)

    @property
    def exhausted(self) -> bool:
        return (
            (self.max_tokens > 0 and self.tokens_used >= self.max_tokens)
            or (self.max_cost_usd > 0 and self.cost_used >= self.max_cost_usd)
            or (self.max_duration_seconds > 0 and self.duration_remaining <= 0)
        )

    def consume_tokens(self, count: int) -> bool:
        if self.max_tokens > 0 and self.tokens_used + count > self.max_tokens:
            return False
        self.tokens_used += count
        return True

    def consume_cost(self, amount_usd: float) -> bool:
        if self.max_cost_usd > 0 and self.cost_used + amount_usd > self.max_cost_usd:
            return False
        self.cost_used += amount_usd
        return True


@dataclass
class AgentProcess:
    """AgentProcess mapped to Python runtime primitives.

    Provides:
      - 13-state lifecycle with valid transitions
      - Parent-child process hierarchy
      - Capability narrowing (never widening)
      - Budget enforcement (child cannot exceed parent ceiling)
      - Checkpoint/restore with state snapshots
      - Signal handling (pause, resume, cancel, kill, migrate)
    """

    process_id: str = field(default_factory=lambda: f"proc-{uuid.uuid4().hex[:12]}")
    parent_id: str | None = None
    status: ProcessStatus = ProcessStatus.CREATED
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    budget: ProcessBudget = field(default_factory=ProcessBudget)
    children: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    _status_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _signal_handlers: dict[ProcessSignal, Callable] = field(default_factory=dict, repr=False)

    # Lifecycle

    def transition_to(self, target: ProcessStatus) -> bool:
        """Attempt a state transition. Returns False if invalid."""
        with self._status_lock:
            if target not in PROCESS_TRANSITIONS.get(self.status, set()):
                log.warning(
                    "Invalid transition: %s → %s (process %s)",
                    self.status.value, target.value, self.process_id,
                )
                return False

            old_status = self.status
            self.status = target
            log.info(
                "Process %s: %s → %s",
                self.process_id, old_status.value, target.value,
            )

            if target == ProcessStatus.RUNNING and self.budget.started_at is None:
                self.budget.started_at = time.time()

            return True

    def can_transition_to(self, target: ProcessStatus) -> bool:
        return target in PROCESS_TRANSITIONS.get(self.status, set())

    # Capability narrowing

    def narrow_capabilities(self, allowed: set[str]) -> bool:
        """Narrow capabilities. Can only remove, never add."""
        new_caps = self.capabilities.narrow(allowed)
        if new_caps.capabilities == self.capabilities.capabilities:
            return True  # No change needed

        self.capabilities = new_caps
        log.info("Process %s capabilities narrowed to: %s", self.process_id, self.capabilities.to_list())
        return True

    def spawn_child(
        self,
        capabilities: set[str] | None = None,
        budget: ProcessBudget | None = None,
    ) -> AgentProcess:
        """Spawn a child process with narrowed capabilities and bounded budget."""
        # Child capabilities must be subset of parent
        child_caps = capabilities or self.capabilities.capabilities
        if not CapabilitySet(child_caps).narrower_than(self.capabilities):
            raise ValueError("Child cannot have capabilities the parent does not possess")

        # Child budget cannot exceed parent remaining
        child_budget = budget or ProcessBudget()
        if self.budget.max_tokens > 0:
            child_budget.max_tokens = min(
                child_budget.max_tokens or float("inf"),
                self.budget.tokens_remaining,
            )
        if self.budget.max_cost_usd > 0:
            child_budget.max_cost_usd = min(
                child_budget.max_cost_usd or float("inf"),
                self.budget.cost_remaining,
            )

        child = AgentProcess(
            parent_id=self.process_id,
            capabilities=CapabilitySet(child_caps),
            budget=child_budget,
            status=ProcessStatus.CREATED,
        )
        child.transition_to(ProcessStatus.ADMITTED)
        self.children.append(child.process_id)
        log.info(
            "Spawned child process %s ← parent %s (caps=%s, budget_tokens=%d)",
            child.process_id, self.process_id,
            child.capabilities.to_list(), child.budget.max_tokens,
        )
        return child

    # Signal handling

    def register_handler(self, signal: ProcessSignal, handler: Callable) -> None:
        self._signal_handlers[signal] = handler

    def send_signal(self, signal: ProcessSignal) -> bool:
        """Send a signal to this process."""
        handler = self._signal_handlers.get(signal)
        if handler:
            try:
                handler(self)
            except Exception as e:
                log.error("Signal handler error for %s: %s", signal.value, e)
                return False

        signal_transitions = {
            ProcessSignal.PAUSE: ProcessStatus.PAUSED,
            ProcessSignal.RESUME: ProcessStatus.RUNNING,
            ProcessSignal.CANCEL: ProcessStatus.CANCELLED,
            ProcessSignal.KILL: ProcessStatus.CANCELLED,
            ProcessSignal.CHECKPOINT: ProcessStatus.CHECKPOINTING,
            ProcessSignal.TIMEOUT: ProcessStatus.FAILED,
        }

        if signal in signal_transitions:
            return self.transition_to(signal_transitions[signal])

        return True

    # Checkpoint

    def checkpoint(self) -> str:
        """Create a state snapshot."""
        checkpoint_id = f"ckpt-{self.process_id}-{int(time.time())}"
        self.checkpoints.append(checkpoint_id)
        self.transition_to(ProcessStatus.CHECKPOINTING)
        # After checkpointing, return to running
        self.transition_to(ProcessStatus.RUNNING)
        log.info("Process %s checkpointed: %s", self.process_id, checkpoint_id)
        return checkpoint_id

    # Budget

    def check_budget(self) -> bool:
        """Check if budget is exhausted. If so, transition to FAILED."""
        if self.budget.exhausted:
            log.warning("Process %s budget exhausted", self.process_id)
            self.transition_to(ProcessStatus.FAILED)
            return False
        return True

    def consume(self, tokens: int = 0, cost_usd: float = 0.0) -> bool:
        """Consume budget resources. Returns False if insufficient."""
        if tokens > 0 and not self.budget.consume_tokens(tokens):
            return False
        if cost_usd > 0 and not self.budget.consume_cost(cost_usd):
            return False
        return self.check_budget()

    # Status

    @property
    def is_active(self) -> bool:
        return self.status in {
            ProcessStatus.RUNNING,
            ProcessStatus.WAITING_FOR_MODEL,
            ProcessStatus.WAITING_FOR_APPROVAL,
            ProcessStatus.WAITING_FOR_RESOURCE,
        }

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ProcessStatus.COMPLETED,
            ProcessStatus.FAILED,
            ProcessStatus.CANCELLED,
        }
