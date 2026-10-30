"""Typed data flow uses original Workflow checkpoints, never another executor."""

from copy import deepcopy
import json

import pytest

from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowStep,
    WorkflowValidationError,
)
from nous_runtime.workflow.models import definition_from_dict, definition_to_dict
from nous_runtime.workflow.store import WorkflowStore, binding_digest
from tests.test_workflow_safety import policy
from tests.test_workflow_studio_api import api as api


def contract(source="inputs", pointer="/payload", step_id="source", **schemas):
    ref = {"source": source, "pointer": pointer}
    if source == "step":
        ref["step_id"] = step_id
    return {"schema_version": 1, "inputs": {"value": ref}, **schemas}


def definition(*steps):
    return WorkflowDefinition("typed.data", "1", TriggerType.MANUAL, tuple(steps))


def test_legacy_definition_bytes_and_digest_remain_unchanged():
    old = WorkflowDefinition(
        "legacy.bindings",
        "1",
        TriggerType.MANUAL,
        (WorkflowStep("legacy", StepType.TRANSFORM, params={"value": 3}),),
    )
    value = definition_to_dict(old)
    assert "data_bindings" not in value["steps"][0]
    assert definition_to_dict(definition_from_dict(value)) == value
    assert (
        WorkflowStore.definition_digest(old)
        == "9cfbfb6473b2dc99b3879f1468816c1c85a25ea3d48f3a1c26b42a7b0b63e1c0"
    )


def test_legacy_skipped_output_does_not_change_strict_result_schema(tmp_path):
    spec = WorkflowDefinition(
        "legacy.skipped",
        "1",
        TriggerType.MANUAL,
        (
            WorkflowStep(
                "condition",
                StepType.CONDITION,
                params={"input": "enabled", "equals": True},
            ),
            WorkflowStep(
                "result",
                StepType.TRANSFORM,
                depends_on=("condition",),
                params={"value": "legacy"},
            ),
        ),
        outputs_schema={
            "type": "object",
            "properties": {"result": {"type": "object"}},
            "required": ["result"],
            "additionalProperties": False,
        },
    )
    runtime = WorkflowRuntime(str(tmp_path))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, {"enabled": False})
    assert run.state.value == "completed" and "condition" not in run.outputs


def test_typed_result_flows_from_persisted_source_and_keeps_original_run(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    integer = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    spec = definition(
        WorkflowStep("source", StepType.TRANSFORM, data_bindings=contract()),
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            depends_on=("source",),
            data_bindings=contract(
                "step", "/value/items/0", inputs_schema=integer, outputs_schema=integer
            ),
        ),
    )
    runtime.register(spec)
    run = runtime.start(
        spec.workflow_id,
        spec.version,
        {"payload": {"items": [42]}},
        idempotency_key="original",
    )
    assert run.state.value == "completed" and run.outputs["consumer"]["value"] == 42
    checkpoints = runtime.store.checkpoints(run.run_id)
    bound = checkpoints["consumer"]["data_binding"]
    assert bound["params_digest"] == binding_digest({"value": 42})
    assert (
        bound["sources"]["value"]["source_digest"]
        == checkpoints["source"]["output_digest"]
    )
    restored = WorkflowRuntime(str(tmp_path))
    assert restored.resume(run.run_id).outputs == run.outputs
    assert (
        restored.start(
            spec.workflow_id,
            spec.version,
            {"payload": {"items": [42]}},
            idempotency_key="original",
        ).run_id
        == run.run_id
    )
    assert restored.store.checkpoints(run.run_id) == checkpoints


@pytest.mark.parametrize("value", [None, False, 0, {}, []])
def test_empty_and_false_values_are_data_not_missing_results(tmp_path, value):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(
        WorkflowStep("source", StepType.TRANSFORM, params={"value": value}),
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            depends_on=("source",),
            data_bindings=contract("step", "/value"),
        ),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state.value == "completed"
    assert run.outputs["consumer"]["value"] == value


def test_empty_handler_result_survives_projection_and_restart(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path), handlers={"empty": lambda *_: {}})
    spec = definition(
        WorkflowStep("source", StepType.CAPABILITY, action="empty"),
        WorkflowStep("review", StepType.APPROVAL, depends_on=("source",)),
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            depends_on=("source", "review"),
            data_bindings=contract("step", ""),
        ),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert runtime.store.checkpoints(run.run_id)["source"]["output"] == {}
    assert "source" not in run.outputs
    restored = WorkflowRuntime(
        str(tmp_path),
        handlers={"empty": lambda *_: pytest.fail("Completed source replayed")},
    )
    result = restored.resume(run.run_id, approved_steps=("review",))
    assert (
        result.state.value == "completed" and result.outputs["consumer"]["value"] == {}
    )


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "boolean-version",
        "extra",
        "missing-dependency",
        "collision",
        "bad-pointer",
        "private-pointer",
        "external-schema",
        "invalid-schema",
        "bad-source",
        "authority-field",
    ],
)
def test_bad_contract_cannot_be_registered_or_dispatch(tmp_path, change):
    data = contract()
    params = {}
    if change == "version":
        data["schema_version"] = 2
    elif change == "boolean-version":
        data["schema_version"] = True
    elif change == "extra":
        data["javascript"] = "run()"
    elif change == "missing-dependency":
        data = contract("step", "/value", "unrelated")
    elif change == "collision":
        params["value"] = 9
    elif change == "bad-pointer":
        data["inputs"]["value"]["pointer"] = "/bad~2escape"
    elif change == "private-pointer":
        data["inputs"]["value"]["pointer"] = "/_approved_steps"
    elif change == "external-schema":
        data["inputs_schema"] = {"$ref": "https://untrusted.invalid/schema"}
    elif change == "invalid-schema":
        data["outputs_schema"] = {"type": "imaginary"}
    elif change == "bad-source":
        data["inputs"]["value"]["source"] = []
    elif change == "authority-field":
        data["inputs"]["value"]["approval"] = True
    runtime = WorkflowRuntime(str(tmp_path))
    with pytest.raises(WorkflowValidationError):
        runtime.register(
            definition(
                WorkflowStep(
                    "consumer", StepType.TRANSFORM, params=params, data_bindings=data
                )
            )
        )
    assert runtime.store.list_definitions() == []


