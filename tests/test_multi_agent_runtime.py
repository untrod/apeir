from __future__ import annotations

import threading
import time

import pytest

from nous_runtime.agent.orchestration import AgentWorkItem, AgentWorkerResult, MultiAgentCoordinator


def test_multi_agent_success_isolated_and_bounded(tmp_path):
    (tmp_path / "source.txt").write_text("source", encoding="utf-8")
    active = 0
    maximum = 0
    lock = threading.Lock()
    def worker(item, workspace):
        nonlocal active, maximum
        assert workspace != tmp_path
        assert (workspace / "source.txt").read_text(encoding="utf-8") == "source"
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return AgentWorkerResult(item.work_id, item.agent_id, "completed", item.allowed_files, ({"name": item.work_id},))
    coordinator = MultiAgentCoordinator(tmp_path, worker, lambda results: {"approved": True}, max_workers=2)
    run = coordinator.start((AgentWorkItem("a", "A", "worker.a", ("a.txt",)), AgentWorkItem("b", "B", "worker.b", ("b.txt",))))
    assert run.state == "completed"
    assert run.integration["changed_files"] == ["a.txt", "b.txt"]
    assert maximum <= 2
    assert not (tmp_path / "a.txt").exists()


def test_worker_failure_preserves_partial_result_and_restart_recovers(tmp_path):
    attempts = {"b": 0}
    def worker(item, workspace):
        if item.work_id == "b":
            attempts["b"] += 1
            if attempts["b"] == 1:
                return AgentWorkerResult(item.work_id, item.agent_id, "failed", error="temporary")
        return AgentWorkerResult(item.work_id, item.agent_id, "completed", item.allowed_files)
    items = (AgentWorkItem("a", "A", "worker.a", ("a.txt",)), AgentWorkItem("b", "B", "worker.b", ("b.txt",), ("a",)))
    first = MultiAgentCoordinator(tmp_path, worker, lambda results: {"approved": True})
    failed = first.start(items)
    assert failed.state == "partial_failure" and "a" in failed.results
    second = MultiAgentCoordinator(tmp_path, worker, lambda results: {"approved": True})
    resumed = second.resume(failed.run_id)
    assert resumed.state == "completed"
    assert attempts["b"] == 2


def test_reviewer_rejection_and_merge_conflict_are_explicit(tmp_path):
    def worker(item, workspace):
        return AgentWorkerResult(item.work_id, item.agent_id, "completed", ("same.txt",))
    items = (AgentWorkItem("a", "A", "worker.a", ("same.txt",)), AgentWorkItem("b", "B", "worker.b", ("same.txt",)))
    rejected = MultiAgentCoordinator(tmp_path / "reject", worker, lambda results: {"approved": False, "reason": "tests failed"}).start(items)
    assert rejected.state == "review_rejected"
    conflicted = MultiAgentCoordinator(tmp_path / "conflict", worker, lambda results: {"approved": True}).start(items)
    assert conflicted.state == "conflict"
    assert conflicted.integration["conflicts"] == ["same.txt"]


def test_worker_scope_violation_is_failure(tmp_path):
    def worker(item, workspace):
        return AgentWorkerResult(item.work_id, item.agent_id, "completed", ("denied.txt",))
    run = MultiAgentCoordinator(tmp_path, worker, lambda results: {"approved": True}).start((AgentWorkItem("a", "A", "worker.a", ("allowed.txt",)),))
    assert run.state == "partial_failure"
    assert "outside declared scope" in run.error


def test_dependency_cycle_is_rejected(tmp_path):
    coordinator = MultiAgentCoordinator(tmp_path, lambda item, workspace: None, lambda results: {})
    with pytest.raises(ValueError, match="cycle"):
        coordinator.start((AgentWorkItem("a", "A", "worker.a", depends_on=("b",)), AgentWorkItem("b", "B", "worker.b", depends_on=("a",))))