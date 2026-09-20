"""Deterministic recovery decisions over canonical Run and Event contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from nous_runtime.events.models import RunEvent, RunState
from nous_runtime.events.stream import EventStream, EventStreamError


@dataclass(frozen=True)
class RecoveryDecision:
    fault_type: str
    final_run_state: RunState
    events_lost: bool
    work_duplicated: bool
    automatic: bool
    user_action_required: bool
    audit_evidence_complete: bool
    strategy: str
    explanation: str


_RECOVERY_POLICY: dict[str, tuple[RunState, bool, bool, str]] = {
    "temporary_sqlite_lock": (
        RunState.RECOVERING, True, False, "bounded_retry"
    ),
    "event_persistence_failure": (
        RunState.FAILED, False, True, "repair_event_store"
    ),
    "provider_timeout": (
        RunState.RECOVERING, True, False, "retry_or_fallback"
    ),
    "provider_rate_limit": (
        RunState.RECOVERING, True, False, "retry_after_or_fallback"
    ),
    "node_disconnect": (
        RunState.WAITING_FOR_NODE, True, False, "reconnect_and_replay"
    ),
    "worker_crash": (
        RunState.RECOVERING, True, False, "restart_from_checkpoint"
    ),
    "approval_expiration": (
        RunState.WAITING_FOR_APPROVAL, False, True, "request_new_approval"
    ),
    "runtime_restart": (
        RunState.RECOVERING, True, False, "restore_checkpoint_and_replay"
    ),
    "duplicate_request": (
        RunState.RUNNING, True, False, "return_idempotent_result"
    ),
    "disk_write_failure": (
        RunState.FAILED, False, True, "free_space_and_retry"
    ),
    "slow_event_consumer": (
        RunState.RUNNING, True, False, "bounded_backpressure"
    ),
}


class RecoveryCoordinator:
    """Assess bounded failures without replacing authoritative Run state."""

    def __init__(self, events: EventStream | None = None) -> None:
        self.events = events

    def assess(
        self,
        fault_type: str,
        *,
        run_id: str = "",
        idempotent: bool = True,
        checkpoint_available: bool = True,
        event_persisted: bool = True,
        duplicate_detected: bool = False,
        retry_count: int = 0,
        max_retries: int = 2,
    ) -> RecoveryDecision:
        if fault_type not in _RECOVERY_POLICY:
            raise ValueError(f"Unsupported recovery fault: {fault_type}")
        state, automatic, user_action, strategy = _RECOVERY_POLICY[fault_type]
        retry_exhausted = retry_count >= max_retries
        if fault_type in {
            "provider_timeout",
            "provider_rate_limit",
            "temporary_sqlite_lock",
        } and (retry_exhausted or not idempotent):
            state = RunState.FAILED
            automatic = False
            user_action = True
            strategy = "manual_retry_required"
        if fault_type in {"worker_crash", "runtime_restart"} and not checkpoint_available:
            state = RunState.FAILED
            automatic = False
            user_action = True
            strategy = "checkpoint_missing"
        work_duplicated = fault_type == "duplicate_request" and not duplicate_detected
        events_lost = not event_persisted
        decision = RecoveryDecision(
            fault_type=fault_type,
            final_run_state=state,
            events_lost=events_lost,
            work_duplicated=work_duplicated,
            automatic=automatic,
            user_action_required=user_action,
            audit_evidence_complete=event_persisted and not work_duplicated,
            strategy=strategy,
            explanation=(
                f"{fault_type} uses {strategy}; final state is {state.value}."
            ),
        )
        if self.events is not None and run_id:
            try:
                self.events.emit(
                    RunEvent(
                        run_id=run_id,
                        event_type="recovery.assessed",
                        payload={
                            "fault_type": fault_type,
                            "final_run_state": state.value,
                            "automatic": automatic,
                            "user_action_required": user_action,
                            "strategy": strategy,
                        },
                    )
                )
            except EventStreamError:
                decision = replace(
                    decision,
                    events_lost=True,
                    audit_evidence_complete=False,
                )
        return decision

    @staticmethod
    def supported_faults() -> tuple[str, ...]:
        return tuple(sorted(_RECOVERY_POLICY))
