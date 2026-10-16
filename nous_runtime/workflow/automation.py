"""Bounded trigger consumption through the existing governed Workflow/Work path.

Only the explicit built-in simulated Reality template is qualified here. A
trigger records intent, never approval, a grant, or proof of a physical effect.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from nous_runtime.governance import GovernanceStore, get_gate
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.core.errors import ArtifactError
from nous_runtime.intelligence.planning.models import PlanStep, TaskPlan
from nous_runtime.intelligence.planning.workflow import PlanWorkflowBridge
from nous_runtime.locking import file_lock
from nous_runtime.node_runtime.distributed_work import (
    DistributedWorkState,
    DistributedWorkStore,
)
from nous_runtime.workflow.models import WorkflowState
from nous_runtime.workflow.runtime import WorkflowRuntime
from nous_runtime.workflow.store import WorkflowBindingError, WorkflowStore

ADAPTER = "simulated-reality"
MAX_DUE = 10


def utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("due_at must be an explicit UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("due_at must be an explicit UTC timestamp")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


class AutomationConsumer:
    """A trigger adapter; canonical owners retain all execution and authority."""

    def __init__(self, root: str | Path, *, gate=None):
        self.root = Path(root).expanduser().resolve()
        self.store = WorkflowStore(self.root)
        self.gate = (
            gate if gate is not None else get_gate(GovernanceStore(self.root / ".nous"))
        )
        if (
            Path(self.gate.store.db_path).resolve()
            != self.root / ".nous" / "governance.db"
        ):
            raise ValueError("Automation and Governance authority differ")
        self.resource_id = (
            "workspace:" + hashlib.sha256(str(self.root).encode()).hexdigest()
        )
        self.controller_state = self.root / ".nous" / "automation-simulation" / "relay"
        self.before_consume = None
        self.management_context = None

    def admit_management(self, context, *, permission="manage", audit=True):
        """Revalidate the existing live human boundary; issue no authority."""
        from nous_runtime.control_plane.human_sessions import (
            human_permission,
            is_human_session_context,
        )
        from nous_runtime.governance import GovernanceRequest
        from nous_runtime.governance.permission import PermissionRequest

        request = GovernanceRequest(
            operation_id="automation-management",
            work_id="automation-management",
            capability_id="workflow.manage",
            resource_id=self.resource_id,
            subject_id="runtime:automation-consumer",
        )
        with self.gate.store.operation_transaction() as db:
            self.gate._require_human(context, request, db=db)
            action = "control.automation." + permission
            if is_human_session_context(
                context, self.gate.store, db=db
            ) and not human_permission(context, action, self.resource_id):
                raise PermissionError("Automation management permission denied")
            if (
                self.gate.permission_engine is not None
                and not self.gate.permission_engine.check(
                    PermissionRequest(
                        context.subject_id,
                        action,
                        self.resource_id,
                        {"subject_type": "user"},
                    )
                ).allowed
            ):
                raise PermissionError("Automation management permission denied")
            if audit and permission == "manage":
                self.gate.store.append_operation_audit(
                    db,
                    "automation.management.admitted",
                    {
                        "actor_id": context.subject_id,
                        "authorization_context_id": context.context_id,
                        "human_session_id": context.session_id,
                        "resource_id": self.resource_id,
                        "execution_authority_issued": False,
                    },
                )
        if permission == "manage":
            self.management_context = context

    def add_simulation(
        self, *, name: str, trigger="manual", due_at="", firmware_version="2.0.0"
    ):
        from nous_runtime.reality.preview import DEFINITION
        from nous_runtime.reality.provider import SimulatedDeviceProvider

        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError(
                "Automation name is required and bounded to 200 characters"
            )
        if trigger not in {"manual", "schedule"}:
            raise ValueError("Only manual and one-shot due triggers are supported")
        if trigger == "schedule":
            due_at = utc_timestamp(due_at)
        elif due_at:
            raise ValueError("Manual automation cannot have due_at")
        SimulatedDeviceProvider.validate_firmware_mutation(
            {"state": {"firmware_version": firmware_version}}
        )
        automation_id = "auto_" + uuid.uuid4().hex
        provider = SimulatedDeviceProvider(DEFINITION)
        device = provider.identify(provider.discover()[0])
        plan_id = "automation-" + automation_id
        plan = TaskPlan(
            task_id=automation_id,
            plan_id=plan_id,
            steps=(
                PlanStep(
                    "inspect",
                    "Observe simulated firmware",
                    "reality.observe",
                    metadata={
                        "device_id": device.device_id,
                        "capability": "device.state.read",
                        "wait_timeout_seconds": 5,
                        "timeout_seconds": 30,
                    },
                ),
                PlanStep(
                    "mutate",
                    "Update and independently verify simulated firmware",
                    "reality.operation",
                    metadata={
                        "device_id": device.device_id,
                        "capability": "device.firmware.update",
                        "mutation": {"state": {"firmware_version": firmware_version}},
                        "expected_effect": {"firmware_version": firmware_version},
                        "wait_timeout_seconds": 5,
                        "timeout_seconds": 30,
                    },
                ),
            ),
            dependencies={"mutate": ("inspect",)},
            metadata={
                "automation_id": automation_id,
                "simulated": True,
                "adapter": ADAPTER,
            },
        )
        definition = PlanWorkflowBridge().compile(plan)
        WorkflowRuntime(str(self.root)).register(definition)
        return self.store.put_automation(
            {
                "id": automation_id,
                "name": name.strip(),
                "adapter": ADAPTER,
                "workflow_id": definition.workflow_id,
                "version": definition.version,
                "definition_digest": self.store.definition_digest(definition),
                "plan_id": plan_id,
                "inputs": {},
                "trigger": trigger,
                "due_at": due_at,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "simulated": True,
                "execution_scope": "runtime-service",
                "kernel_traversed": False,
                "qualification": "SIMULATED_TEMPLATE",
                "schedule": due_at,
                "action": "device.firmware.update",
            },
            before_publish=self.before_consume,
        )

    def list(self):
        return self.store.list_automations()

    def history(self, automation_id: str, *, limit=50):
        history = self.store.automation_history(automation_id, limit=limit)
        for entry in history:
            entry.update(self._projection(automation_id, entry["run"]["run_id"]))
        return {
            "automation_id": automation_id,
            "history": history,
            "total": len(history),
        }

    def trigger(self, automation_id: str, trigger_key: str):
        binding = self._binding(automation_id)
        if not isinstance(trigger_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:+-]{1,128}", trigger_key
        ):
            raise ValueError("An explicit bounded trigger_key is required")
        if binding["trigger"] == "schedule":
            if trigger_key != "due:" + binding["due_at"] or datetime.fromisoformat(
                binding["due_at"]
            ) > datetime.now(timezone.utc):
                raise ValueError(
                    "One-shot scheduled trigger is not due or has a changed key"
                )
        # Creation, relation and immutable inputs commit before the original run
        # can start. Repeating a started trigger only projects persisted state.
        run = self.store.claim_automation_run(
            automation_id, trigger_key, before_publish=self.before_consume
        )
        if run.state is not WorkflowState.PENDING or not binding["enabled"]:
            return self._projection(automation_id, run.run_id)
        return self._consume(automation_id, run.run_id, "start")

    def run_due(self, *, limit=MAX_DUE):
        if type(limit) is not int or not 1 <= limit <= MAX_DUE:
            raise ValueError("run_due limit must be between 1 and 10")
        now = datetime.now(timezone.utc)
        due = sorted(
            (
                binding
                for binding in self.list()
                if binding["enabled"]
                and binding["trigger"] == "schedule"
                and datetime.fromisoformat(binding["due_at"]) <= now
                and not self.store.automation_history(binding["id"], limit=1)
            ),
            key=lambda b: b["due_at"],
        )
        return [self.trigger(b["id"], "due:" + b["due_at"]) for b in due[:limit]]

    def resume(self, automation_id: str, run_id: str):
        self._binding(automation_id)
        run = self.store.automation_run(automation_id, run_id)
        if run.cancellation_requested or run.state in {
            WorkflowState.COMPLETED,
            WorkflowState.CANCELLED,
        }:
            return self._projection(automation_id, run_id)
        return self._consume(automation_id, run_id, "resume")

    def cancel(self, automation_id: str, run_id: str):
        run = self.store.automation_run(automation_id, run_id)
        if run.state is not WorkflowState.COMPLETED:
            if self.management_context is not None:
                for work in self._projection(automation_id, run_id)["works"]:
                    if work["execution_policy"].get(
                        "require_effect_verification", False
                    ):
                        self.gate.interrupt_operation(
                            work["execution_arguments"]["authorization_id"],
                            self.management_context,
                        )
            WorkflowRuntime(str(self.root)).cancel(run_id)
            # A host reconciler can leave FAILED Workflow with UNKNOWN Work.
            # Fence its future resume as well; cancellation is no effect proof.
            self.store.update_run(run_id, state=WorkflowState.CANCELLED, cancel=True)
            if self._projection(automation_id, run_id)["reconciliation_required"]:
                self.store.mark_unknown(
                    run_id,
                    "Cancelled future admission; original effect requires reconciliation",
                )
        return self._projection(automation_id, run_id)

    def reconcile(self, automation_id: str, run_id: str):
        self._binding(automation_id)
        self.store.automation_run(automation_id, run_id)
        return self._consume(automation_id, run_id, "reconcile")

    def _binding(self, automation_id):
        binding = self.store.get_automation(automation_id)
        if (
            binding["adapter"] != ADAPTER
            or binding["qualification"] != "SIMULATED_TEMPLATE"
            or binding["simulated"] is not True
        ):
            raise ValueError("Automation has no qualified structured adapter")
        return binding

    def _consume(self, automation_id, run_id, phase):
        from nous_runtime.reality.preview import create_automation_simulation_components

        async def consume():
            self._projection(automation_id, run_id)
            # Starting this shared relay also reopens other original deliveries.
            # Fence every uncertain effect in the isolated Automation Work store.
            unresolved = [
                work.to_dict()
                for work in DistributedWorkStore(self.controller_state).list()
                if work.execution_policy.require_effect_verification
                and work.state
                in {
                    DistributedWorkState.ASSIGNED,
                    DistributedWorkState.RUNNING,
                    DistributedWorkState.SUCCEEDED,
                    DistributedWorkState.RECOVERING,
                    DistributedWorkState.UNKNOWN,
                    DistributedWorkState.VERIFIED,
                }
            ]
            try:
                components = create_automation_simulation_components(
                    self.root, governance=self.gate
                )
            except (OSError, ValueError, PermissionError):
                if not unresolved:
                    raise
                self.store.mark_unknown(
                    run_id,
                    "Original Node journal or identity is invalid; replay blocked",
                )
                return self._projection(automation_id, run_id)
            try:
                if unresolved and not self._terminal_journals_match(
                    components, unresolved
                ):
                    self.store.mark_unknown(
                        run_id,
                        "Original bound Node terminal journal is unavailable; replay blocked",
                    )
                    return self._projection(automation_id, run_id)
                if self.before_consume is not None:
                    self.before_consume()
                await components.start()
                if self.before_consume is not None:
                    self.before_consume()
                runtime = WorkflowRuntime(
                    str(self.root),
                    handlers=components.handlers,
                    event_bus=components.bus,
                    max_parallel=1,
                )
                run = self.store.automation_run(automation_id, run_id)
                if phase in {"resume", "reconcile"}:
                    # Recovery consults persisted receipt journals, then observes
                    # only. It cannot create a replacement mutation Work.
                    for output in run.outputs.values():
                        work_id = (
                            output.get("work_id") if isinstance(output, dict) else None
                        )
                        work = (
                            DistributedWorkStore(self.controller_state).get(work_id)
                            if work_id
                            else None
                        )
                        if (
                            work is not None
                            and work.execution_policy.require_effect_verification
                            and work.state
                            in {
                                DistributedWorkState.ASSIGNED,
                                DistributedWorkState.RUNNING,
                                DistributedWorkState.SUCCEEDED,
                                DistributedWorkState.RECOVERING,
                                DistributedWorkState.UNKNOWN,
                                DistributedWorkState.VERIFIED,
                            }
                        ):
                            if work.state is not DistributedWorkState.VERIFIED:
                                from nous_runtime.reality.preview import _wait

                                await _wait(
                                    lambda: work_id in components.server.results,
                                    timeout=5,
                                )
                            await asyncio.to_thread(
                                components.handler.recover_verified, work_id
                            )
                    if phase == "resume":
                        if run.state is WorkflowState.PENDING:
                            await asyncio.to_thread(
                                runtime.start,
                                run.workflow_id,
                                run.workflow_version,
                                run.inputs,
                                idempotency_key=run.idempotency_key,
                            )
                        else:
                            await asyncio.to_thread(runtime.resume, run_id)
                    elif (
                        run.cancellation_requested
                        and not self._projection(automation_id, run_id)[
                            "reconciliation_required"
                        ]
                    ):
                        self.store.update_run(
                            run_id,
                            state=WorkflowState.CANCELLED,
                            cancel=True,
                            error="Original effect reconciled; future admission remains cancelled",
                        )
                elif self.store.get_automation(automation_id)["enabled"]:
                    await asyncio.to_thread(
                        runtime.start,
                        run.workflow_id,
                        run.workflow_version,
                        run.inputs,
                        idempotency_key=run.idempotency_key,
                    )
                return self._projection(
                    automation_id, run_id, provider=components.provider
                )
            finally:
                await components.close()

        # One local simulator lifecycle at a time; Workflow locks still own
        # execution exclusion and allow cancellation while handlers run.
        with file_lock(self.root / ".nous" / "automation-simulation.lock"):
            return asyncio.run(consume())

    def _terminal_journals_match(self, components, works):
        """Validate original Node evidence before opening its delivery transport."""
        from nous_runtime.node_runtime.relay import (
            _payload_digest,
            _verify_at_most_once_result,
        )

        try:
            persisted = json.loads(
                components.node.workloads_path.read_text(encoding="utf-8")
            )
            status = components.node.run_once()
            node_id = status["node_id"]
            for work in works:
                work_id = work["work_id"]
                journal = persisted.get(work_id)
                assignment = work["assignment"]
                dispatch = work["dispatch_record"]
                if (
                    not isinstance(journal, dict)
                    or journal not in status["workloads"]
                    # Node journal states differ from Controller Work states.
                    # A pre-start CANCELLED record has no bound receipt.
                    or journal.get("state") not in {"COMPLETED", "FAILED"}
                    or work["assigned_node"] != node_id
                    or assignment["node_id"] != node_id
                    or assignment["work_id"] != work_id
                    or assignment["input_artifacts"] != work["input_artifacts"]
                    or assignment["execution_policy"] != work["execution_policy"]
                    or dispatch.get("work_id") != work_id
                    or dispatch.get("assignment_id") != assignment["assignment_id"]
                    or dispatch.get("node_id") != node_id
                    or dispatch.get("delivery") != "at_most_once"
                    or dispatch.get("input_artifacts") != work["input_artifacts"]
                ):
                    return False
                original = self.gate.get_operation_request(
                    work["execution_arguments"]["authorization_id"]
                )
                if (
                    original.work_id != work_id
                    or original.operation_id != work_id
                    or original.workflow_run_id != work["provenance"]["workflow_run_id"]
                    or original.node_id != node_id
                    or original.capability_id != work["execution_capability"]
                    or original.resource_id != work["target_resource_id"]
                    or original.expected_effect != work["expected_effect"]
                    or list(original.input_artifacts) != work["input_artifacts"]
                ):
                    return False
                # Reconstruct only the recorded provider request for comparison;
                # this evidence check never stages or queues a dispatch.
                request = {
                    "schema": "nous.remote-provider-request/v1",
                    "operation_id": work_id,
                    "workload_id": work_id,
                    "step_id": assignment["assignment_id"],
                    "node_id": node_id,
                    "capability": work["execution_capability"],
                    "arguments": work["execution_arguments"],
                    "timeout_seconds": 30.0,
                    "delivery_semantics": "at_most_once",
                    "binding": journal["binding"],
                    "input_artifacts": work["input_artifacts"],
                }
                if dispatch.get("provider_request_digest") != _payload_digest(request):
                    return False
                path = components.server.provider_requests / f"{work_id}.json"
                if (
                    path.exists()
                    and json.loads(path.read_text(encoding="utf-8")) != request
                ):
                    return False
                pending = components.server.pending.get(node_id, {}).get(work_id)
                if pending is not None and pending != {
                    field: request[field]
                    for field in (
                        "workload_id",
                        "capability",
                        "arguments",
                        "timeout_seconds",
                        "delivery_semantics",
                        "binding",
                    )
                }:
                    return False
                _verify_at_most_once_result(node_id, request, journal)
                cached = components.server.results.get(work_id)
                if cached is not None and cached != journal:
                    return False
                receipt = journal["receipt"]
                if (
                    journal.get("delivery_semantics") != "at_most_once"
                    or receipt.get("delivery_semantics") != "at_most_once"
                    or receipt.get("result") != journal["state"]
                    or receipt.get("effect_digest")
                    != _payload_digest(
                        {
                            key: value
                            for key, value in journal.items()
                            if key != "receipt"
                        }
                    )
                ):
                    return False
            return True
        except (OSError, KeyError, TypeError, ValueError, PermissionError):
            return False

    def _historical_result(self, work, cas, relay):
        """Read original signed execution evidence without admitting a new call."""
        from nous_runtime.node_runtime.protocol import NodeProtocolEnvelope
        from nous_runtime.node_runtime.relay import (
            CONTROL_PLANE_ID,
            _payload_digest,
            _verify_at_most_once_result,
            _verify_recorded_result,
            remote_execution_receipt,
        )

        def read(ref):
            digest = "sha256:" + ref.removeprefix("artifact://sha256/")
            return json.loads(
                cas.resolve(digest, verify=True).read_text(encoding="utf-8")
            )

        summary = work.result_summary
        evidence = read(summary["evidence_artifact"])
        receipt = evidence["remote_execution_receipt"]
        raw = receipt["signed_envelope"]
        envelope = NodeProtocolEnvelope.from_json(json.dumps(raw), check_time=False)
        payload = envelope.payload
        assignment = work.assignment
        if (
            evidence.get("schema") != "apeir.distributed-work-evidence/v1"
            or evidence.get("work_id") != work.work_id
            or summary["evidence_artifact"] not in work.evidence_refs
            or summary["output_artifact"] not in work.output_artifacts
            or receipt != summary["remote_execution_receipt"]
            or receipt
            != remote_execution_receipt(raw, expected_operation_id=work.work_id)
            or envelope.source != work.assigned_node
            or envelope.target != CONTROL_PLANE_ID
            or not envelope.verify(relay.node_keys.get(work.assigned_node, ""))
            or relay.results.get(work.work_id) != payload
            or assignment is None
            or assignment.work_id != work.work_id
            or assignment.node_id != work.assigned_node
            or assignment.input_artifacts != work.input_artifacts
            or assignment.execution_policy != work.execution_policy
        ):
            raise ValueError("Original signed Work receipt binding changed")
        _verify_recorded_result(work, payload, raw, status="VERIFIED")
        request = {
            "schema": "nous.remote-provider-request/v1",
            "operation_id": work.work_id,
            "workload_id": work.work_id,
            "step_id": assignment.assignment_id,
            "node_id": work.assigned_node,
            "capability": work.execution_capability,
            "arguments": work.execution_arguments,
            "timeout_seconds": 30.0,
            "delivery_semantics": "at_most_once",
            "binding": payload["binding"],
            "input_artifacts": list(work.input_artifacts),
        }
        dispatch = work.dispatch_record
        if any(
            dispatch.get(key) != value
            for key, value in {
                "work_id": work.work_id,
                "assignment_id": assignment.assignment_id,
                "node_id": work.assigned_node,
                "delivery": "at_most_once",
                "input_artifacts": list(work.input_artifacts),
                "provider_request_digest": _payload_digest(request),
            }.items()
        ):
            raise ValueError("Original Work dispatch binding changed")
        _verify_at_most_once_result(work.assigned_node, request, payload)
        if read(summary["output_artifact"]) != {
            "schema": "apeir.distributed-work-output/v1",
            "work_id": work.work_id,
            "node_id": work.assigned_node,
            "output": payload.get("output"),
        }:
            raise ValueError("Original Work output changed")
        original = self.gate.get_operation_request(
            work.execution_arguments["authorization_id"]
        )
        if (
            original.operation_id != work.work_id
            or original.work_id != work.work_id
            or original.node_id != work.assigned_node
            or original.capability_id != work.execution_capability
            or original.resource_id != work.target_resource_id
            or original.expected_effect != work.expected_effect
        ):
            raise ValueError("Original Work Governance binding changed")
        return receipt, payload, original

    def _historical_work_evidence(self, run, step, work, cas, relay, works):
        from dataclasses import replace
        from nous_runtime.node_runtime.distributed_workflow import (
            DistributedWorkflowAdapter,
        )
        from nous_runtime.planner.observation import Observation
        from nous_runtime.reality.execution import _operation_from_dict
        from nous_runtime.reality.verification import EffectVerifier

        receipt, _, original = self._historical_result(work, cas, relay)
        inputs = run.inputs
        provenance = {
            "plan_id": inputs["_plan_id"],
            "workflow_id": run.workflow_id,
            "workflow_run_id": run.run_id,
            "workflow_step_id": step.step_id,
        }
        if (
            work.work_id
            != DistributedWorkflowAdapter._work_id(step, {"run_id": run.run_id})
            or any(
                work.provenance.get(key) != value for key, value in provenance.items()
            )
            or original.plan_id != inputs["_plan_id"]
            or original.workflow_run_id != run.run_id
            or original.subject_id != inputs["_agent_id"]
            or original.agent_session_id != str(inputs.get("_agent_session_id") or "")
            or work.execution_capability != step.params["capability"]
            or work.target_resource_id != step.params["device_id"]
            or work.expected_effect != step.params.get("expected_effect", {})
            or work.execution_policy.require_effect_verification
            != (step.action == "reality.operation")
        ):
            raise ValueError("Original Workflow and Work semantic binding changed")
        if not work.execution_policy.require_effect_verification:
            return
        operation_value = work.execution_arguments["operation"]
        operation = _operation_from_dict(operation_value, node_id=work.assigned_node)
        if (
            any(
                operation_value.get(key) != value
                for key, value in {
                    **provenance,
                    "work_id": work.work_id,
                    "operation_id": work.work_id,
                    "capability_id": work.execution_capability,
                    "target_resource_id": work.target_resource_id,
                    "expected_effect": work.expected_effect,
                }.items()
                if key != "workflow_step_id"
            )
            or operation.input_artifacts != work.input_artifacts
            or original.input_artifacts != work.input_artifacts
            or list(work.input_artifacts)
            != [work.execution_arguments["mutation_artifact"]]
        ):
            raise ValueError("Original Operation binding changed")
        mutation = json.loads(
            cas.resolve(
                "sha256:" + work.input_artifacts[0].removeprefix("artifact://sha256/"),
                verify=True,
            ).read_text(encoding="utf-8")
        )
        if (
            mutation.get("schema") != "apeir.reality-mutation-input/v1"
            or mutation.get("operation_id") != work.work_id
            or mutation.get("device_id") != work.target_resource_id
            or mutation.get("capability_id") != work.execution_capability
            or mutation.get("mutation") != step.params["mutation"]
            or any(
                mutation.get("provenance", {}).get(key) != value
                for key, value in {
                    **provenance,
                    "work_id": work.work_id,
                    "operation_id": work.work_id,
                }.items()
            )
        ):
            raise ValueError("Original mutation CAS provenance changed")
        observations = []
        verifications = []
        for ref in work.evidence_refs:
            digest = "sha256:" + ref.removeprefix("artifact://sha256/")
            artifact = cas.get(digest)
            if artifact.media_type not in {
                "application/vnd.apeir.observation+json",
                "application/vnd.apeir.effect-verification+json",
            }:
                continue
            value = json.loads(
                cas.resolve(digest, verify=True).read_text(encoding="utf-8")
            )
            if artifact.media_type == "application/vnd.apeir.effect-verification+json":
                if artifact.produced_by != "reality.effect-verifier/v1":
                    raise ValueError("Original EffectVerifier provenance changed")
                verifications.append((artifact, value))
                continue
            observation = Observation(**value)
            acquisition_id = observation.metadata["acquisition_id"]
            read_work = works.get(acquisition_id)
            if read_work is None:
                raise ValueError("Original observation Work is unavailable")
            _, result, read_request = self._historical_result(read_work, cas, relay)
            if (
                result.get("output") != value
                or read_work.execution_capability != "device.state.read"
                or read_work.target_resource_id != work.target_resource_id
                or read_work.assigned_node != work.assigned_node
                or read_request.plan_id != original.plan_id
                or read_request.workflow_run_id != run.run_id
                or read_request.subject_id != original.subject_id
                or artifact.metadata.get("observation_work_id") != acquisition_id
                or artifact.metadata.get("observation_id") != observation.observation_id
                or any(
                    "sha256:" + item.removeprefix("artifact://sha256/")
                    not in artifact.depends_on
                    for item in read_work.evidence_refs
                )
            ):
                raise ValueError("Original independent Observation provenance changed")
            observations.append((artifact, observation))
        matching = [
            item for item in verifications if item[1] == work.effect_verification
        ]
        selected = [
            item
            for item in observations
            if item[1].observation_id
            in work.effect_verification.get("observation_ids", ())
        ]
        if len(matching) != 1 or not selected:
            raise ValueError(
                "Original Observation or EffectVerification proof is unavailable"
            )
        artifact, recorded = matching[0]
        if any(item.digest not in artifact.depends_on for item, _ in selected):
            raise ValueError("Original verification CAS dependencies changed")
        operation = replace(
            operation, observation_request_id=selected[-1][1].metadata["acquisition_id"]
        )
        verified = json.loads(
            json.dumps(
                EffectVerifier()
                .verify(operation, receipt, [item for _, item in selected])
                .to_dict()
            )
        )
        # Re-evaluation creates a new identity/time; compare the original CAS
        # record exactly above, then compare only the deterministic semantics.
        if recorded.get("verdict") != "MATCH" or any(
            recorded.get(key) != value
            for key, value in verified.items()
            if key not in {"verification_id", "verified_at"}
        ):
            raise ValueError("Original EffectVerification semantics changed")

    def _projection(self, automation_id, run_id, *, provider=None):
        run = self.store.automation_run(automation_id, run_id)
        works = DistributedWorkStore(self.controller_state)
        records = []
        cas = ContentAddressedArtifactStore(self.controller_state / "artifacts")
        definition = self.store.get_definition(run.workflow_id, run.workflow_version)
        steps = {step.step_id: step for step in definition.steps}
        if run.state is WorkflowState.COMPLETED:
            # A completed projection must account for every original step. Do
            # not reconstruct omitted output from a checkpoint: the omission is
            # itself inconsistent persisted evidence, not another execution.
            if set(run.outputs) != set(steps) or set(run.step_states) != set(steps):
                raise WorkflowBindingError(
                    "Completed Automation has incomplete original step evidence"
                )
            checkpoints = self.store.checkpoints(run_id)
            validator = WorkflowRuntime(str(self.root))
            for step_id, step in steps.items():
                output = run.outputs[step_id]
                checkpoint = checkpoints.get(step_id, {})
                if (
                    run.step_states[step_id] != "completed"
                    or checkpoint.get("status") != "completed"
                    or not isinstance(output, dict)
                    or not output.get("work_id")
                    or checkpoint.get("output") != output
                ):
                    raise WorkflowBindingError(
                        "Completed Automation original step output changed"
                    )
                validator._validate_checkpoint(run, step, checkpoint)
        relay = None
        for step_id, output in run.outputs.items():
            if not isinstance(output, dict) or not output.get("work_id"):
                continue
            work = works.get(output["work_id"])
            if work is None or work.provenance.get("workflow_run_id") != run_id:
                raise WorkflowBindingError(
                    "Original Automation Work evidence is unavailable or changed"
                )
            if (
                run.state is WorkflowState.COMPLETED
                and work.state is not DistributedWorkState.COMMITTED
            ):
                raise WorkflowBindingError(
                    "Completed Automation original Work is not committed"
                )
            for ref in (
                *work.input_artifacts,
                *work.output_artifacts,
                *work.evidence_refs,
            ):
                if not ref.startswith("artifact://sha256/") or not cas.verify(
                    "sha256:" + ref.removeprefix("artifact://sha256/")
                ):
                    raise ArtifactError("Original Automation Artifact integrity failed")
            if work.state is DistributedWorkState.COMMITTED:
                from nous_runtime.node_runtime.relay import NodeRelayServer

                try:
                    if relay is None:
                        relay = NodeRelayServer(state_dir=self.controller_state)
                    self._historical_work_evidence(
                        run, steps[step_id], work, cas, relay, works
                    )
                except (
                    OSError,
                    KeyError,
                    TypeError,
                    ValueError,
                    PermissionError,
                    RuntimeError,
                ) as exc:
                    raise WorkflowBindingError(
                        "Original Automation semantic evidence is unavailable or changed"
                    ) from exc
            records.append(work.to_dict())
        if provider is None:
            from nous_runtime.reality.preview import DEFINITION
            from nous_runtime.reality.provider import SimulatedDeviceProvider

            provider = SimulatedDeviceProvider(
                DEFINITION,
                state_dir=self.root
                / ".nous"
                / "automation-simulation"
                / "simulated-device",
            )
        reconciliation_required = any(
            work["execution_policy"].get("require_effect_verification", False)
            and (
                work["state"]
                in {"ASSIGNED", "RUNNING", "SUCCEEDED", "RECOVERING", "UNKNOWN"}
                or work["effect_verification"].get("verdict") == "UNKNOWN"
            )
            for work in records
        )
        return {
            "automation_id": automation_id,
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "state": run.state.value,
            "step_states": run.step_states,
            "outputs": run.outputs,
            "cancellation_requested": run.cancellation_requested,
            "error": run.error,
            "works": records,
            "reconciliation_required": reconciliation_required,
            "simulated": True,
            "execution_scope": "runtime-service",
            "kernel_traversed": False,
            "effect_counts": {
                work["work_id"]: provider.execution_count(work["work_id"])
                for work in records
            },
        }
