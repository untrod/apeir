"""Workflow-to-TaskGraph compiler."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from typing import Any

from jsonschema import validators
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.plan import Task
from nous_runtime.workflow.models import StepType, WorkflowDefinition, WorkflowStep


class WorkflowValidationError(ValueError):
    pass


class WorkflowCompiler:
    def compile(self, definition: WorkflowDefinition) -> TaskGraph:
        self.validate(definition)
        tasks = [
            Task(
                description=f"Workflow step {step.step_id}",
                task_id=step.step_id,
                capability_id=self._capability(step.step_type, step.action),
                params={
                    "workflow_step": step.step_id,
                    "action": step.action,
                    **step.params,
                },
                depends_on=list(step.depends_on),
                max_retries=step.retries,
                timeout_seconds=max(1, int(step.timeout_seconds)),
            )
            for step in definition.steps
        ]
        graph = TaskGraph()
        graph.build(tasks)
        return graph

    def validate(self, definition: WorkflowDefinition) -> None:
        if not definition.workflow_id or not definition.version:
            raise WorkflowValidationError("workflow_id and version are required")
        self._schema_validator(definition.inputs_schema, "inputs")
        self._schema_validator(definition.outputs_schema, "outputs")
        ids = [step.step_id for step in definition.steps]
        if len(ids) != len(set(ids)) or any(not item for item in ids):
            raise WorkflowValidationError(
                "workflow step ids must be unique and non-empty"
            )
        known = set(ids)
        for step in definition.steps:
            if step.step_type == StepType.CAPABILITY and not step.action:
                raise WorkflowValidationError("capability steps require an action")
            missing = set(step.depends_on) - known
            if missing:
                raise WorkflowValidationError(
                    f"unknown dependencies for {step.step_id}: {sorted(missing)}"
                )
            if step.step_id in step.depends_on:
                raise WorkflowValidationError(f"self dependency: {step.step_id}")
            self.validate_step_bindings(step)
            if type(step.retries) is not int or not 0 <= step.retries <= 10:
                raise WorkflowValidationError(
                    "workflow retries must be between 0 and 10"
                )
            if (
                type(step.timeout_seconds) not in {int, float}
                or not math.isfinite(step.timeout_seconds)
                or step.timeout_seconds <= 0
            ):
                raise WorkflowValidationError(
                    "workflow timeout must be finite and positive"
                )
        visiting: set[str] = set()
        visited: set[str] = set()
        edges = {step.step_id: step.depends_on for step in definition.steps}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise WorkflowValidationError("workflow contains a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in edges[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)

    @staticmethod
    def _pointer_parts(pointer: Any) -> list[str]:
        if (
            not isinstance(pointer, str)
            or len(pointer) > 1024
            or pointer
            and not pointer.startswith("/")
            or re.search(r"~(?![01])", pointer)
        ):
            raise WorkflowValidationError("Invalid Workflow data pointer")
        parts = (
            [
                part.replace("~1", "/").replace("~0", "~")
                for part in pointer[1:].split("/")
            ]
            if pointer
            else []
        )
        if len(parts) > 32 or any(part.startswith("_") for part in parts):
            raise WorkflowValidationError("Reserved or excessive Workflow data path")
        return parts

    def validate_step_bindings(self, step: WorkflowStep) -> None:
        contract = step.data_bindings
        if contract is None:
            return
        if (
            not isinstance(contract, dict)
            or set(contract)
            - {"schema_version", "inputs", "inputs_schema", "outputs_schema"}
            or type(contract.get("schema_version")) is not int
            or contract["schema_version"] != 1
        ):
            raise WorkflowValidationError("Unsupported Workflow data binding contract")
        bindings = contract.get("inputs", {})
        if not isinstance(bindings, dict) or len(bindings) > 64:
            raise WorkflowValidationError(
                "Workflow data bindings require at most 64 targets"
            )
        for target, source in bindings.items():
            if (
                not isinstance(target, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", target) is None
                or target in step.params
                or not isinstance(source, dict)
                or not isinstance(source.get("source"), str)
                or source.get("source") not in {"inputs", "step"}
            ):
                raise WorkflowValidationError(
                    "Invalid or conflicting Workflow data target"
                )
            allowed = {"source", "pointer"}
            if source["source"] == "step":
                allowed.add("step_id")
                if (
                    not isinstance(source.get("step_id"), str)
                    or source["step_id"] not in step.depends_on
                ):
                    raise WorkflowValidationError(
                        "Workflow data source must be a declared dependency"
                    )
            if set(source) - allowed:
                raise WorkflowValidationError("Unknown Workflow data source field")
            self._pointer_parts(source.get("pointer", ""))
        for key in ("inputs_schema", "outputs_schema"):
            self._schema_validator(contract.get(key, {}), f"step {key}")

    def validate_step_data(
        self, step: WorkflowStep, value: Any, *, outputs: bool = False
    ) -> None:
        if step.data_bindings is None:
            return
        label = "step outputs" if outputs else "step inputs"
        schema = step.data_bindings.get(
            "outputs_schema" if outputs else "inputs_schema", {}
        )
        validator = self._schema_validator(schema, label)
        try:
            encoded = json.dumps(value, allow_nan=False).encode("utf-8")
            if len(encoded) > 96 * 1024:
                raise WorkflowValidationError(f"Workflow {label} exceed 96 KiB")
            if validator is not None:
                validator.validate(value)
        except ValidationError as exc:
            raise WorkflowValidationError(
                f"Workflow {label} violate schema ({exc.validator})"
            ) from None
        except (Unresolvable, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, WorkflowValidationError):
                raise
            raise WorkflowValidationError(
                f"Workflow {label} could not be validated"
            ) from None

    def resolve_step_bindings(
        self, step: WorkflowStep, inputs: dict[str, Any], outputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve data only; no expressions, acquisition, permissions or dispatch."""
        self.validate_step_bindings(step)
        params = deepcopy(step.params)
        if step.data_bindings is None:
            return params
        for target, reference in step.data_bindings.get("inputs", {}).items():
            value = (
                inputs
                if reference["source"] == "inputs"
                else outputs[reference["step_id"]]
            )
            for part in self._pointer_parts(reference.get("pointer", "")):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                elif (
                    isinstance(value, list)
                    and re.fullmatch(r"0|[1-9][0-9]*", part)
                    and len(part) < 10
                    and int(part) < len(value)
                ):
                    value = value[int(part)]
                else:
                    raise WorkflowValidationError(
                        "Workflow data source path is unavailable"
                    )
            params[target] = deepcopy(value)
        self.validate_step_data(step, params)
        return params

    @staticmethod
    def _schema_validator(schema: dict[str, Any], label: str):
        """Use installed JSON Schema dialects and local references only."""
        if not isinstance(schema, dict):
            raise WorkflowValidationError(f"Workflow {label} schema must be an object")
        if not schema:
            return None
        dialects = {}
        for validator in (
            validators.Draft4Validator,
            validators.Draft6Validator,
            validators.Draft7Validator,
            validators.Draft201909Validator,
            validators.Draft202012Validator,
        ):
            uri = validator.META_SCHEMA.get("$id") or validator.META_SCHEMA["id"]
            dialects[uri.rstrip("#")] = validator
        try:
            json.dumps(schema, allow_nan=False)
            pending = [(schema, 0)]
            while pending:
                item, depth = pending.pop()
                if depth > 32:
                    raise WorkflowValidationError(
                        f"Workflow {label} schema is too deeply nested"
                    )
                if isinstance(item, dict):
                    declared = item.get("$schema")
                    if declared is not None and (
                        not isinstance(declared, str)
                        or declared.rstrip("#") not in dialects
                    ):
                        raise WorkflowValidationError(
                            f"Unsupported Workflow {label} schema dialect"
                        )
                    for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                        reference = item.get(keyword)
                        if isinstance(reference, str) and not reference.startswith("#"):
                            raise WorkflowValidationError(
                                f"External Workflow {label} schema references are not allowed"
                            )
                    pending.extend((value, depth + 1) for value in item.values())
                elif isinstance(item, list):
                    pending.extend((value, depth + 1) for value in item)
            validator = dialects.get(
                schema.get("$schema", "").rstrip("#"), validators.Draft202012Validator
            )
            validator.check_schema(schema)
            # No retriever: even an unresolved local reference cannot fall back
            # to network/file acquisition during execution.
            return validator(schema, registry=Registry())
        except (SchemaError, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, WorkflowValidationError):
                raise
            raise WorkflowValidationError(f"Invalid Workflow {label} schema") from None

    def validate_data(
        self, definition: WorkflowDefinition, data: Any, *, outputs: bool = False
    ) -> None:
        label = "outputs" if outputs else "inputs"
        schema = definition.outputs_schema if outputs else definition.inputs_schema
        validator = self._schema_validator(schema, label)
        if not isinstance(data, dict):
            raise WorkflowValidationError(f"Workflow {label} must be an object")
        try:
            json.dumps(data, allow_nan=False)
            if validator is not None:
                validator.validate(data)
        except ValidationError as exc:
            # Instance/schema text can contain private model or project data.
            # Report only the violated keyword, never the offending content.
            raise WorkflowValidationError(
                f"Workflow {label} violate schema ({exc.validator})"
            ) from None
        except (Unresolvable, TypeError, ValueError, RecursionError):
            raise WorkflowValidationError(
                f"Workflow {label} could not be validated"
            ) from None

    @staticmethod
    def _capability(step_type: StepType, action: str) -> str:
        defaults = {
            StepType.AGENT: "agent.execute",
            StepType.CONNECTOR: "connector.execute",
            StepType.COMMAND: "device.pc.exec",
            StepType.APPROVAL: "governance.approval",
            StepType.CONDITION: "workflow.condition",
            StepType.WAIT: "workflow.wait",
            StepType.TRANSFORM: "workflow.transform",
        }
        return (
            action
            if step_type == StepType.CAPABILITY and action
            else defaults[step_type]
        )
