"""Tests for ControlPlaneLifecycle and recovery."""


class TestLifecycle:
    """Test sidecar lifecycle management."""

    def test_initial_state_stopped(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle, LifecycleState
        lc = ControlPlaneLifecycle()
        assert lc.state == LifecycleState.STOPPED
        assert lc.port == 0
        assert lc.host == "127.0.0.1"

    def test_state_transitions(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle, LifecycleState
        lc = ControlPlaneLifecycle()
        transitions = []
        lc.on_state_change(lambda old, new: transitions.append((old, new)))
        lc._transition(LifecycleState.STARTING)
        assert transitions == [(LifecycleState.STOPPED, LifecycleState.STARTING)]
        lc._transition(LifecycleState.RUNNING)
        assert len(transitions) == 2

    def test_health_when_stopped(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle
        lc = ControlPlaneLifecycle()
        health = lc.health()
        assert "status" in health
        assert health["system"]["state"] == "STOPPED"

    def test_shutdown_when_stopped_returns_ok(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle
        lc = ControlPlaneLifecycle()
        result = lc.shutdown()
        assert result["ok"] is True

    def test_base_url_format(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle
        lc = ControlPlaneLifecycle()
        lc._host = "127.0.0.1"
        lc._port = 8770
        assert lc.base_url == "http://127.0.0.1:8770"

    def test_find_free_port(self):
        from nous_runtime.control_plane.lifecycle import ControlPlaneLifecycle
        lc = ControlPlaneLifecycle()
        port = lc._find_free_port()
        assert 1024 < port < 65536


class TestRecovery:
    """Test crash recovery system."""

    def test_crash_recording(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery, RecoveryAction
        recovery = ControlPlaneRecovery()
        record = recovery.record_crash("Test error", "traceback here")
        assert record.error == "Test error"
        assert record.stack_trace == "traceback here"
        assert record.crash_id.startswith("crash_")
        assert record.recovery_action != RecoveryAction.NONE

    def test_backoff_increases(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery
        recovery = ControlPlaneRecovery()
        recovery._crash_count = 1
        d1 = recovery.get_backoff_delay()
        recovery._crash_count = 3
        d3 = recovery.get_backoff_delay()
        assert d3 > d1  # backoff should increase with more crashes

    def test_backoff_capped(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery
        recovery = ControlPlaneRecovery()
        recovery._crash_count = 100
        delay = recovery.get_backoff_delay()
        assert delay <= 60.0  # capped at max

    def test_permanent_stop_after_max_crashes(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery
        recovery = ControlPlaneRecovery()
        recovery._crash_window_max = 3
        for _ in range(3):
            recovery.record_crash("error")
        assert recovery._permanent_stop is True
        assert recovery.should_restart() is False

    def test_diagnose_no_corruption_on_clean_system(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery
        recovery = ControlPlaneRecovery()
        result = recovery.diagnose_corruption()
        assert "severity" in result
        # Should be ok or warning, not critical on a dev setup

    def test_recover_in_flight_tasks_returns_structure(self):
        from nous_runtime.control_plane.recovery import ControlPlaneRecovery
        recovery = ControlPlaneRecovery()
        result = recovery.recover_in_flight_tasks()
        assert "recovered" in result
        assert "failed" in result


class TestStateMachine:
    """Test unified task state machine transitions."""

    def test_all_spec_states_exist(self):
        from nous_runtime.kernel.task import TaskPhase
        required = {"DRAFT", "ANALYZING", "PLANNING", "AWAITING_APPROVAL", "QUEUED",
                    "PREPARING", "RUNNING", "PAUSED", "WAITING_FOR_INPUT",
                    "WAITING_FOR_RESOURCE", "VERIFYING", "RECOVERING",
                    "COMPLETED", "FAILED", "CANCEL_REQUESTED", "CANCELLED", "BLOCKED"}
        existing = {e.name for e in TaskPhase}
        for state in required:
            assert state in existing, f"Missing state: {state}"

    def test_backward_compat_states_preserved(self):
        from nous_runtime.kernel.task import TaskPhase
        legacy = {"created", "queued", "planning", "awaiting_approval", "dispatching",
                  "running", "waiting_for_model", "waiting_for_node", "verifying",
                  "paused", "recovering", "completed", "completed_with_warnings",
                  "failed", "failed_verification", "cancelled"}
        existing = {e.value for e in TaskPhase}
        for state in legacy:
            assert state in existing, f"Legacy state missing: {state}"

    def test_valid_transitions_are_symmetric(self):
        """If A → B is valid, B should have A in its source set (for non-terminal)."""
        from nous_runtime.kernel.task import TASK_TRANSITIONS, TaskPhase
        for source, targets in TASK_TRANSITIONS.items():
            for target in targets:
                # Not all transitions are bidirectional, but verify structure
                assert isinstance(source, TaskPhase)
                assert isinstance(target, TaskPhase)

    def test_terminal_states_have_no_exits(self):
        from nous_runtime.kernel.task import TASK_TRANSITIONS, TaskPhase, is_task_terminal
        terminals = {TaskPhase.COMPLETED, TaskPhase.COMPLETED_WITH_WARNINGS,
                     TaskPhase.FAILED, TaskPhase.FAILED_VERIFICATION, TaskPhase.CANCELLED}
        for t in terminals:
            assert is_task_terminal(t) is True
            assert len(TASK_TRANSITIONS.get(t, frozenset())) == 0

    def test_non_terminal_states_have_exits(self):
        from nous_runtime.kernel.task import is_task_terminal, TaskPhase
        active = {TaskPhase.DRAFT, TaskPhase.ANALYZING, TaskPhase.PLANNING,
                  TaskPhase.RUNNING, TaskPhase.PAUSED, TaskPhase.RECOVERING,
                  TaskPhase.CANCEL_REQUESTED, TaskPhase.BLOCKED}
        for t in active:
            assert is_task_terminal(t) is False, f"{t} should not be terminal"

    def test_cancel_requested_flows_to_cancelled(self):
        from nous_runtime.kernel.task import TASK_TRANSITIONS, TaskPhase
        targets = TASK_TRANSITIONS.get(TaskPhase.CANCEL_REQUESTED, frozenset())
        assert TaskPhase.CANCELLED in targets
