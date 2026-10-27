"""Declared Workflow schemas constrain canonical execution and persisted results."""

from dataclasses import replace

import pytest

from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowState,
    WorkflowStep,
    WorkflowValidationError,
)
from tests.test_workflow_studio_api import api as api


def definition():
    return WorkflowDefinition(
        "schema.workflow",
        "1",
        TriggerType.MANUAL,
        (WorkflowStep("compute", StepType.TRANSFORM, params={"value": 3}),),
        inputs_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        outputs_schema={
            "type": "object",
            "properties": {
                "compute": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                }
            },
            "required": ["compute"],
        },
    )


@pytest.mark.parametrize(
    "inputs", [{}, {"count": "PRIVATE_BAD_VALUE"}, {"count": 1, "extra": 2}]
)
def test_invalid_input_is_rejected_before_creating_or_dispatching_a_run(
    tmp_path, inputs
):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"transform": lambda *_: calls.append(1) or {"value": 1}},
    )
    spec = definition()
    runtime.register(spec)
    with pytest.raises(WorkflowValidationError) as error:
        runtime.start(spec.workflow_id, spec.version, inputs)
    assert "PRIVATE_BAD_VALUE" not in str(error.value)
    assert calls == []
    assert runtime.store.history(spec.workflow_id) == []


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "unsupported-type"},
        {"required": "count"},
        {"$schema": "https://untrusted.invalid/schema"},
        {"$ref": "https://untrusted.invalid/schema"},
    ],
)
def test_invalid_or_external_schema_is_rejected_on_registration(tmp_path, schema):
    runtime = WorkflowRuntime(str(tmp_path))
    with pytest.raises(WorkflowValidationError):
        runtime.register(replace(definition(), inputs_schema=schema))
    assert runtime.store.list_definitions() == []


def test_local_schema_references_and_draft_seven_remain_usable(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = replace(
        definition(),
        inputs_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"count": {"$ref": "#/definitions/count"}},
            "definitions": {"count": {"type": "integer"}},
            "required": ["count"],
        },
    )
    runtime.register(spec)
    assert (
        runtime.start(spec.workflow_id, spec.version, {"count": 1}).state
        is WorkflowState.COMPLETED
    )
    with pytest.raises(WorkflowValidationError):
        runtime.start(spec.workflow_id, spec.version, {"count": "wrong"})


def test_output_failure_keeps_original_results_and_does_not_replay_after_restart(
    tmp_path,
):
    calls = []

    def handler(*_):
        calls.append(1)
        return {"value": "wrong-type"}

    spec = definition()
    runtime = WorkflowRuntime(str(tmp_path), handlers={"transform": handler})
    runtime.register(spec)
    run = runtime.start(
        spec.workflow_id, spec.version, {"count": 1}, idempotency_key="original"
    )
    assert run.state is WorkflowState.FAILED
    assert "outputs" in run.error
    assert run.outputs["compute"]["value"] == "wrong-type"
    restored = WorkflowRuntime(str(tmp_path), handlers={"transform": handler})
    assert restored.resume(run.run_id).state is WorkflowState.FAILED
    assert (
        restored.start(
            spec.workflow_id, spec.version, {"count": 1}, idempotency_key="original"
        ).run_id
        == run.run_id
    )
    assert calls == [1]
    assert restored.store.checkpoints(run.run_id)["compute"]["output_digest"]


def test_trusted_approval_metadata_does_not_change_the_input_contract(tmp_path):
    spec = replace(
        definition(),
        steps=(WorkflowStep("review", StepType.APPROVAL), *definition().steps),
    )
    runtime = WorkflowRuntime(str(tmp_path))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, {"count": 1})
    assert run.state is WorkflowState.WAITING_APPROVAL
    assert (
        runtime.resume(run.run_id, approved_steps=("review",)).state
        is WorkflowState.COMPLETED
    )


@pytest.mark.parametrize("inputs", [[], False, 0, {"count": float("nan")}])
def test_non_object_or_non_finite_input_cannot_enter_execution(tmp_path, inputs):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition()
    runtime.register(spec)
    with pytest.raises(WorkflowValidationError):
        runtime.start(spec.workflow_id, spec.version, inputs)
    assert not runtime.store.history(spec.workflow_id)