@pytest.mark.parametrize("pointer", ["/missing", "/items/01", "/items/4", "/items/-"])
def test_missing_data_fails_before_consumer_dispatch(tmp_path, pointer):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path), handlers={"consume": lambda *_: calls.append(1) or {}}
    )
    spec = definition(
        WorkflowStep(
            "consumer",
            StepType.CAPABILITY,
            action="consume",
            data_bindings=contract(pointer=pointer),
        )
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, {"items": [1]})
    assert run.state.value == "failed" and calls == []
    assert runtime.store.checkpoints(run.run_id)["consumer"]["attempts"] == 0
    assert runtime.resume(run.run_id).state.value == "failed" and calls == []


def test_reference_decoding_and_private_run_metadata_are_separate(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            data_bindings=contract(pointer="/a~1b/~0value"),
        )
    )
    runtime.register(spec)
    run = runtime.start(
        spec.workflow_id,
        spec.version,
        {"a/b": {"~value": "source-value-unique"}, "_internal": "host-only"},
    )
    assert run.outputs["consumer"]["value"] == "source-value-unique"
    manifest = runtime.store.checkpoints(run.run_id)["consumer"]["data_binding"]
    assert "source-value-unique" not in json.dumps(
        manifest
    ) and "host-only" not in json.dumps(manifest)


def test_invalid_input_does_not_compensate_or_replay_prior_effect(tmp_path):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "effect": lambda *_: (
                calls.append("effect") or {"value": "PRIVATE_WRONG_TYPE"}
            ),
            "undo": lambda *_: calls.append("undo") or {},
        },
    )
    spec = definition(
        WorkflowStep(
            "source", StepType.CAPABILITY, action="effect", compensation="undo"
        ),
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            depends_on=("source",),
            retries=3,
            data_bindings=contract(
                "step",
                "/value",
                inputs_schema={"properties": {"value": {"type": "integer"}}},
            ),
        ),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state.value == "failed" and "PRIVATE_WRONG_TYPE" not in run.error
    assert runtime.resume(run.run_id).state.value == "failed"
    assert (
        calls == ["effect"] and run.outputs["source"]["value"] == "PRIVATE_WRONG_TYPE"
    )


@pytest.mark.parametrize("effect", ["none", "external_write"])
def test_wrong_output_schema_preserves_original_effect_and_never_retries(
    tmp_path, effect
):
    calls = []

    def execute(*_):
        calls.append(1)
        (tmp_path / "effect.txt").write_text(str(len(calls)))
        return {"value": "wrong"}

    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"compute": execute},
        handler_policies={
            "compute": policy(capability_id="compute", effect=effect, retries=3)
        },
    )
    spec = definition(
        WorkflowStep(
            "compute",
            StepType.CAPABILITY,
            action="compute",
            retries=3,
            data_bindings={
                "schema_version": 1,
                "outputs_schema": {"properties": {"value": {"type": "integer"}}},
            },
        )
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, idempotency_key="once")
    expected = "failed" if effect == "none" else "unknown"
    assert run.state.value == expected and run.outputs["compute"]["value"] == "wrong"
    restored = WorkflowRuntime(
        str(tmp_path),
        handlers=runtime.handlers,
        handler_policies=runtime.handler_policies,
    )
    assert restored.resume(run.run_id).state.value == expected
    assert (
        restored.start(spec.workflow_id, spec.version, idempotency_key="once").run_id
        == run.run_id
    )
    assert calls == [1] and (tmp_path / "effect.txt").read_text() == "1"


