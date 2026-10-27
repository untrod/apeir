"""Durable Workflow execution over the existing TaskGraph."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
import math
from typing import Any, Callable

from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    RetryStrategy,
)
from nous_runtime.events.bus import RuntimeEventBus
from nous_runtime.events.models import RunEvent
from nous_runtime.events.stream import EventStream
from nous_runtime.governance.operation_contracts import GovernanceApprovalRequired
from nous_runtime.workflow.compiler import WorkflowCompiler, WorkflowValidationError
from nous_runtime.workflow.models import (
    StepType,
    WorkflowDefinition,
    WorkflowHandlerPolicy,
    WorkflowRun,
    WorkflowState,
    WorkflowStep,
)
from nous_runtime.workflow.store import (
    WorkflowBindingError,
    WorkflowConflictError,
    WorkflowStore,
    binding_digest,
)

StepHandler = Callable[[WorkflowStep, dict[str, Any]], dict[str, Any]]
_SUPPORTED_EFFECTS = {"none", "read_only", "local_write", "external_write"}
_PURE_EFFECTS = {"none", "read_only"}


class WorkflowRuntime:
    def __init__(
        self,
        root: str = ".",
        *,
        handlers: dict[str, StepHandler] | None = None,
        max_parallel: int = 4,
        event_bus: RuntimeEventBus | None = None,
        event_metadata: dict[str, Any] | None = None,
        handler_policies: dict[str, WorkflowHandlerPolicy] | None = None,
    ):
        self.store = WorkflowStore(root)
        self.events = EventStream(root)
        self.compiler = WorkflowCompiler()
        self.handlers = dict(handlers or {})
        self.handler_policies = deepcopy(dict(handler_policies or {}))
        for key, handler in self.handlers.items():
            if key not in self.handler_policies:
                policy = getattr(handler, "workflow_handler_policy", None)
                if policy is not None:
                    self.handler_policies[key] = deepcopy(policy)
        if any(
            not isinstance(policy, WorkflowHandlerPolicy)
            or type(policy.reconcile_started) is not bool
            or policy.contract is not None
            and not isinstance(policy.contract, CapabilityContract)
            for policy in self.handler_policies.values()
        ):
            raise TypeError("Workflow handler policies require trusted host contracts")
        self.max_parallel = max(1, max_parallel)
        self.event_bus = event_bus
        self.event_metadata = dict(event_metadata or {})

    def register(self, definition: WorkflowDefinition) -> None:
        self._validate_definition(definition)
        self.store.put_definition(definition)

    def _validate_definition(self, definition: WorkflowDefinition) -> None:
        self.compiler.validate(definition)
        if any(not math.isfinite(step.timeout_seconds) for step in definition.steps):
            raise WorkflowValidationError(
                "workflow timeout must be finite and positive"
            )

    def start(
        self,
        workflow_id: str,
        version: str,
        inputs: dict[str, Any] | None = None,
        *,
        idempotency_key: str = "",
    ) -> WorkflowRun:
        definition = self.store.get_definition(workflow_id, version)
        if definition is None:
            raise KeyError(f"workflow not found: {workflow_id}@{version}")
        self._validate_definition(definition)
        self.compiler.validate_data(definition, {} if inputs is None else inputs)
        run = self.store.create_run(
            WorkflowRun(
                workflow_id,
                version,
                dict(inputs or {}),
                idempotency_key=idempotency_key,
            )
        )
        with self.store.execution_lock(run.run_id):
            current = self._require(run.run_id)
            if (
                current.state is not WorkflowState.PENDING
                or current.cancellation_requested
            ):
                return current
            return self._execute(definition, current)

    def resume(
        self, run_id: str, *, approved_steps: tuple[str, ...] = ()
    ) -> WorkflowRun:
        with self.store.execution_lock(run_id):
            run = self._require(run_id)
            if run.cancellation_requested or run.state not in {
                WorkflowState.WAITING_APPROVAL,
                WorkflowState.RUNNING,
                WorkflowState.FAILED,
                WorkflowState.UNKNOWN,
            }:
                return run
            definition = self.store.get_definition(
                run.workflow_id, run.workflow_version
            )
            if definition is None:
                raise KeyError(
                    f"workflow not found: {run.workflow_id}@{run.workflow_version}"
                )
            self._validate_definition(definition)
            return self._execute(definition, run, approved_steps=approved_steps)

    def cancel(self, run_id: str) -> WorkflowRun:
        run = self._require(run_id)
        if run.state in {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.COMPENSATION_FAILED,
            WorkflowState.CANCELLED,
        }:
            return run
        run = self.store.update_run(run_id, state=WorkflowState.CANCELLED, cancel=True)
        self._emit(run, "workflow.cancelled", {})
        return run

    def _require(self, run_id: str) -> WorkflowRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _execute(
        self,
        definition: WorkflowDefinition,
        run: WorkflowRun,
        *,
        approved_steps: tuple[str, ...] = (),
    ) -> WorkflowRun:
        legacy_started = (
            not run.definition_digest and run.state is WorkflowState.RUNNING
        )
        try:
            run = self.store.bind_run(run.run_id, definition)
        except WorkflowBindingError as exc:
            return self._binding_failure(run, exc)
        try:
            self.compiler.validate_data(
                definition,
                {
                    key: value
                    for key, value in run.inputs.items()
                    if key != "_approved_steps"
                },
            )
        except WorkflowValidationError as exc:
            # A historical run may already have an uncertain effect. Invalid
            # legacy input cannot establish that nothing happened.
            return self._binding_failure(run, WorkflowBindingError(str(exc)))
        checkpoints = self.store.checkpoints(run.run_id)
        for step in definition.steps:
            checkpoint = checkpoints.get(step.step_id) or {}
            if run.step_states.get(step.step_id) in {
                "completed",
                "skipped",
            } and checkpoint.get("status") not in {"completed", "skipped"}:
                return self._binding_failure(
                    run,
                    WorkflowBindingError(
                        "Completed Workflow step has no bound checkpoint"
                    ),
                )
            if checkpoint.get("status") in {"completed", "skipped"}:
                try:
                    self._validate_checkpoint(run, step, checkpoint)
                except WorkflowBindingError as exc:
                    return self._binding_failure(run, exc)
                run.step_states[step.step_id] = str(checkpoint["status"])
                if "output" in checkpoint:
                    run.outputs[step.step_id] = checkpoint["output"]
        try:
            self.store.save_run(run)
        except WorkflowConflictError:
            current = self._require(run.run_id)
            if current.cancellation_requested:
                return current
            raise
        run = self.store.update_run(
            run.run_id,
            state=WorkflowState.RUNNING,
            error="",
            approved_steps=approved_steps,
        )
        if run.cancellation_requested:
            return run
        self._emit(run, "workflow.started", {})
        graph = self.compiler.compile(definition)
        steps = {step.step_id: step for step in definition.steps}
        for wave in graph.level_order():
            run = self._require(run.run_id)
            if run.cancellation_requested:
                return run
            pending = [
                steps[node.task_id]
                for node in wave
                if run.step_states.get(node.task_id) not in {"completed", "skipped"}
            ]
            if not pending:
                continue
            with ThreadPoolExecutor(
                max_workers=min(self.max_parallel, len(pending))
            ) as executor:
                futures = [
                    executor.submit(
                        self._execute_step, run, step, legacy_started=legacy_started
                    )
                    for step in pending
                ]
                results = []
                for future, step in zip(futures, pending):
                    try:
                        status, _output, error = future.result()
                    except Exception as exc:
                        from nous_runtime.core.redaction import redact_sensitive_text

                        status, _output, error = (
                            "unknown",
                            {},
                            redact_sensitive_text(str(exc)),
                        )
                    results.append((step, status, error))
                    self._emit(
                        self._require(run.run_id),
                        f"workflow.step.{status}",
                        {"step_id": step.step_id, "error": error},
                    )
            run = self._require(run.run_id)
            uncertain = next((item for item in results if item[1] == "unknown"), None)
            if uncertain:
                return self._finish(
                    run.run_id,
                    WorkflowState.UNKNOWN,
                    uncertain[2],
                    step_id=uncertain[0].step_id,
                )
            if run.cancellation_requested:
                return run
            failed = next((item for item in results if item[1] == "failed"), None)
            if failed:
                completed = [
                    step.step_id
                    for step in definition.steps
                    if run.step_states.get(step.step_id) == "completed"
                ]
                state = self._compensate(run, steps, completed)
                return self._finish(
                    run.run_id, state, failed[2], step_id=failed[0].step_id
                )
            waiting = next(
                (item for item in results if item[1] == "waiting_approval"), None
            )
            if waiting:
                return self._finish(
                    run.run_id,
                    WorkflowState.WAITING_APPROVAL,
                    waiting[2],
                    step_id=waiting[0].step_id,
                )
        try:
            self.compiler.validate_data(
                definition, self._require(run.run_id).outputs, outputs=True
            )
        except WorkflowValidationError as exc:
            # Steps may already have effects. Keep original checkpoints and do
            # not replay or implicitly compensate for a result-schema failure.
            return self._finish(run.run_id, WorkflowState.FAILED, str(exc))
        return self._finish(
            run.run_id,
            WorkflowState.COMPLETED,
            "",
            outputs=self._require(run.run_id).outputs,
        )

    def _finish(
        self, run_id: str, state: WorkflowState, error: str, **payload
    ) -> WorkflowRun:
        run = self.store.update_run(run_id, state=state, error=error)
        self._emit(run, f"workflow.{run.state.value}", {"error": run.error, **payload})
        return run

    def _binding_failure(
        self, run: WorkflowRun, exc: WorkflowBindingError
    ) -> WorkflowRun:
        # Never repair the bound data or admit a handler after a failed check.
        run = self.store.mark_unknown(run.run_id, str(exc))
        self._emit(run, "workflow.unknown", {"error": run.error})
        return run

    def _step_binding(self, run: WorkflowRun, step: WorkflowStep) -> str:
        return binding_digest(
            {
                "run_id": run.run_id,
                "definition_digest": run.definition_digest,
                "inputs_digest": run.inputs_digest,
                "step_id": step.step_id,
                "params": step.params,
                "dependencies": {key: run.outputs.get(key) for key in step.depends_on},
            }
        )

    def _validate_checkpoint(self, run, step, checkpoint):
        if checkpoint.get("status") in {"completed", "skipped"} and (
            not checkpoint.get("binding_digest") or not checkpoint.get("output_digest")
        ):
            raise WorkflowBindingError(
                "Completed Workflow checkpoint has incomplete evidence bindings"
            )
        self.store._validate_checkpoint(checkpoint, self._step_binding(run, step))
        if checkpoint.get("output_digest") and checkpoint[
            "output_digest"
        ] != binding_digest(checkpoint.get("output") or {}):
            raise WorkflowBindingError("Workflow checkpoint output binding changed")

    def _handler(self, step: WorkflowStep):
        key = step.action if step.action in self.handlers else step.step_type.value
        if key in self.handlers:
            policy = self.handler_policies.get(key, WorkflowHandlerPolicy())
            capability = step.action or self.compiler._capability(
                step.step_type, step.action
            )
            if (
                policy.contract is not None
                and policy.contract.capability_id != capability
            ):
                raise WorkflowBindingError(
                    "Workflow handler contract capability binding changed"
                )
            return self.handlers[key], policy
        if (
            not step.action
            and not step.condition
            and step.step_type
            in {
                StepType.TRANSFORM,
                StepType.WAIT,
                StepType.CONDITION,
                StepType.APPROVAL,
            }
        ):
            contract = CapabilityContract(
                capability_id=f"workflow.{step.step_type.value}",
                side_effect_class="none",
                idempotency=Idempotency.IDEMPOTENT,
                retry_strategy=RetryStrategy.LINEAR,
                max_retries=10,
            )
            return self._builtin_handler, WorkflowHandlerPolicy(contract=contract)
        return None, WorkflowHandlerPolicy()

    @staticmethod
    def _policy_snapshot(policy: WorkflowHandlerPolicy) -> dict[str, Any]:
        contract = policy.contract
        return {
            "reconcile_started": policy.reconcile_started,
            "capability_id": contract.capability_id if contract else "",
            "side_effect_class": contract.side_effect_class if contract else "unknown",
            "idempotency": contract.idempotency.value
            if contract
            else Idempotency.NOT_IDEMPOTENT.value,
            "retry_strategy": contract.retry_strategy.value
            if contract
            else RetryStrategy.NONE.value,
            "max_retries": contract.max_retries if contract else 0,
        }

    @staticmethod
    def _retry_limit(step, policy_snapshot):
        trusted = (
            policy_snapshot["side_effect_class"] in _SUPPORTED_EFFECTS
            and policy_snapshot["idempotency"] == Idempotency.IDEMPOTENT.value
            and policy_snapshot["retry_strategy"] != RetryStrategy.NONE.value
            and type(policy_snapshot["max_retries"]) is int
            and 0 <= policy_snapshot["max_retries"] <= 10
        )
        return min(step.retries, policy_snapshot["max_retries"]) if trusted else 0

    def _execute_step(self, run, step, *, legacy_started=False):
        run = self._require(run.run_id)
        binding = self._step_binding(run, step)
        checkpoint = self.store.checkpoints(run.run_id).get(step.step_id) or {}
        handler, policy = self._handler(step)
        snapshot = self._policy_snapshot(policy)
        attempts = int(checkpoint.get("attempts") or 0)
        retry_limit = self._retry_limit(step, snapshot)
        context = {
            "run_id": run.run_id,
            "inputs": dict(run.inputs),
            "outputs": dict(run.outputs),
        }
        try:
            self._validate_checkpoint(run, step, checkpoint)
        except WorkflowBindingError as exc:
            return "unknown", {}, str(exc)
        legacy_failure = not checkpoint.get("binding_digest") and (
            checkpoint.get("status") == "failed"
            or run.step_states.get(step.step_id) == "failed"
        )
        prior_started = (
            checkpoint.get("status") in {"started", "unknown"}
            or attempts > 0
            or legacy_started
            or legacy_failure
            or run.step_states.get(step.step_id) in {"started", "running", "unknown"}
        )
        if prior_started:
            if (
                checkpoint.get("handler_policy")
                and checkpoint["handler_policy"] != snapshot
            ):
                return (
                    "unknown",
                    checkpoint.get("output") or {},
                    "Workflow handler policy changed after dispatch",
                )
            if not policy.reconcile_started and (
                retry_limit == 0 or attempts >= 1 + retry_limit
            ):
                if (
                    snapshot["side_effect_class"] in _PURE_EFFECTS
                    and checkpoint.get("status") == "failed"
                ):
                    return (
                        "failed",
                        checkpoint.get("output") or {},
                        checkpoint.get("error") or "Workflow retry budget exhausted",
                    )
                return self._record_step(
                    run,
                    step,
                    binding,
                    max(1, attempts),
                    snapshot,
                    "unknown",
                    checkpoint.get("output") or {},
                    "Started Workflow step requires reconciliation; replay blocked",
                )
        if run.cancellation_requested:
            return "cancelled", {}, ""
        if handler is None:
            return self._record_step(
                run,
                step,
                binding,
                attempts,
                snapshot,
                "failed",
                {},
                f"no workflow handler registered for {step.step_type.value}:{step.action}",
            )
        if step.approval_required or step.step_type is StepType.APPROVAL:
            if step.step_id not in set(run.inputs.get("_approved_steps") or ()):
                return self._record_step(
                    run,
                    step,
                    binding,
                    attempts,
                    snapshot,
                    "waiting_approval",
                    {},
                    "human approval required",
                )
        if step.step_type is StepType.CONDITION:
            key = str(step.params.get("input") or "")
            if key and run.inputs.get(key) != step.params.get("equals"):
                return self._record_step(
                    run, step, binding, attempts, snapshot, "skipped", {}, ""
                )
        while True:
            previous_attempts = attempts
            attempts += 1
            started = {
                "status": "started",
                "attempts": attempts,
                "binding_digest": binding,
                "handler_policy": snapshot,
            }
            if not self.store.admit_step(
                run.run_id, step.step_id, started, expected_attempts=previous_attempts
            ):
                return "cancelled", {}, ""
            output = {}
            status = "unknown"
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, step, context)
                try:
                    result = future.result(timeout=step.timeout_seconds)
                    from nous_runtime.core.redaction import redact_sensitive_data

                    output = redact_sensitive_data(dict(result or {}))
                    status, error = "completed", ""
                except GovernanceApprovalRequired as exc:
                    return self._record_step(
                        run,
                        step,
                        binding,
                        previous_attempts,
                        snapshot,
                        "waiting_approval",
                        exc.workflow_output,
                        str(exc),
                    )
                except FutureTimeout:
                    error = f"step timed out after {step.timeout_seconds} seconds"
                    if snapshot["side_effect_class"] in _PURE_EFFECTS:
                        status = "failed"
                except Exception as exc:
                    from nous_runtime.core.redaction import redact_sensitive_text

                    error = redact_sensitive_text(str(exc))
                    output = dict(getattr(exc, "workflow_output", {}) or {})
                    if (
                        snapshot["side_effect_class"] in _PURE_EFFECTS
                        or policy.reconcile_started
                    ):
                        status = "failed"
            if status == "completed":
                return self._record_step(
                    run, step, binding, attempts, snapshot, status, output, error
                )
            self._record_step(
                run, step, binding, attempts, snapshot, status, output, error
            )
            if (
                self._require(run.run_id).cancellation_requested
                or policy.reconcile_started
                or attempts >= 1 + retry_limit
            ):
                return status, output, error

    def _record_step(self, run, step, binding, attempts, policy, status, output, error):
        from nous_runtime.core.redaction import (
            redact_sensitive_data,
            redact_sensitive_text,
        )

        output = redact_sensitive_data(output)
        error = redact_sensitive_text(error)
        self.store.finish_step(
            run.run_id,
            step.step_id,
            {
                "status": status,
                "output": output,
                "output_digest": binding_digest(output),
                "error": error,
                "attempts": attempts,
                "binding_digest": binding,
                "handler_policy": policy,
            },
        )
        return status, output, error

    def _compensate(self, run, steps, completed_order):
        failed = False
        for step_id in reversed(completed_order):
            step = steps[step_id]
            if not step.compensation:
                continue
            handler = self.handlers.get(step.compensation)
            if handler is None:
                failed = True
                continue
            key = f"compensate:{step_id}"
            previous = self.store.checkpoints(run.run_id).get(key) or {}
            if previous.get("status") == "completed":
                continue
            if previous.get("status") in {"started", "unknown"}:
                return WorkflowState.UNKNOWN
            self.store.checkpoint(run.run_id, key, {"status": "started"})
            try:
                handler(
                    step,
                    {
                        "run_id": run.run_id,
                        "inputs": run.inputs,
                        "outputs": run.outputs,
                        "compensation": True,
                    },
                )
                self.store.checkpoint(run.run_id, key, {"status": "completed"})
            except Exception as exc:
                policy = self.handler_policies.get(
                    step.compensation, WorkflowHandlerPolicy()
                )
                status = (
                    "failed"
                    if self._policy_snapshot(policy)["side_effect_class"]
                    in _PURE_EFFECTS
                    else "unknown"
                )
                self.store.checkpoint(
                    run.run_id, key, {"status": status, "error": str(exc)}
                )
                if status == "unknown":
                    return WorkflowState.UNKNOWN
                failed = True
        return WorkflowState.COMPENSATION_FAILED if failed else WorkflowState.FAILED

    @staticmethod
    def _builtin_handler(step, context):
        if step.step_type is StepType.TRANSFORM:
            return {"value": step.params.get("value"), "inputs": context["inputs"]}
        if step.step_type is StepType.WAIT:
            return {"waited": True}
        if step.step_type is StepType.CONDITION:
            return {"matched": True}
        if step.step_type is StepType.APPROVAL:
            return {"approved": True}
        raise RuntimeError(
            f"no workflow handler registered for {step.step_type.value}:{step.action}"
        )

    def _emit(self, run, event_type, payload):
        state = {
            WorkflowState.PENDING: "CREATED",
            WorkflowState.RUNNING: "RUNNING",
            WorkflowState.WAITING_APPROVAL: "WAITING_FOR_APPROVAL",
            WorkflowState.UNKNOWN: "RECOVERY_REQUIRED",
            WorkflowState.COMPLETED: "COMPLETED",
            WorkflowState.FAILED: "FAILED",
            WorkflowState.CANCELLED: "CANCELLED",
            WorkflowState.COMPENSATION_FAILED: "FAILED",
        }[run.state]
        event_payload = {"run_id": run.run_id, "state": state, **payload}
        self.events.emit(
            RunEvent(run_id=run.run_id, event_type=event_type, payload=event_payload)
        )
        if self.event_bus is not None:
            self.event_bus.publish(
                event_type,
                source="workflow.runtime",
                payload=event_payload,
                metadata=self.event_metadata,
            )
