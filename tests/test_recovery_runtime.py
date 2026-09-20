from __future__ import annotations

import pytest

from nous_runtime.events import EventStream
from nous_runtime.events.models import RunState
from nous_runtime.intelligence.reliability.fault_injection import FaultInjector
from nous_runtime.recovery_runtime import RecoveryCoordinator


@pytest.mark.parametrize(
    ("fault_type", "state", "automatic", "user_action"),
    [
        ("temporary_sqlite_lock", RunState.RECOVERING, True, False),
        ("event_persistence_failure", RunState.FAILED, False, True),
        ("provider_timeout", RunState.RECOVERING, True, False),
        ("provider_rate_limit", RunState.RECOVERING, True, False),
        ("node_disconnect", RunState.WAITING_FOR_NODE, True, False),
        ("worker_crash", RunState.RECOVERING, True, False),
        ("approval_expiration", RunState.WAITING_FOR_APPROVAL, False, True),
        ("runtime_restart", RunState.RECOVERING, True, False),
        ("duplicate_request", RunState.RUNNING, True, False),
        ("disk_write_failure", RunState.FAILED, False, True),
        ("slow_event_consumer", RunState.RUNNING, True, False),
    ],
)
def test_recovery_fault_outcomes(
    fault_type,
    state,
    automatic,
    user_action,
):
    decision = RecoveryCoordinator().assess(
        fault_type,
        event_persisted=fault_type != "event_persistence_failure",
        duplicate_detected=fault_type == "duplicate_request",
    )

    assert decision.final_run_state == state
    assert decision.automatic is automatic
    assert decision.user_action_required is user_action
    assert decision.work_duplicated is False
    assert decision.events_lost is (
        fault_type == "event_persistence_failure"
    )


def test_recovery_stops_unsafe_retry_and_missing_checkpoint():
    exhausted = RecoveryCoordinator().assess(
        "provider_timeout",
        retry_count=2,
        max_retries=2,
    )
    non_idempotent = RecoveryCoordinator().assess(
        "temporary_sqlite_lock",
        idempotent=False,
    )
    missing_checkpoint = RecoveryCoordinator().assess(
        "worker_crash",
        checkpoint_available=False,
    )

    assert exhausted.final_run_state == RunState.FAILED
    assert non_idempotent.strategy == "manual_retry_required"
    assert missing_checkpoint.strategy == "checkpoint_missing"
    assert all(
        decision.user_action_required
        for decision in (exhausted, non_idempotent, missing_checkpoint)
    )


def test_recovery_emits_audit_evidence_to_existing_event_stream(tmp_path):
    events = EventStream(str(tmp_path))
    decision = RecoveryCoordinator(events).assess(
        "runtime_restart",
        run_id="run_1",
    )

    persisted = events.load_events("run_1")
    assert decision.audit_evidence_complete is True
    assert persisted[-1].event_type == "recovery.assessed"
    assert persisted[-1].payload["strategy"] == (
        "restore_checkpoint_and_replay"
    )


def test_fault_injector_supports_recovery_faults():
    injector = FaultInjector()
    for fault_type in RecoveryCoordinator.supported_faults():
        injector.clear_all()
        injector.enable(fault_type, provider_id="runtime")
        injected = injector.inject("runtime", "", "")
        assert injected is not None
        assert injected["_fault_type"] == fault_type
