from __future__ import annotations

import threading

import pytest

from nous_runtime.events import RunState
from nous_runtime.work import (
    DecisionStatus,
    WorkAlreadyRunning,
    WorkDecision,
    WorkExecutionComponents,
    WorkSupervisor,
)


def _components(deliberator):
    return WorkExecutionComponents(
        tools=None,
        deliberator=deliberator,
        verifier=None,
    )


def test_detaching_client_does_not_stop_background_work(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def deliberate(_context):
        entered.set()
        assert release.wait(5)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "Background work completed",
            output="done",
        )

    supervisor = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(deliberate),
    )
    try:
        created = supervisor.start("Explain one bounded concept")
        assert entered.wait(5)

        detached = supervisor.detach(created.run_id)
        assert detached["active"] is True

        release.set()
        completed = supervisor.wait(created.run_id, timeout=5)
        assert completed.state is RunState.COMPLETED
        assert supervisor.attach(created.run_id)["work"]["result"] == "done"
    finally:
        release.set()
        supervisor.close()


def test_pause_is_durable_and_discards_inflight_decision(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def deliberate(_context):
        entered.set()
        assert release.wait(5)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "This stale decision must not complete the Work",
            output="stale",
        )

    supervisor = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(deliberate),
    )
    try:
        created = supervisor.start("Wait for a durable pause")
        assert entered.wait(5)
        paused = supervisor.pause(created.run_id, reason="user requested pause")
        release.set()

        settled = supervisor.wait(created.run_id, timeout=5)
        assert paused.state is RunState.PAUSED
        assert settled.state is RunState.PAUSED
        assert settled.result is None
    finally:
        release.set()
        supervisor.close()


def test_new_supervisor_recovers_checkpoint_through_reassessment(tmp_path):
    first = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(
            lambda _context: WorkDecision(
                DecisionStatus.ASK_USER,
                "Need user confirmation",
                next_action="Continue?",
            )
        ),
    )
    created = first.start(
        "Explain recovery semantics",
        preferred_model="model-a",
        read_only=True,
        max_iterations=7,
    )
    waiting = first.wait(created.run_id, timeout=5)
    first.close()
    assert waiting.state is RunState.WAITING_USER

    contexts = []

    def finish(context):
        contexts.append(context)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "Recovered after inspecting durable state",
            output="recovered",
        )

    restarted = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, snapshot: (
            _assert_recovery_options(snapshot, finish)
        ),
    )
    try:
        assert [item.run_id for item in restarted.recovery_candidates()] == [
            created.run_id
        ]
        restarted.resume(created.run_id)
        completed = restarted.wait(created.run_id, timeout=5)

        assert completed.state is RunState.COMPLETED
        assert completed.result == "recovered"
        assert contexts[0].recovering is True
        assert "re-evaluate" in contexts[0].reanalysis_reason
    finally:
        restarted.close()


def _assert_recovery_options(snapshot, deliberator):
    assert snapshot.execution_options == {
        "preferred_model": "model-a",
        "read_only": True,
        "max_iterations": 7,
    }
    return _components(deliberator)


def test_supervisor_rejects_two_workers_for_same_run(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def deliberate(_context):
        entered.set()
        assert release.wait(5)
        return WorkDecision(DecisionStatus.COMPLETE, "Done")

    supervisor = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(deliberate),
    )
    try:
        created = supervisor.start("Keep one owner for this run")
        assert entered.wait(5)
        with pytest.raises(WorkAlreadyRunning):
            supervisor.resume(created.run_id)
    finally:
        release.set()
        supervisor.wait(created.run_id, timeout=5)
        supervisor.close()


def test_uncertain_effect_requires_external_recovery_and_is_not_replayed(tmp_path):
    from nous_runtime.work import WorkHarness

    harness = WorkHarness(tmp_path)
    created = harness.create("Recover an uncertain deployment")
    created.pending_action = {
        "tool": "deploy_release",
        "arguments_digest": "sha256:" + "a" * 64,
        "effect_class": "execute",
        "capability_id": "deployment.execute",
        "recovery_policy": "kernel_or_manual",
    }
    harness.persist_progress(
        created,
        "work.action.dispatched",
        {"action": dict(created.pending_action)},
    )
    deliberations = []
    supervisor = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(
            lambda context: deliberations.append(context)
        ),
    )
    try:
        supervisor.resume(created.run_id)
        recovered = supervisor.wait(created.run_id, timeout=5)

        assert recovered.state is RunState.RECOVERY_REQUIRED
        assert recovered.pending_action["tool"] == "deploy_release"
        assert deliberations == []
        events = harness.events.load_events(created.run_id)
        assert events[-1].event_type == "work.recovery.required"
        assert events[-1].payload["automatic_replay"] is False
    finally:
        supervisor.close()


def test_interrupted_read_is_reassessed_before_safe_reissue(tmp_path):
    from nous_runtime.work import WorkHarness

    harness = WorkHarness(tmp_path)
    created = harness.create("Recover an interrupted workspace read")
    created.pending_action = {
        "tool": "read_file",
        "arguments_digest": "sha256:" + "b" * 64,
        "effect_class": "read",
        "capability_id": "filesystem.read",
        "recovery_policy": "reassess_then_reissue",
    }
    harness.persist_progress(
        created,
        "work.action.dispatched",
        {"action": dict(created.pending_action)},
    )
    contexts = []

    def deliberate(context):
        contexts.append(context)
        return WorkDecision(
            DecisionStatus.COMPLETE,
            "Read state was reassessed",
            output="safe",
        )

    supervisor = WorkSupervisor(
        tmp_path,
        component_factory=lambda _root, _snapshot: _components(deliberate),
    )
    try:
        supervisor.resume(created.run_id)
        recovered = supervisor.wait(created.run_id, timeout=5)

        assert recovered.state is RunState.COMPLETED
        assert recovered.pending_action == {}
        assert contexts[0].recovering is True
        assert "interrupted read-only action" in contexts[0].reanalysis_reason
    finally:
        supervisor.close()