@pytest.mark.parametrize("tamper", ["source", "binding", "missing-binding"])
def test_changed_evidence_stays_unknown_after_approval_and_restart(tmp_path, tamper):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(
        WorkflowStep("source", StepType.TRANSFORM, params={"value": 7}),
        WorkflowStep(
            "consumer",
            StepType.TRANSFORM,
            depends_on=("source",),
            approval_required=True,
            data_bindings=contract("step", "/value"),
        ),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state.value == "waiting_approval"
    key = "source" if tamper == "source" else "consumer"
    checkpoint = deepcopy(runtime.store.checkpoints(run.run_id)[key])
    if tamper == "source":
        checkpoint["output"]["value"] = 9
    elif tamper == "binding":
        checkpoint["data_binding"]["params_digest"] = "changed"
    else:
        checkpoint.pop("data_binding")
    runtime.store.checkpoint(run.run_id, key, checkpoint)
    restored = WorkflowRuntime(str(tmp_path)).resume(
        run.run_id, approved_steps=("consumer",)
    )
    assert restored.state.value == "unknown"
    assert runtime.store.checkpoints(run.run_id)["consumer"]["attempts"] == 0


def test_existing_governed_api_runs_the_same_bound_definition_and_exposes_digests(api):
    call, _, _ = api
    spec = definition_to_dict(
        definition(
            WorkflowStep("source", StepType.TRANSFORM, params={"value": 12}),
            WorkflowStep(
                "consumer",
                StepType.TRANSFORM,
                depends_on=("source",),
                data_bindings=contract("step", "/value"),
            ),
        )
    )
    assert call("GET", "/api/v1/workflow")["data"]["data_bindings_versions"] == [1]
    assert not call(
        "POST", "/api/v1/workflow/register", {"definition": spec}, auth=False
    )["ok"]
    assert call(
        "POST", "/api/v1/workflow/register", {"definition": spec}, approve=True
    )["ok"]
    body = {
        "workflow_id": spec["workflow_id"],
        "version": "1",
        "inputs": {},
        "idempotency_key": "original",
        "definition": spec,
    }
    result = call("POST", "/api/v1/workflow/run", body, approve=True)
    assert result["ok"], result
    run = result["data"]
    assert run["outputs"]["consumer"]["value"] == 12
    detail = call("GET", f"/api/v1/workflow/runs/{run['run_id']}")["data"]
    assert detail["step_bindings"]["consumer"]["data_binding"][
        "params_digest"
    ] == binding_digest({"value": 12})
    assert (
        call("POST", "/api/v1/workflow/run", body, approve=True)["data"]["run_id"]
        == run["run_id"]
    )
    runtime = WorkflowRuntime(str(api[2]))
    runtime.store.checkpoint(
        run["run_id"],
        "private:aux",
        {"data_binding": {"private_notes": "PRIVATE_AUXILIARY_CONTENT"}},
    )
    original = runtime.store.checkpoints(run["run_id"])["consumer"]
    original["data_binding"]["sources"]["value"]["private_notes"] = (
        "PRIVATE_AUXILIARY_CONTENT"
    )
    original["data_binding"]["params_digest"] = "PRIVATE_INVALID_DIGEST"
    runtime.store.checkpoint(run["run_id"], "consumer", original)
    guarded = call("GET", f"/api/v1/workflow/runs/{run['run_id']}")["data"][
        "step_bindings"
    ]
    assert "private:aux" not in guarded and "PRIVATE" not in json.dumps(guarded)
    assert guarded["consumer"]["data_binding"]["params_digest"] is None
    assert (
        guarded["consumer"]["data_binding"]["sources"]["value"]["reference_matches"]
        is False
    )


def test_cancel_between_data_read_and_admission_blocks_consumer(tmp_path, monkeypatch):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path), handlers={"consume": lambda *_: calls.append(1) or {}}
    )
    spec = definition(
        WorkflowStep(
            "consumer", StepType.CAPABILITY, action="consume", data_bindings=contract()
        )
    )
    runtime.register(spec)
    original = runtime.compiler.resolve_step_bindings

    def cancel_after_read(*args):
        params = original(*args)
        runtime.cancel(runtime.store.history(spec.workflow_id)[0].run_id)
        return params

    monkeypatch.setattr(runtime.compiler, "resolve_step_bindings", cancel_after_read)
    run = runtime.start(spec.workflow_id, spec.version, {"payload": "reviewed"})
    assert run.cancellation_requested and calls == []
    assert runtime.store.checkpoints(run.run_id) == {}
    assert WorkflowRuntime(str(tmp_path)).resume(run.run_id).state.value == "cancelled"


@pytest.mark.parametrize("kind", ["nonfinite", "cyclic", "object"])
def test_noncanonical_result_keeps_a_durable_failure_fence(tmp_path, kind):
    calls = []

    def execute(*_):
        calls.append(1)
        result = {"value": float("nan") if kind == "nonfinite" else object()}
        if kind == "cyclic":
            result["value"] = result
        return result

    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"compute": execute},
        handler_policies={
            "compute": policy(capability_id="compute", effect="none", retries=3)
        },
    )
    spec = definition(
        WorkflowStep(
            "compute",
            StepType.CAPABILITY,
            "compute",
            retries=3,
            data_bindings={"schema_version": 1},
        )
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    checkpoint = runtime.store.checkpoints(run.run_id)["compute"]
    assert checkpoint["data_validation_failed"] and checkpoint["output"] == {}
    assert run.state.value == "failed" and "unavailable" in run.error
    assert runtime.resume(run.run_id).state.value == "failed" and calls == [1]
