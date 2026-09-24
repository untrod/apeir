from __future__ import annotations

from typer.testing import CliRunner

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

    decision = ModelWorkDeliberator(facade)(harness.context_for(snapshot))

    assert decision.status.value == "complete"
    request = facade.requests[0]
    assert request.operation.value == "structured_output"
    assert request.response_schema["properties"]["status"]["enum"]
    assert request.metadata["source"] == "work.harness"


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
