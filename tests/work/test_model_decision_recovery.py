"""Rejected model data must not become an action or destroy original Work."""

from __future__ import annotations

import json

import pytest

from nous_runtime.events import RunState
from nous_runtime.model_runtime import GatewayResponse
from nous_runtime.work import ModelWorkDeliberator, WorkHarness
from nous_runtime.work.models import InvalidModelDecision
from tests.work.test_work_deliberation import StubFacade


def _decision(**fields):
    return {
        "status": "ask_user",
        "summary": "Review the task",
        "confidence": "high",
        **fields,
    }


@pytest.mark.parametrize(
    "value",
    [
        _decision(status="replan"),
        _decision(plan_revision_required=True),
        _decision(plan_revision_required="false"),
        _decision(status="continue"),
        _decision(status="continue", next_action="  "),
        _decision(summary=42),
        _decision(summary="  "),
        _decision(confidence="certain"),
        _decision(tool_arguments=[]),
        _decision(action_source="approved_replay"),
        _decision(approval_granted=True),
        _decision(work={"status": "complete"}),
        _decision(output=float("nan")),
        _decision(output=float("inf")),
    ],
)
def test_invalid_response_waits_without_actions_and_preserves_original_work(
    tmp_path, value
):
    harness = WorkHarness(tmp_path)
    original = harness.create(
        "Explain a bounded concept",
        execution_options={"preferred_model": "chosen-model"},
    )
    facade = StubFacade(value)
    result = harness.run(original.run_id, deliberator=ModelWorkDeliberator(facade))
    assert result.state is RunState.WAITING_USER
    assert len(facade.requests) == 1
    assert result.last_decision is None
    assert not result.pending_action and result.action_sequence == 0
    reopened = WorkHarness(tmp_path).require(original.run_id)
    assert reopened.state is RunState.WAITING_USER
    assert reopened.goal.goal_id == original.goal.goal_id
    assert reopened.execution_options == original.execution_options
    assert "No tool was dispatched" in reopened.error
    assert len(harness.list()) == 1


@pytest.mark.parametrize(
    "steps",
    [
        [
            {"step_id": "a", "description": "one"},
            {"step_id": "a", "description": "two"},
        ],
        [{"step_id": "a", "description": "one", "depends_on": ["missing"]}],
        [{"step_id": "a", "description": "one", "depends_on": ["a"]}],
        [
            {"step_id": "a", "description": "one", "depends_on": ["b"]},
            {"step_id": "b", "description": "two", "depends_on": ["a"]},
        ],
    ],
)
def test_invalid_model_dag_does_not_replace_the_original_plan(tmp_path, steps):
    harness = WorkHarness(tmp_path)
    original = harness.create("Inspect and fix a Python project")
    before = original.plan.to_dict()
    facade = StubFacade(
        _decision(status="replan", plan_revision_required=True, replacement_steps=steps)
    )
    result = harness.run(original.run_id, deliberator=ModelWorkDeliberator(facade))
    assert result.state is RunState.WAITING_USER
    assert result.error.startswith("MODEL_PLAN_INVALID:")
    assert result.plan.plan_id == before["plan_id"]
    assert result.plan.revision == before["revision"]
    assert result.plan.to_dict()["tasks"] == before["tasks"]


def test_invalid_response_requires_explicit_resume_after_restart(tmp_path):
    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")
    facade = StubFacade(_decision(status="replan"))
    waiting = harness.run(original.run_id, deliberator=ModelWorkDeliberator(facade))
    failed_agent = waiting.agent_run_id
    reopened = WorkHarness(tmp_path)
    assert reopened.require(original.run_id).state is RunState.WAITING_USER
    assert len(facade.requests) == 1
    # A normal run/read is not permission to retry inference.
    assert (
        reopened.run(original.run_id, deliberator=ModelWorkDeliberator(facade)).state
        is RunState.WAITING_USER
    )
    assert len(facade.requests) == 1
    facade.decision = _decision(status="complete", output="A bounded answer")
    completed = reopened.resume(
        original.run_id, deliberator=ModelWorkDeliberator(facade)
    )
    assert completed.state is RunState.COMPLETED
    assert completed.run_id == original.run_id
    assert completed.result == "A bounded answer"
    assert completed.agent_run_id and completed.agent_run_id != failed_agent
    assert len(facade.requests) == 2
    assert len(reopened.list()) == 1


