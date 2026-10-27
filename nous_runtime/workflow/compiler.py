"""Workflow-to-TaskGraph compiler."""

from __future__ import annotations

import json
import math
from typing import Any

from jsonschema import validators
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.plan import Task
from nous_runtime.workflow.models import StepType, WorkflowDefinition


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