def test_invalid_legacy_input_never_clears_uncertain_effect_state(tmp_path):
    from nous_runtime.workflow.models import WorkflowRun

    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"transform": lambda *_: calls.append(1) or {"value": 1}},
    )
    spec = definition()
    runtime.register(spec)
    legacy = runtime.store.create_run(
        WorkflowRun(
            spec.workflow_id,
            spec.version,
            {"count": "wrong"},
            state=WorkflowState.UNKNOWN,
        )
    )
    restored = runtime.resume(legacy.run_id)
    assert restored.state is WorkflowState.UNKNOWN
    assert calls == []


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), True, "60"])
def test_public_compiler_rejects_invalid_timeouts_consistently(tmp_path, timeout):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = replace(
        definition(), steps=(replace(definition().steps[0], timeout_seconds=timeout),)
    )
    with pytest.raises(WorkflowValidationError):
        runtime.compiler.compile(spec)


def test_unresolvable_local_reference_does_not_fetch_or_dispatch(tmp_path, monkeypatch):
    import urllib.request

    def unexpected_network(*_args, **_kwargs):
        pytest.fail("Schema validation must not fetch resources")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_network)
    runtime = WorkflowRuntime(str(tmp_path))
    spec = replace(definition(), inputs_schema={"$ref": "#/missing"})
    runtime.register(spec)
    with pytest.raises(WorkflowValidationError):
        runtime.start(spec.workflow_id, spec.version, {"count": 1})
    assert not runtime.store.history(spec.workflow_id)


def test_invalid_schema_and_actual_input_are_rejected_through_existing_api(api):
    from nous_runtime.workflow.models import definition_to_dict

    call, _, _ = api
    spec = definition_to_dict(definition())
    invalid = {**spec, "inputs_schema": {"type": "invalid"}}
    assert not call("POST", "/api/v1/workflow/validate", {"definition": invalid})["ok"]
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": spec}, approve=True
    )["ok"]
    response = call(
        "POST",
        "/api/v1/workflow/run",
        {
            "workflow_id": spec["workflow_id"],
            "version": "1",
            "inputs": {"count": "wrong"},
            "idempotency_key": "rejected",
        },
        approve=True,
    )
    assert not response["ok"]
    assert response["error"]["code"] == "NOUS_INVALID_REQUEST"


def test_public_cli_reports_schema_failure_without_private_input_or_traceback(
    tmp_path, monkeypatch
):
    import json
    from typer.testing import CliRunner
    from nous_runtime.workflow.cli import workflow_app
    from nous_runtime.workflow.models import definition_to_dict

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(definition_to_dict(definition())), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(workflow_app, ["register", str(path), "--json"]).exit_code == 0
    result = runner.invoke(
        workflow_app,
        [
            "run",
            "schema.workflow",
            "--version",
            "1",
            "--inputs",
            '{"count":"PRIVATE_CODE_EXCERPT"}',
            "--json",
        ],
    )
    assert result.exit_code != 0
    assert "PRIVATE_CODE_EXCERPT" not in result.output
    assert "Traceback" not in result.output
    assert "inputs" in result.output


@pytest.mark.parametrize(
    "kind", [StepType.TRANSFORM, StepType.WAIT, StepType.CONDITION, StepType.APPROVAL]
)
def test_unregistered_action_is_not_silently_executed_as_a_pure_builtin(tmp_path, kind):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = replace(
        definition(),
        inputs_schema={},
        outputs_schema={},
        steps=(WorkflowStep("custom", kind, action="missing.host.action"),),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.FAILED
    assert "no workflow handler" in run.error


def test_unimplemented_expression_does_not_become_a_skipped_or_completed_condition(
    tmp_path,
):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = replace(
        definition(),
        inputs_schema={},
        outputs_schema={},
        steps=(
            WorkflowStep(
                "condition",
                StepType.CONDITION,
                condition="requires.host.expression",
                params={"input": "missing", "equals": True},
            ),
        ),
    )
    runtime.register(spec)
    assert runtime.start(spec.workflow_id, spec.version).state is WorkflowState.FAILED


def test_explicit_host_action_can_still_bind_its_real_handler(tmp_path):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "host.action": lambda step, context: (
                calls.append(step.action) or {"actual": True}
            )
        },
    )
    spec = replace(
        definition(),
        inputs_schema={},
        outputs_schema={},
        steps=(WorkflowStep("custom", StepType.TRANSFORM, action="host.action"),),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.COMPLETED
    assert calls == ["host.action"]
    assert run.outputs["custom"]["actual"] is True