def test_invalid_diagnostic_never_copies_rejected_model_values(tmp_path):
    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")
    secret = "UNTRUSTED_PRIVATE_MODEL_TEXT_9548"
    facade = StubFacade(_decision(status=secret, summary=secret))
    result = harness.run(original.run_id, deliberator=ModelWorkDeliberator(facade))
    assert result.state is RunState.WAITING_USER
    assert secret not in json.dumps(result.to_dict())
    records = [event.to_dict() for event in harness.events.load_events(original.run_id)]
    assert secret not in json.dumps(records)
    invalid = [
        event for event in records if event["event_type"] == "work.model.invalid"
    ]
    assert len(invalid) == 1
    assert invalid[0]["payload"]["request_id"] == "request-1"
    assert invalid[0]["payload"]["automatic_replay"] is False


@pytest.mark.parametrize(
    "arguments", ["[]", '{"path":"a.py"}', '{"path":7,"content":"x"}', "{bad"]
)
def test_invalid_native_arguments_are_rejected_before_work_dispatch(
    tmp_path, arguments
):
    harness = WorkHarness(tmp_path)
    original = harness.create("Fix a Python project")
    original.loaded_tools["write_file"] = {
        "tool_id": "write_file",
        "effect_class": "write",
        "input_schema": {
            "type": "object",
            "required": ["path", "content"],
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        },
    }
    original.observations.append(
        {
            "kind": "tool",
            "tool": "read_file",
            "ok": True,
            "result": {"path": "a.py", "content": "source"},
        }
    )
    facade = StubFacade(
        None, tool_calls=({"function": {"name": "write_file", "arguments": arguments}},)
    )
    with pytest.raises(InvalidModelDecision, match="invalid native action"):
        ModelWorkDeliberator(facade)(harness.context_for(original))
    assert not original.pending_action and original.action_sequence == 0
    assert not (tmp_path / "a.py").exists()


@pytest.mark.parametrize("finish_reason", ["length", "completed"])
def test_absent_or_truncated_decision_is_recoverable_without_inference_retry(
    tmp_path, finish_reason
):
    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")
    facade = StubFacade(None, finish_reason=finish_reason)
    result = harness.run(original.run_id, deliberator=ModelWorkDeliberator(facade))
    assert result.state is RunState.WAITING_USER
    assert len(facade.requests) == 1
    assert (
        "MODEL_OUTPUT_TRUNCATED" in result.error
        if finish_reason == "length"
        else "MODEL_DECISION_MISSING" in result.error
    )


def test_non_model_execution_errors_still_fail(tmp_path):
    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")

    def defect(_context):
        raise RuntimeError("unexpected host defect")

    assert harness.run(original.run_id, deliberator=defect).state is RunState.FAILED


@pytest.mark.parametrize("model", ["", "local/code-model", "cloud/review-model"])
def test_task_projection_preserves_explicit_model_selection(tmp_path, model):
    from nous_runtime.api.desktop_routes import _work_task_projection

    original = WorkHarness(tmp_path).create(
        "Explain one concept", execution_options={"preferred_model": model}
    )
    assert _work_task_projection(original)["model_id"] == (model or "auto")


@pytest.mark.parametrize(
    "arguments", [{}, {"path": 4}, {"path": "a.py", "grant": "execute"}]
)
def test_structured_actions_validate_the_loaded_schema_before_dispatch(
    tmp_path, arguments
):
    harness = WorkHarness(tmp_path)
    original = harness.create("Read the project source")
    original.loaded_tools["read_file"] = {
        "tool_id": "read_file",
        "effect_class": "read",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    }
    facade = StubFacade(
        _decision(status="continue", tool_name="read_file", tool_arguments=arguments)
    )
    with pytest.raises(InvalidModelDecision) as caught:
        ModelWorkDeliberator(facade)(harness.context_for(original))
    assert caught.value.code == "MODEL_TOOL_ARGUMENTS_INVALID"
    assert original.action_sequence == 0


