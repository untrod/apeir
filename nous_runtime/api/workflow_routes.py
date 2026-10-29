"""Studio adapters over the canonical Workflow Runtime, Store and EventStream.

Canvas state never enters this API. Only the built-in, effect-free handlers are
bound here; host-specific handlers remain available through their existing hosts.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from nous_runtime.api.responses import err_response, ok_response
from nous_runtime.workflow import WorkflowRuntime
from nous_runtime.workflow.models import (
    StepType,
    definition_from_dict,
    definition_to_dict,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_BUILTINS = {StepType.TRANSFORM, StepType.WAIT, StepType.CONDITION, StepType.APPROVAL}


def workspace() -> Path:
    return (
        Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    )


def _bounded_json(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Workflow JSON nesting exceeds 12")
    if isinstance(value, dict):
        if any(not isinstance(key, str) or key.startswith("_") for key in value):
            raise ValueError("Reserved or invalid Workflow field")
        for item in value.values():
            _bounded_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _bounded_json(item, depth + 1)
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("Workflow numbers must be finite")
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ValueError("Workflow JSON value is invalid")


def validate_definition(data: Any):
    if not isinstance(data, dict):
        raise ValueError("WorkflowDefinition must be an object")
    if len(json.dumps(data, allow_nan=False).encode("utf-8")) > 96 * 1024:
        raise ValueError("WorkflowDefinition exceeds 96 KiB")
    _bounded_json(data)
    if set(data) - {
        "workflow_id",
        "version",
        "trigger",
        "steps",
        "inputs_schema",
        "outputs_schema",
        "audit_metadata",
    }:
        raise ValueError("Unknown WorkflowDefinition field")
    for key in ("workflow_id", "version"):
        if not isinstance(data.get(key), str) or not _IDENTIFIER.fullmatch(data[key]):
            raise ValueError(f"Invalid {key}")
    if data.get("trigger", "manual") not in {"manual", "schedule", "event", "webhook"}:
        raise ValueError("Unknown workflow trigger")
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise ValueError("Workflow requires 1 to 64 steps")
    for step in steps:
        if not isinstance(step, dict) or set(step) - {
            "step_id",
            "step_type",
            "action",
            "depends_on",
            "condition",
            "retries",
            "timeout_seconds",
            "approval_required",
            "compensation",
            "params",
            "data_bindings",
        }:
            raise ValueError("Unknown workflow step field")
        if not isinstance(step.get("step_id"), str) or not _IDENTIFIER.fullmatch(
            step["step_id"]
        ):
            raise ValueError("Invalid step_id")
        StepType(step.get("step_type"))
        for key in ("action", "condition", "compensation"):
            if not isinstance(step.get(key, ""), str):
                raise ValueError(f"Invalid {key}")
        dependencies = step.get("depends_on", [])
        if (
            not isinstance(dependencies, list)
            or any(not isinstance(item, str) for item in dependencies)
            or len(dependencies) != len(set(dependencies))
        ):
            raise ValueError("Dependencies must be unique string IDs")
        if (
            type(step.get("retries", 0)) is not int
            or not 0 <= step.get("retries", 0) <= 10
        ):
            raise ValueError("Invalid retries")
        timeout = step.get("timeout_seconds", 60)
        if type(timeout) not in {int, float} or not 0 < timeout <= 300:
            raise ValueError("Timeout must be finite, positive and at most 300 seconds")
        if type(step.get("approval_required", False)) is not bool or not isinstance(
            step.get("params", {}), dict
        ):
            raise ValueError("Invalid approval_required or params")
        if "data_bindings" in step and not isinstance(step["data_bindings"], dict):
            raise ValueError("Invalid data_bindings")
    for key in ("inputs_schema", "outputs_schema", "audit_metadata"):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f"Invalid {key}")
    definition = definition_from_dict(data)
    # Use the same validator/compiler as CLI and execution, without initializing a Store.
    from nous_runtime.workflow.compiler import WorkflowCompiler

    WorkflowCompiler().compile(definition)
    return definition


def unsupported_steps(definition) -> list[str]:
    return [
        step.step_id
        for step in definition.steps
        if step.step_type not in _BUILTINS
        or step.action
        or step.condition
        or step.compensation
    ]


def _read(authorization_context):
    from nous_runtime.governance import ActionProposal, get_gate
    from nous_runtime.governance.contracts import AuthorizationContext

    if not isinstance(authorization_context, AuthorizationContext):
        raise PermissionError("Authenticated workspace identity required")
    decision = get_gate().evaluate(
        ActionProposal(
            action_type="workflow.inspect",
            capability_id="project.read_file",
            target_workspace=str(workspace()),
            affected_resources=(str(workspace() / ".nous" / "workflows.db"),),
            required_permissions=("workspace.read",),
            side_effect_class="read_only",
            reversibility="reversible",
            retry_behavior="idempotent",
            locality=authorization_context.session_locality,
        ),
        authorization_context,
    )
    if decision.action_mode != "EXECUTE" or decision.allowed is not True:
        raise PermissionError("Workflow inspection was not admitted")


def _view(run):
    from nous_runtime.workflow.store import WorkflowStore

    result = WorkflowStore._run_dict(run)
    # Internal approval/checkpoint bookkeeping is never an input to the client.
    result["inputs"] = {
        key: value for key, value in run.inputs.items() if not key.startswith("_")
    }
    result["execution_scope"] = "runtime-service"
    result["verification"] = "NOT_PHYSICAL_VERIFICATION"
    return result


def handle_workflow_catalog(*, authorization_context=None):
    _read(authorization_context)
    runtime = WorkflowRuntime(str(workspace()))
    return ok_response(
        {
            "definitions": runtime.store.list_definition_summaries(),
            "runs": runtime.store.list_run_summaries(),
            "limit": 100,
            "data_bindings_versions": [1],
            "step_types": [
                {"type": item.value, "available": item in _BUILTINS}
                for item in StepType
            ],
            "execution_scope": "runtime-service",
        }
    )


def handle_workflow_definition(
    workflow_id: str, version: str, *, authorization_context=None
):
    _read(authorization_context)
    definition = WorkflowRuntime(str(workspace())).store.get_definition(
        workflow_id, version
    )
    if definition is None:
        return err_response("NOUS_NOT_FOUND", "Workflow definition not found")
    data = definition_to_dict(definition)
    if len(json.dumps(data).encode("utf-8")) > 96 * 1024:
        return err_response(
            "NOUS_NOT_AVAILABLE",
            "Definition exceeds the bounded Studio editor profile; use the original CLI host",
        )
    return ok_response({"definition": data})


def handle_workflow_validate(body: dict, *, authorization_context=None):
    _read(authorization_context)
    try:
        definition = validate_definition(body.get("definition"))
        unsupported = unsupported_steps(definition)
        return ok_response(
            {
                "valid": True,
                "data_bindings_versions": [1],
                "runnable": not unsupported,
                "unsupported_steps": unsupported,
                "definition": definition_to_dict(definition),
            }
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_workflow_register(body: dict, *, authorization_context=None):
    _read(authorization_context)
    try:
        if set(body) != {"definition"}:
            raise ValueError("Only definition may be registered")
        definition = validate_definition(body.get("definition"))
        WorkflowRuntime(str(workspace())).register(definition)
        return ok_response(
            {"registered": True, "definition": definition_to_dict(definition)}
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_workflow_run(body: dict, *, authorization_context=None):
    _read(authorization_context)
    try:
        if set(body) - {
            "workflow_id",
            "version",
            "inputs",
            "idempotency_key",
            "definition",
        }:
            raise ValueError("Unknown run argument")
        runtime = WorkflowRuntime(str(workspace()))
        definition = runtime.store.get_definition(
            str(body.get("workflow_id") or ""), str(body.get("version") or "1.0.0")
        )
        if definition is None:
            raise ValueError("Workflow definition not found")
        validate_definition(definition_to_dict(definition))
        if "definition" in body:
            from nous_runtime.workflow.store import binding_digest

            reviewed = validate_definition(body["definition"])
            if binding_digest(definition_to_dict(reviewed)) != binding_digest(
                definition_to_dict(definition)
            ):
                raise ValueError(
                    "Draft differs from registered version; register a new version before running"
                )
        if unsupported_steps(definition):
            return err_response(
                "NOUS_NOT_AVAILABLE",
                "Workflow requires host handlers not bound to this endpoint",
            )
        inputs = body.get("inputs", {})
        if (
            not isinstance(inputs, dict)
            or len(json.dumps(inputs, allow_nan=False).encode()) > 32 * 1024
        ):
            raise ValueError("Inputs must be an object of at most 32 KiB")
        _bounded_json(inputs)
        key = body.get("idempotency_key", "")
        if not isinstance(key, str) or (key and not _IDENTIFIER.fullmatch(key)):
            raise ValueError("Invalid idempotency_key")
        return ok_response(
            _view(
                runtime.start(
                    definition.workflow_id,
                    definition.version,
                    inputs,
                    idempotency_key=key,
                )
            )
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


def handle_workflow_run_detail(run_id: str, *, authorization_context=None):
    _read(authorization_context)
    runtime = WorkflowRuntime(str(workspace()))
    run = runtime.store.get_run(run_id)
    if run is None:
        return err_response("NOUS_NOT_FOUND", "Workflow run not found")
    definition = runtime.store.get_definition(run.workflow_id, run.workflow_version)
    checkpoints = runtime.store.checkpoints(run_id)
    binding_views = {}

    def digest(value):
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
            else None
        )

    for step in definition.steps if definition else ():
        if not isinstance(step.data_bindings, dict):
            continue
        checkpoint = checkpoints.get(step.step_id) or {}
        recorded = checkpoint.get("data_binding")
        if not isinstance(recorded, dict):
            continue
        sources = recorded.get("sources")
        sources = sources if isinstance(sources, dict) else {}
        binding_views[step.step_id] = {
            "data_binding": {
                "schema_version": 1
                if type(recorded.get("schema_version")) is int
                and recorded["schema_version"] == 1
                else None,
                "params_digest": digest(recorded.get("params_digest")),
                "sources": {
                    target: {
                        **{
                            key: value
                            for key, value in reference.items()
                            if key in {"source", "step_id", "pointer"}
                        },
                        "source_digest": digest(sources[target].get("source_digest"))
                        if {
                            key: value
                            for key, value in sources[target].items()
                            if key != "source_digest"
                        }
                        == reference
                        else None,
                        "reference_matches": {
                            key: value
                            for key, value in sources[target].items()
                            if key != "source_digest"
                        }
                        == reference,
                    }
                    for target, reference in step.data_bindings.get(
                        "inputs", {}
                    ).items()
                    if isinstance(reference, dict)
                    and isinstance(sources.get(target), dict)
                },
            },
            "output_digest": digest(checkpoint.get("output_digest")),
            "status": checkpoint.get("status")
            if isinstance(checkpoint.get("status"), str)
            and checkpoint["status"]
            in {
                "started",
                "waiting_approval",
                "completed",
                "skipped",
                "failed",
                "unknown",
                "cancelled",
            }
            else "unknown",
            "data_validation_failed": checkpoint.get("data_validation_failed") is True,
        }
    return ok_response(
        {
            "run": _view(run),
            "step_bindings": binding_views,
            "events": [
                event.to_dict() for event in runtime.events.load_events(run_id)[-200:]
            ],
        }
    )


def handle_workflow_run_action(run_id: str, body: dict, *, authorization_context=None):
    _read(authorization_context)
    try:
        approval = body.get("action") == "approve"
        expected = (
            {"action", "step_id", "definition_digest"} if approval else {"action"}
        )
        if set(body) != expected or body["action"] not in {
            "cancel",
            "resume",
            "approve",
        }:
            raise ValueError("Invalid original-run action")
        runtime = WorkflowRuntime(str(workspace()))
        original = runtime.store.get_run(run_id)
        if original is None:
            return err_response("NOUS_NOT_FOUND", "Workflow run not found")
        definition = runtime.store.get_definition(
            original.workflow_id, original.workflow_version
        )
        if body["action"] == "cancel":
            # Cancellation is an original-run admission flag, not handler replay.
            # The Store preserves UNKNOWN if a started effect needs reconciliation.
            return ok_response(_view(runtime.cancel(run_id)))
        if definition is None or unsupported_steps(definition):
            return err_response(
                "NOUS_NOT_AVAILABLE", "Original host handlers are required for recovery"
            )
        if approval:
            from nous_runtime.control_plane.human_sessions import (
                human_permission,
                is_human_session_context,
            )
            from nous_runtime.governance import get_gate

            step_id = body["step_id"]
            if (
                not isinstance(step_id, str)
                or body["definition_digest"] != original.definition_digest
            ):
                raise ValueError("Original definition binding differs")
            step = next(
                (item for item in definition.steps if item.step_id == step_id), None
            )
            if step is None or not (
                step.approval_required or step.step_type is StepType.APPROVAL
            ):
                raise ValueError("Original step does not request human approval")
            resource = f"workflow:{run_id}:{step_id}"
            store = get_gate().store
            # The existing authenticated human context and permission system own
            # this decision. Body claims and an ordinary API lease cannot pass.
            with store.operation_transaction() as db:
                if not is_human_session_context(
                    authorization_context, store, db=db
                ) or not human_permission(
                    authorization_context, "governance.approve", resource
                ):
                    raise PermissionError(
                        "A current human approver with original-step permission is required"
                    )
                store.append_operation_audit(
                    db,
                    "workflow.approval.accepted",
                    {
                        "run_id": run_id,
                        "step_id": step_id,
                        "definition_digest": original.definition_digest,
                        "actor_id": authorization_context.subject_id,
                        "human_session_id": authorization_context.session_id,
                        "resource_id": resource,
                    },
                )
                run = runtime.resume(run_id, approved_steps=(step_id,))
            return ok_response(_view(run))
        # No approved_steps input on ordinary resume. It cannot turn a waiting
        # step into an approval or replay an uncertain effect.
        run = (
            runtime.cancel(run_id)
            if body["action"] == "cancel"
            else runtime.resume(run_id)
        )
        return ok_response(_view(run))
    except (KeyError, TypeError, ValueError) as exc:
        return err_response("NOUS_INVALID_REQUEST", str(exc))


WORKFLOW_ROUTES = {
    ("GET", "/api/v1/workflow"): handle_workflow_catalog,
    (
        "GET",
        "/api/v1/workflow/definitions/{workflow_id}/{version}",
    ): handle_workflow_definition,
    ("POST", "/api/v1/workflow/validate"): handle_workflow_validate,
    ("POST", "/api/v1/workflow/register"): handle_workflow_register,
    ("POST", "/api/v1/workflow/run"): handle_workflow_run,
    ("GET", "/api/v1/workflow/runs/{run_id}"): handle_workflow_run_detail,
    ("POST", "/api/v1/workflow/runs/{run_id}/action"): handle_workflow_run_action,
}
WORKFLOW_GOVERNANCE = {
    ("POST", "/api/v1/workflow/register"): (
        "workflow.register",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/workflow/runs/{run_id}/action"): (
        "workflow.run",
        "local_write",
        "partially_reversible",
    ),
}
