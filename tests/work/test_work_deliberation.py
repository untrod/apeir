from __future__ import annotations

import json

from typer.testing import CliRunner

from nous_runtime.events import RunEvent
from nous_runtime.model_runtime import GatewayResponse
from nous_runtime.planner.plan import TaskStatus
from nous_runtime.work import ModelWorkDeliberator, WorkHarness
from nous_runtime.work.cli import work_app
from nous_runtime.work.deliberation import verify_recorded_work


class StubFacade:
    def __init__(self, decision):
        self.decision = decision
        self.requests = []

    def try_invoke_sync(self, request):
        self.requests.append(request)
        return GatewayResponse(
            request_id="request-1",
            structured_output=self.decision,
        )


def test_model_deliberator_uses_structured_gateway_contract(tmp_path):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Explain this behavior")
    facade = StubFacade(
        {
            "status": "complete",
            "summary": "The explanation is ready",
            "confidence": "high",
            "output": "answer",
        }
    )

    decision = ModelWorkDeliberator(
        facade,
        tool_capabilities=(
            {"category": "files", "tool_count": 3, "authority": "none"},
        ),
    )(harness.context_for(snapshot))

    assert decision.status.value == "complete"
    request = facade.requests[0]
    assert request.operation.value == "structured_output"
    assert request.response_schema["properties"]["status"]["enum"]
    assert request.metadata["source"] == "work.harness"
    assert request.metadata["temperature"] == 0.1
    assert "Do not choose blocked" in request.messages[0]["content"]
    assert "complete and blocked are invalid" in request.messages[0]["content"]
    assert request.timeout_s == 180.0
    assert request.budget.max_tokens == 384
    payload = json.loads(request.messages[1]["content"])
    assert payload["tool_capability_catalog"][0]["category"] == "files"
    assert payload["tool_capability_catalog"][0]["authority"] == "none"
    assert payload["work"]["conversation"] == {}
    assert "created_at" not in payload["work"]["goal"]
    assert all(
        "objective" not in event["payload"]
        and "plan" not in event["payload"]
        and "assessment" not in event["payload"]
        for event in payload["work"]["recent_events"]
    )


def test_model_deliberator_bounds_event_history_and_failure_text(tmp_path):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Fix the code in this repository")
    for index in range(12):
        harness.events.emit(
            RunEvent(
                run_id=snapshot.run_id,
                task_id=snapshot.goal.goal_id,
                event_type="run.failed",
                actor="test",
                payload={"reason": f"failure-{index}-" + ("x" * 600)},
            )
        )
    facade = StubFacade(
        {"status": "blocked", "summary": "done", "confidence": "high"}
    )

    ModelWorkDeliberator(facade)(harness.context_for(snapshot))

    payload = json.loads(facade.requests[0].messages[1]["content"])
    events = payload["work"]["recent_events"]
    assert len(events) == 6
    assert events[-1]["payload"]["reason"].endswith("…")
    assert len(events[-1]["payload"]["reason"]) == 201


def test_model_deliberator_deduplicates_catalog_observation_schemas(tmp_path):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Fix the code in this repository")
    tool = {
        "tool_id": "read_file",
        "description": "Read one file",
        "effect_class": "read",
        "approval_policy": "none",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "description": "large duplicate"},
        "metadata": {"provider": "workspace"},
    }
    snapshot.loaded_tools["read_file"] = tool
    snapshot.observations.append(
        {
            "kind": "tool",
            "tool": "catalog_expand",
            "ok": True,
            "result": {"ok": True, "category": "files", "tools": [tool]},
        }
    )
    facade = StubFacade(
        {"status": "blocked", "summary": "done", "confidence": "high"}
    )

    ModelWorkDeliberator(facade)(harness.context_for(snapshot))

    work = json.loads(facade.requests[0].messages[1]["content"])["work"]
    assert work["recent_observations"][-1]["result"]["tool_ids"] == ["read_file"]
    assert "tools" not in work["recent_observations"][-1]["result"]
    assert "output_schema" not in work["loaded_tools"][0]


def test_recorded_work_verifier_requires_tool_evidence_when_assessed(tmp_path):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Fix the code in this repository")

    missing = verify_recorded_work(harness.context_for(snapshot))
    snapshot.observations.append(
        {"kind": "tool", "tool": "write_file", "ok": True, "result": {"ok": True}}
    )
    for task in snapshot.plan.tasks:
        if task.task_id != "verify":
            task.status = TaskStatus.COMPLETED
    recorded = verify_recorded_work(harness.context_for(snapshot))

    assert missing["ok"] is False
    assert recorded["ok"] is True


def test_recorded_work_verifier_uses_latest_result_for_current_plan(tmp_path):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Fix the code in this repository")
    revision = snapshot.plan.revision
    snapshot.observations.extend(
        (
            {
                "kind": "tool",
                "tool": "workspace_action",
                "step_id": "execute_1",
                "ok": False,
                "plan_revision": revision,
            },
            {
                "kind": "tool",
                "tool": "workspace_action",
                "step_id": "execute_1",
                "ok": True,
                "plan_revision": revision,
            },
        )
    )
    for task in snapshot.plan.tasks:
        if task.task_id != "verify":
            task.status = TaskStatus.COMPLETED

    result = verify_recorded_work(harness.context_for(snapshot))

    assert result["ok"] is True
    assert result["failed_tool_observations"] == 0


def test_work_cli_lists_durable_runs_without_loading_a_model(tmp_path):
    harness = WorkHarness(tmp_path)
    created = harness.create("Explain one function")

    result = CliRunner().invoke(
        work_app,
        ["list", "--root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    assert created.run_id in result.stdout