def test_valid_dag_and_loaded_action_keep_original_semantics(tmp_path):
    harness = WorkHarness(tmp_path)
    original = harness.create("Inspect a Python project")
    value = _decision(
        status="replan",
        plan_revision_required=True,
        replacement_steps=[
            {"step_id": "inspect", "description": "Inspect sources"},
            {
                "step_id": "review",
                "description": "Review results",
                "depends_on": ["inspect"],
            },
        ],
    )
    decision = ModelWorkDeliberator(StubFacade(value))(harness.context_for(original))
    assert decision.plan_revision_required is True
    assert decision.replacement_steps[1].depends_on == ("inspect",)
    facade = StubFacade(
        _decision(status="continue", tool_name="unloaded_tool", tool_arguments={})
    )
    with pytest.raises(InvalidModelDecision) as caught:
        ModelWorkDeliberator(facade)(harness.context_for(original))
    assert caught.value.code == "MODEL_TOOL_UNAVAILABLE"
    schema = facade.requests[0].response_schema
    assert "allOf" not in schema and "if" not in schema


def test_model_phase_cannot_override_recorded_work_progress(tmp_path):
    harness = WorkHarness(tmp_path)
    original = harness.create("Inspect the project source")
    before = original.to_dict()
    decision = ModelWorkDeliberator(StubFacade(_decision(phase="COMPLETE")))(
        harness.context_for(original)
    )
    assert decision.phase == "INSPECT"
    assert original.to_dict() == before


@pytest.mark.parametrize(
    "reference",
    [
        "https://schemas.example.invalid/input.json",
        "file:///private-input.json",
        "#/missing",
    ],
)
@pytest.mark.parametrize("native", [False, True])
def test_tool_schema_validation_cannot_read_external_resources(
    tmp_path, monkeypatch, reference, native
):
    import urllib.request

    def forbidden(*args, **kwargs):
        pytest.fail("Schema validation must not acquire network or file resources")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    harness = WorkHarness(tmp_path)
    original = harness.create("Fix a Python project")
    original.loaded_tools["write_file"] = {
        "tool_id": "write_file",
        "effect_class": "write",
        "input_schema": {"$ref": reference},
    }
    original.observations.append(
        {
            "kind": "tool",
            "tool": "read_file",
            "ok": True,
            "result": {"path": "a.py", "content": "source"},
        }
    )
    if native:
        facade = StubFacade(
            None,
            tool_calls=(
                {
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "a.py", "content": "changed"},
                    }
                },
            ),
        )
    else:
        original.loaded_tools["write_file"]["effect_class"] = "read"
        facade = StubFacade(
            _decision(
                status="continue",
                tool_name="write_file",
                tool_arguments={"path": "a.py", "content": "changed"},
            )
        )
    with pytest.raises(InvalidModelDecision):
        ModelWorkDeliberator(facade)(harness.context_for(original))
    assert original.action_sequence == 0
    assert not (tmp_path / "a.py").exists()


@pytest.mark.parametrize("number", [0, 1])
def test_declared_legacy_tool_schema_dialect_is_preserved(tmp_path, number):
    harness = WorkHarness(tmp_path)
    original = harness.create("Inspect a metric")
    original.loaded_tools["read_metric"] = {
        "tool_id": "read_metric",
        "effect_class": "read",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "type": "object",
            "required": ["n"],
            "properties": {
                "n": {"type": "number", "minimum": 0, "exclusiveMinimum": True}
            },
        },
    }
    facade = StubFacade(
        _decision(
            status="continue", tool_name="read_metric", tool_arguments={"n": number}
        )
    )
    model = ModelWorkDeliberator(facade)
    if number == 0:
        with pytest.raises(InvalidModelDecision):
            model(harness.context_for(original))
    else:
        assert model(harness.context_for(original)).tool_arguments == {"n": 1}


