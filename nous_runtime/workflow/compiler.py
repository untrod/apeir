"""Workflow-to-TaskGraph compiler."""

from __future__ import annotations

from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.plan import Task
from nous_runtime.workflow.models import StepType, WorkflowDefinition


class WorkflowValidationError(ValueError):
    pass


class WorkflowCompiler:
    def compile(self, definition: WorkflowDefinition) -> TaskGraph:
        self.validate(definition)
        tasks = [Task(description=f"Workflow step {step.step_id}", task_id=step.step_id, capability_id=self._capability(step.step_type, step.action), params={"workflow_step": step.step_id, "action": step.action, **step.params}, depends_on=list(step.depends_on), max_retries=step.retries, timeout_seconds=max(1, int(step.timeout_seconds))) for step in definition.steps]
        graph = TaskGraph()
        graph.build(tasks)
        return graph

    def validate(self, definition: WorkflowDefinition) -> None:
        if not definition.workflow_id or not definition.version:
            raise WorkflowValidationError("workflow_id and version are required")
        ids = [step.step_id for step in definition.steps]
        if len(ids) != len(set(ids)) or any(not item for item in ids):
            raise WorkflowValidationError("workflow step ids must be unique and non-empty")
        known = set(ids)
        for step in definition.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise WorkflowValidationError(f"unknown dependencies for {step.step_id}: {sorted(missing)}")
            if step.step_id in step.depends_on:
                raise WorkflowValidationError(f"self dependency: {step.step_id}")
            if step.retries < 0 or step.retries > 10:
                raise WorkflowValidationError("workflow retries must be between 0 and 10")
            if step.timeout_seconds <= 0:
                raise WorkflowValidationError("workflow timeout must be positive")
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
    def _capability(step_type: StepType, action: str) -> str:
        defaults = {StepType.AGENT: "agent.execute", StepType.CONNECTOR: "connector.execute", StepType.COMMAND: "device.pc.exec", StepType.APPROVAL: "governance.approval", StepType.CONDITION: "workflow.condition", StepType.WAIT: "workflow.wait", StepType.TRANSFORM: "workflow.transform"}
        return action if step_type == StepType.CAPABILITY and action else defaults[step_type]