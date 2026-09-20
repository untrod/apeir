"""Durable Workflow execution over the existing TaskGraph."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable

from nous_runtime.events.models import RunEvent
from nous_runtime.events.stream import EventStream
from nous_runtime.workflow.compiler import WorkflowCompiler
from nous_runtime.workflow.models import StepType, WorkflowDefinition, WorkflowRun, WorkflowState, WorkflowStep
from nous_runtime.workflow.store import WorkflowStore

StepHandler = Callable[[WorkflowStep, dict[str, Any]], dict[str, Any]]


class WorkflowRuntime:
    def __init__(
        self,
        root: str = ".",
        *,
        handlers: dict[str, StepHandler] | None = None,
        max_parallel: int = 4,
    ):
        self.store = WorkflowStore(root)
        self.events = EventStream(root)
        self.compiler = WorkflowCompiler()
        self.handlers = dict(handlers or {})
        self.max_parallel = max(1, max_parallel)

    def register(self, definition: WorkflowDefinition) -> None:
        self.compiler.validate(definition)
        self.store.put_definition(definition)

    def start(self, workflow_id: str, version: str, inputs: dict[str, Any] | None = None, *, idempotency_key: str = "") -> WorkflowRun:
        definition = self.store.get_definition(workflow_id, version)
        if definition is None:
            raise KeyError(f"workflow not found: {workflow_id}@{version}")
        run = self.store.create_run(WorkflowRun(workflow_id, version, dict(inputs or {}), idempotency_key=idempotency_key))
        if run.state != WorkflowState.PENDING:
            return run
        return self._execute(definition, run)

    def resume(self, run_id: str, *, approved_steps: tuple[str, ...] = ()) -> WorkflowRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.state not in {WorkflowState.WAITING_APPROVAL, WorkflowState.RUNNING, WorkflowState.FAILED}:
            return run
        definition = self.store.get_definition(run.workflow_id, run.workflow_version)
        if definition is None:
            raise KeyError(f"workflow not found: {run.workflow_id}@{run.workflow_version}")
        approved = set(run.inputs.get("_approved_steps") or ())
        approved.update(approved_steps)
        run.inputs["_approved_steps"] = sorted(approved)
        run.state = WorkflowState.RUNNING
        run.error = ""
        self.store.save_run(run)
        return self._execute(definition, run)

    def cancel(self, run_id: str) -> WorkflowRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        terminal_states = {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.COMPENSATION_FAILED,
            WorkflowState.CANCELLED,
        }
        if run.state not in terminal_states:
            run.cancellation_requested = True
            run.state = WorkflowState.CANCELLED
            self.store.save_run(run)
            self._emit(run, "workflow.cancelled", {})
        return run

    def _execute(self, definition: WorkflowDefinition, run: WorkflowRun) -> WorkflowRun:
        graph = self.compiler.compile(definition)
        steps = {step.step_id: step for step in definition.steps}
        checkpoints = self.store.checkpoints(run.run_id)
        for step_id, checkpoint in checkpoints.items():
            if checkpoint.get("status") in {"completed", "skipped"}:
                run.step_states[step_id] = str(checkpoint["status"])
                if "output" in checkpoint:
                    run.outputs[step_id] = checkpoint["output"]
        run.state = WorkflowState.RUNNING
        self.store.save_run(run)
        self._emit(run, "workflow.started", {})
        completed_order: list[str] = [step.step_id for step in definition.steps if run.step_states.get(step.step_id) == "completed"]
        for wave in graph.level_order():
            pending = [steps[node.task_id] for node in wave if run.step_states.get(node.task_id) not in {"completed", "skipped"}]
            if not pending:
                continue
            if run.cancellation_requested:
                return run
            with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(pending))) as executor:
                futures = {executor.submit(self._execute_step, run, step): step for step in pending}
                for future, step in futures.items():
                    try:
                        status, output, error = future.result()
                    except Exception as exc:
                        status, output, error = "failed", {}, str(exc)
                    run.step_states[step.step_id] = status
                    if output:
                        run.outputs[step.step_id] = output
                    self.store.checkpoint(run.run_id, step.step_id, {"status": status, "output": output, "error": error})
                    self._emit(run, f"workflow.step.{status}", {"step_id": step.step_id, "error": error})
                    if status == "waiting_approval":
                        run.state = WorkflowState.WAITING_APPROVAL
                        run.error = error
                        self.store.save_run(run)
                        return self.store.get_run(run.run_id) or run
                    if status == "failed":
                        run.error = error
                        run.state = self._compensate(run, steps, completed_order)
                        self.store.save_run(run)
                        self._emit(run, f"workflow.{run.state.value}", {"step_id": step.step_id, "error": error})
                        return self.store.get_run(run.run_id) or run
                    if status == "completed":
                        completed_order.append(step.step_id)
            self.store.save_run(run)
        run.state = WorkflowState.COMPLETED
        run.error = ""
        self.store.save_run(run)
        self._emit(run, "workflow.completed", {"outputs": run.outputs})
        return self.store.get_run(run.run_id) or run

    def _execute_step(self, run: WorkflowRun, step: WorkflowStep) -> tuple[str, dict[str, Any], str]:
        if step.approval_required or step.step_type == StepType.APPROVAL:
            if step.step_id not in set(run.inputs.get("_approved_steps") or ()):
                return "waiting_approval", {}, "human approval required"
        if step.step_type == StepType.APPROVAL:
            return "completed", {"approved": True}, ""
        if step.step_type == StepType.CONDITION:
            key = str(step.params.get("input") or "")
            if key and run.inputs.get(key) != step.params.get("equals"):
                return "skipped", {}, ""
        handler = self.handlers.get(step.action) or self.handlers.get(step.step_type.value) or self._builtin_handler
        context = {"run_id": run.run_id, "inputs": dict(run.inputs), "outputs": dict(run.outputs)}
        attempts = 0
        while attempts <= step.retries:
            attempts += 1
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, step, context)
                try:
                    output = future.result(timeout=step.timeout_seconds)
                    return "completed", dict(output or {}), ""
                except FutureTimeout:
                    error = f"step timed out after {step.timeout_seconds} seconds"
                except Exception as exc:
                    error = str(exc)
            if attempts > step.retries:
                return "failed", {}, error
        return "failed", {}, "step failed"

    def _compensate(self, run: WorkflowRun, steps: dict[str, WorkflowStep], completed_order: list[str]) -> WorkflowState:
        failed = False
        for step_id in reversed(completed_order):
            step = steps[step_id]
            if not step.compensation:
                continue
            handler = self.handlers.get(step.compensation)
            if handler is None:
                failed = True
                continue
            try:
                handler(step, {"run_id": run.run_id, "inputs": run.inputs, "outputs": run.outputs, "compensation": True})
                self.store.checkpoint(run.run_id, f"compensate:{step_id}", {"status": "completed"})
            except Exception as exc:
                failed = True
                self.store.checkpoint(run.run_id, f"compensate:{step_id}", {"status": "failed", "error": str(exc)})
        return WorkflowState.COMPENSATION_FAILED if failed else WorkflowState.FAILED

    @staticmethod
    def _builtin_handler(step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        if step.step_type == StepType.TRANSFORM:
            return {"value": step.params.get("value"), "inputs": context["inputs"]}
        if step.step_type == StepType.WAIT:
            return {"waited": True}
        raise RuntimeError(f"no workflow handler registered for {step.step_type.value}:{step.action}")

    def _emit(self, run: WorkflowRun, event_type: str, payload: dict[str, Any]) -> None:
        self.events.emit(RunEvent(run_id=run.run_id, event_type=event_type, payload=payload))