@pytest.mark.parametrize(
    "error,code",
    [
        ({"http_status": 401}, "MODEL_PROVIDER_AUTHENTICATION"),
        ({"http_status": 402}, "MODEL_PROVIDER_ACCOUNT"),
        ({"http_status": 403}, "MODEL_PROVIDER_ACCESS"),
        ({"http_status": 404}, "MODEL_PROVIDER_ENDPOINT"),
        ({"type": "ModelRoutingError"}, "MODEL_ROUTE_UNAVAILABLE"),
        (
            {"provider_error_code": "NOUS_MODEL_PARAMETER_UNSUPPORTED"},
            "MODEL_CONFIGURATION_UNSUPPORTED",
        ),
    ],
)
def test_model_configuration_failures_preserve_original_work_without_retry(
    tmp_path, error, code
):
    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")

    class RefusedFacade:
        calls = 0

        def try_invoke_sync(self, request):
            self.calls += 1
            assert request.fallback.allowed is False
            assert request.fallback.max_retries_per_model == 0
            return GatewayResponse(
                request_id="refused-original",
                error={**error, "message": "UNTRUSTED_PROVIDER_ERROR_TEXT"},
            )

    facade = RefusedFacade()
    result = harness.run(
        original.run_id,
        deliberator=ModelWorkDeliberator(facade, preferred_model="local/selected"),
    )
    assert result.state is RunState.WAITING_USER
    assert result.error.startswith(code + ":")
    assert "UNTRUSTED_PROVIDER_ERROR_TEXT" not in result.error
    assert facade.calls == 1
    assert result.run_id == original.run_id and not result.pending_action


def test_explicit_model_never_falls_back_to_another_available_model(
    tmp_path, monkeypatch
):
    from tests.model_runtime.test_gateway_facade import build_facade

    harness = WorkHarness(tmp_path)
    original = harness.create("Explain one concept")
    facade, adapter = build_facade(
        {"status": "complete", "summary": "Wrong model", "confidence": "high"}
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("An unselected model must not be invoked")

    monkeypatch.setattr(adapter, "invoke", forbidden)
    try:
        result = harness.run(
            original.run_id,
            deliberator=ModelWorkDeliberator(
                facade, preferred_model="local/not-configured"
            ),
        )
        assert result.state is RunState.WAITING_USER
        assert result.error.startswith("MODEL_ROUTE_UNAVAILABLE:")
        assert not any(
            event.event_type == "model.invoke.completed"
            for event in facade.gateway.events
        )
    finally:
        facade.gateway.close_sync_bridge()


def test_original_work_records_private_input_manifests_and_unique_invocations(tmp_path):
    harness = WorkHarness(tmp_path)
    private_goal = "PRIVATE_QUALIFICATION_OBJECTIVE not for general telemetry"
    original = harness.create(private_goal)
    context = harness.context_for(original)
    for _ in range(2):
        # A host restart can reset an in-memory iteration count. Correlation must
        # still distinguish the exact original invocation, not just iteration 1.
        facade = StubFacade(
            _decision(),
            usage={"input_tokens": 13, "output_tokens": 2, "total_tokens": 15},
        )
        ModelWorkDeliberator(facade, event_stream=harness.events)(context)
    events = harness.events.load_events(original.run_id)
    starts = [
        event for event in events if event.event_type == "model.invocation.started"
    ]
    ends = [
        event for event in events if event.event_type == "model.invocation.completed"
    ]
    assert len(starts) == len(ends) == 2
    assert starts[0].payload["invocation_id"] != starts[1].payload["invocation_id"]
    assert [event.payload["invocation_id"] for event in starts] == [
        event.payload["invocation_id"] for event in ends
    ]
    for event in starts:
        manifest = event.payload["input_manifest"]
        assert manifest["scope"] == "prepared-work-gateway-input"
        assert manifest["raw_content_recorded"] is False
        assert manifest["execution_authority"] is False
        assert private_goal not in json.dumps(event.to_dict())
    assert ends[-1].payload["usage"]["total_tokens"] == 15
    assert ends[-1].payload["cost_usd"] is None
    assert harness.require(original.run_id).run_id == original.run_id
