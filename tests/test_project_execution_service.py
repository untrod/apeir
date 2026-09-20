from __future__ import annotations

import pytest

from nous_runtime.connectivity.project import ProjectExecutionService
from nous_runtime.runtime.response import RuntimeResponse


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path / "data"))
    return ProjectExecutionService()


def _response(*, status="ok", product_status="success", artifacts=()):
    return RuntimeResponse(
        request_id="run-1",
        status=status,
        message="done" if status == "ok" else "paused",
        trace_id="trace-1",
        result={
            "execution": {
                "status": product_status,
                "result": {
                    "status": product_status,
                    "agent_execution": {
                        "run_id": "agent-run-1",
                        "checkpoint_id": "agent-checkpoint-1",
                    },
                    "files": [
                        {"artifact_id": artifact_id} for artifact_id in artifacts
                    ],
                },
            }
        },
    )


def test_runtime_request_is_bound_to_durable_project_and_checkpoint(service):
    binding = service.begin(
        conversation_id="conversation-1",
        objective="build a verified program",
        owner="user-1",
        run_id="run-1",
        required_capability="workspace.code",
    )

    result = service.finish(
        binding,
        _response(artifacts=("artifact-1", "artifact-2")),
    )

    assert result["status"] == "succeeded"
    assert result["checkpoint_id"]
    assert result["artifact_ids"] == ["artifact-1", "artifact-2"]
    assert result["agent_run_id"] == "agent-run-1"
    assert result["agent_checkpoint_id"] == "agent-checkpoint-1"
    assert result["progress"]["completed"] == 1
    item = service.store.get_work_item(binding.work_item_id)
    assert item and item["status"] == "succeeded"


def test_step_budget_pauses_and_next_request_resumes_same_work_item(service):
    first = service.begin(
        conversation_id="conversation-2",
        objective="perform a long governed build",
        owner="user-1",
        run_id="run-1",
        required_capability="workflow.execute",
    )
    paused = service.finish(
        first,
        _response(status="failed", product_status="tool_limit_reached"),
    )

    assert paused["status"] == "recovery_required"
    assert service.store.get_project(first.project_id)["status"] == "paused"

    resumed = service.begin(
        conversation_id="conversation-2",
        objective="continue",
        owner="user-1",
        run_id="run-2",
        required_capability="workflow.execute",
    )

    assert resumed.resumed is True
    assert resumed.project_id == first.project_id
    assert resumed.work_item_id == first.work_item_id
    assert service.store.get_project(first.project_id)["status"] == "active"
    assert service.store.get_work_item(first.work_item_id)["task_id"] == "run-2"


def test_failed_request_keeps_project_and_checkpoint_for_diagnosis(service):
    binding = service.begin(
        conversation_id="conversation-3",
        objective="run a verified workflow",
        owner="user-1",
        run_id="run-1",
        required_capability="workflow.execute",
    )

    result = service.finish(
        binding,
        _response(status="failed", product_status="provider_error"),
    )

    assert result["status"] == "failed"
    assert result["checkpoint_id"]
    assert service.store.get_work_item(binding.work_item_id)["status"] == "failed"
