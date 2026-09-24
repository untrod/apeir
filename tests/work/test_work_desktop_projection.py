from __future__ import annotations

from nous_runtime.api.desktop_routes import (
    DESKTOP_ROUTES,
    handle_tasks_action,
    handle_tasks_list,
    handle_work_inspect,
)
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness


class _ArtifactTool:
    def specifications(self):
        return (
            {
                "type": "function",
                "function": {
                    "name": "artifact_tool",
                    "description": "Record one test artifact",
                    "parameters": {"type": "object"},
                },
            },
        )

    def execute(self, _name, _arguments):
        return {
            "ok": True,
            "artifact": {"artifact_ref": "sha256:" + "a" * 64},
        }


def test_desktop_task_read_does_not_initialize_work_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))

    response = handle_tasks_list()

    assert response["ok"] is True
    assert not (tmp_path / ".nous" / "checkpoints.db").exists()


def test_desktop_projects_durable_work_plan_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    harness = WorkHarness(tmp_path)
    created = harness.create("Fix this repository and run targeted tests")
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Record one build artifact",
                tool_name="artifact_tool",
            ),
            WorkDecision(DecisionStatus.BLOCKED, "Wait for review"),
        )
    )
    created = harness.run(
        created.run_id,
        deliberator=lambda _context: next(decisions),
        tools=_ArtifactTool(),
    )

    response = handle_tasks_list()

    assert response["ok"] is True
    task = next(
        item for item in response["data"]["tasks"] if item["id"] == created.run_id
    )
    assert task["task_kind"] == "work"
    assert task["task_id"] == created.run_id
    assert task["trace_id"] == created.run_id
    assert task["name"] == "Fix this repository and run targeted tests"
    assert task["status"] == "blocked"
    assert task["plan_revision"] == created.plan.revision
    assert len(task["steps"]) == len(created.plan.tasks)
    assert task["artifact_refs"] == ["sha256:" + "a" * 64]


def test_desktop_pause_and_cancel_mutate_work_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    harness = WorkHarness(tmp_path)
    created = harness.create("Inspect this repository and explain the result")

    paused = handle_tasks_action({"action": "pause", "task_id": created.run_id})
    cancelled = handle_tasks_action({"action": "cancel", "task_id": created.run_id})

    assert paused["ok"] is True
    assert paused["data"]["work"]["state"] == "PAUSED"
    assert cancelled["ok"] is True
    assert cancelled["data"]["work"]["state"] == "CANCELLED"
    restored = WorkHarness(tmp_path).require(created.run_id)
    assert restored.state.value == "CANCELLED"


def test_desktop_can_reattach_to_durable_work_without_starting_worker(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    created = WorkHarness(tmp_path).create("Inspect durable Work from Desktop")

    response = handle_work_inspect(created.run_id)

    assert response["ok"] is True
    assert response["data"]["work"]["run_id"] == created.run_id
    assert response["data"]["supervisor"]["active"] is False
    assert ("POST", "/api/v1/work") in DESKTOP_ROUTES
    assert ("GET", "/api/v1/work/{run_id}") in DESKTOP_ROUTES
