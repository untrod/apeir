"""Reality bindings for the existing Workflow, Distributed Work, and Node path."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.governance.gate import ExecutionAuthorizationGate, get_gate
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.operation_contracts import (
    GovernanceApprovalRequired,
    GovernanceDecision,
    GovernanceRequest,
)
from nous_runtime.planner.observation import Observation
from nous_runtime.node_runtime.distributed_work import (
    DistributedWork,
    DistributedWorkError,
    DistributedWorkState,
)
from nous_runtime.node_runtime.distributed_workflow import DistributedWorkflowAdapter
from nous_runtime.node_runtime.relay import NodeRelayServer
from nous_runtime.node_runtime.service import WorkloadResponseLost
from nous_runtime.reality.contracts import (
    DeviceLifecycle,
    EffectVerdict,
    Operation,
    RelationKind,
    utc_now,
)
from nous_runtime.reality.graph import ResourceGraph
from nous_runtime.reality.provider import (
    SimulatedDeviceProvider,
    SimulatedResponseLost,
)
from nous_runtime.reality.registry import DeviceRegistry
from nous_runtime.reality.verification import EffectVerifier
from nous_runtime.workflow.models import StepType, WorkflowStep


class SimulatedDeviceOperationHandler:
    """Node capability handler backed by the simulator and the Node-local CAS."""

    capability_id = "device.state.set"
    accepts_authorization_context = True

    def __init__(
        self,
        provider: SimulatedDeviceProvider,
        registry: DeviceRegistry,
        artifact_store: ContentAddressedArtifactStore,
        *,
        governance: ExecutionAuthorizationGate | None = None,
        capability_id: str = "device.state.set",
        credential_broker=None,
    ):
        self.provider = provider
        self.registry = registry
        self.artifact_root = artifact_store.root
        self.capability_id = capability_id
        self.governance = governance or get_gate()
        self.credential_broker = credential_broker

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._execute(arguments, admitted=False)

    def _execute(
        self,
        arguments: dict[str, Any],
        *,
        admitted: bool,
        before_effect=None,
        credential_context=None,
    ) -> dict[str, Any]:
        operation_value = arguments.get("operation")
        if not isinstance(operation_value, Mapping):
            raise ValueError("Reality operation binding is required")
        operation_id = str(operation_value.get("operation_id") or "")
        device_id = str(operation_value.get("target_resource_id") or "")
        capability_id = str(operation_value.get("capability_id") or "")
        device = self.registry.get(device_id)
        if device is None:
            raise LookupError(f"device not found: {device_id}")
        if device.lifecycle is not DeviceLifecycle.AVAILABLE:
            raise RuntimeError(f"device is not available: {device.lifecycle.value}")
        input_ref = str(arguments.get("mutation_artifact") or "")
        digest = _artifact_digest(input_ref)
        artifacts = ContentAddressedArtifactStore(self.artifact_root)
        payload = json.loads(
            artifacts.resolve(digest, verify=True).read_text(encoding="utf-8")
        )
        if (
            payload.get("schema") != "apeir.reality-mutation-input/v1"
            or payload.get("operation_id") != operation_id
            or payload.get("device_id") != device_id
            or payload.get("capability_id") != capability_id
            or not isinstance(payload.get("mutation"), Mapping)
        ):
            raise ValueError("Reality mutation Artifact binding is invalid")
        if not admitted:
            raise PermissionError(
                "Reality mutation requires bound Node governance admission"
            )
        try:
            result = self.provider.apply_operation(
                device,
                operation_id=operation_id,
                capability_id=capability_id,
                mutation=dict(payload["mutation"]),
                before_effect=before_effect,
                **(
                    {"credential_context": credential_context}
                    if credential_context is not None
                    else {}
                ),
            )
        except SimulatedResponseLost as exc:
            raise WorkloadResponseLost(
                str(exc), output=exc.output, completed=exc.effect_applied
            ) from exc
        except LookupError:
            self.provider.disconnect(device.stable_identity, registry=self.registry)
            raise
        return {
            **result,
            "mutation_artifact": input_ref,
            "provenance": dict(payload.get("provenance") or {}),
            "authorization_id": arguments["authorization_id"],
        }

    def execute_bound(
        self,
        arguments: dict[str, Any],
        *,
        workload_id: str,
        node_id: str,
        binding: Mapping[str, str],
        authorization_context=None,
    ) -> dict[str, Any]:
        operation = arguments.get("operation") or {}
        if (
            operation.get("operation_id") != workload_id
            or operation.get("work_id") != workload_id
            or operation.get("capability_id") != self.capability_id
            or binding.get("target_ref")
            != f"device://{operation.get('target_resource_id')}/capability/{self.capability_id}"
        ):
            raise ValueError("Reality Operation does not match its Node Work binding")
        device = self.registry.get(str(operation.get("target_resource_id") or ""))
        if device is not None and device.node_id and device.node_id != node_id:
            raise ValueError("Reality Device is hosted by a different Node")
        authorization_id = str(arguments.get("authorization_id") or "")
        request = self.governance.get_operation_request(authorization_id)
        if (
            request.operation_id != workload_id
            or request.node_id != node_id
            or request.capability_id != self.capability_id
            or request.resource_id != operation.get("target_resource_id")
            or request.agent_session_id != operation.get("agent_session_id")
            or request.expected_effect != operation.get("expected_effect")
            or list(request.input_artifacts) != operation.get("input_artifacts")
            or list(request.input_artifacts) != [arguments.get("mutation_artifact")]
            or list(request.secret_handles) != operation.get("secret_handles", [])
            or list(request.secret_handles) != arguments.get("secret_handles", [])
        ):
            raise PermissionError("Node Operation authorization binding differs")
        with self.governance.admit_operation(
            authorization_id,
            resource_check=lambda: (
                self.registry.get(request.resource_id).lifecycle
                is DeviceLifecycle.AVAILABLE
            ),
            authorization_context=authorization_context,
        ) as revalidate:
            if request.secret_handles:
                if (
                    self.credential_broker is None
                    or self.credential_broker.gate is not self.governance
                ):
                    raise PermissionError(
                        "CredentialBroker is unavailable at the Node boundary"
                    )
                return self.credential_broker.run_provider(
                    authorization_id,
                    authorization_context,
                    admission=revalidate,
                    call=lambda credentials: self._execute(
                        arguments,
                        admitted=True,
                        before_effect=credentials.revalidate,
                        credential_context=credentials,
                    ),
                )
            return self._execute(arguments, admitted=True, before_effect=revalidate)

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Acquire a separate observation through a read-only Node Work."""
        device_id = str(arguments.get("device_id") or "")
        device = self.registry.get(device_id)
        if device is None:
            raise LookupError(f"device not found: {device_id}")
        if device.lifecycle is not DeviceLifecycle.AVAILABLE:
            return Observation.failure(
                "reality.device.read",
                [f"device is {device.lifecycle.value}"],
                capability="device.state.read",
                metadata={"device_id": device_id},
            ).to_dict()
        authorization_id = str(arguments.get("authorization_id") or "")
        request = self.governance.get_operation_request(authorization_id)
        if (
            request.resource_id != device_id
            or request.capability_id != "device.state.read"
            or request.operation_id != arguments.get("acquisition_id")
        ):
            raise PermissionError("Observation authorization binding differs")
        with self.governance.admit_operation(
            authorization_id,
            resource_check=lambda: (
                self.registry.get(device_id).lifecycle is DeviceLifecycle.AVAILABLE
            ),
        ):
            return self.provider.read_state(
                device, acquisition_id=str(arguments.get("acquisition_id") or "")
            ).to_dict()


class RealityOperationWorkflowHandler:
    """Translate one Reality Plan step into the authoritative distributed path."""

    def __init__(
        self,
        controller_state: str | Path,
        *,
        provider: SimulatedDeviceProvider,
        registry: DeviceRegistry,
        graph: ResourceGraph | None = None,
        poll_interval_seconds: float = 0.05,
        governance: ExecutionAuthorizationGate | None = None,
    ):
        self.controller_state = Path(controller_state).expanduser().resolve()
        self.provider = provider
        self.registry = registry
        self.governance = governance or get_gate()
        self.approvals = ApprovalBroker(self.governance.store)
        self.graph = graph or ResourceGraph(self.controller_state)
        self.artifacts = ContentAddressedArtifactStore(
            self.controller_state / "artifacts"
        )
        self.distributed = DistributedWorkflowAdapter(
            self.controller_state,
            poll_interval_seconds=poll_interval_seconds,
            verified_work_finalizer=self._finalize,
            work_admitter=self._authorize_work,
        )

    def __call__(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        params = dict(step.params)
        from nous_runtime.governance.credentials import validate_secret_handles

        secret_handles = validate_secret_handles(params.get("secret_handles", ()))
        device_id = str(params.get("device_id") or "")
        device = self.registry.get(device_id)
        if device is None:
            raise DistributedWorkError(f"Reality target device not found: {device_id}")
        if device.lifecycle is not DeviceLifecycle.AVAILABLE:
            raise DistributedWorkError(
                f"Reality target is not AVAILABLE: {device.lifecycle.value}"
            )
        capability_id = str(params.get("capability") or "device.state.set")
        if capability_id == "device.state.read":
            return self._observe_step(step, context, device)
        expected_effect = params.get("expected_effect")
        mutation = params.get("mutation")
        if redact_sensitive_data(
            {"mutation": mutation, "expected_effect": expected_effect}
        ) != {"mutation": mutation, "expected_effect": expected_effect}:
            raise ValueError(
                "Credential material cannot enter Reality Work or Artifact inputs"
            )
        if capability_id == "device.firmware.update":
            self.provider.validate_firmware_mutation(mutation)
        if not isinstance(expected_effect, Mapping) or not expected_effect:
            raise DistributedWorkError("Reality expected_effect must be non-empty")
        if not isinstance(mutation, Mapping) or not mutation:
            raise DistributedWorkError("Reality mutation must be non-empty")
        work_id = str(
            params.get("work_id") or DistributedWorkflowAdapter._work_id(step, context)
        )
        inputs = context.get("inputs") or {}
        existing_controller = self.distributed._controller()
        assert existing_controller.work_store is not None
        existing = existing_controller.work_store.get(work_id)
        prior_operation = (
            existing.execution_arguments.get("operation") if existing else {}
        )
        operation = Operation(
            operation_id=work_id,
            work_id=work_id,
            capability_id=capability_id,
            target_resource_id=device_id,
            expected_effect=dict(expected_effect),
            agent_session_id=str(inputs.get("_agent_session_id") or ""),
            plan_id=str(inputs.get("_plan_id") or ""),
            workflow_id=str(inputs.get("_workflow_id") or ""),
            workflow_run_id=str(context.get("run_id") or ""),
            requested_at=str((prior_operation or {}).get("requested_at") or utc_now()),
            secret_handles=secret_handles,
        )
        provenance = {
            "agent_session_id": operation.agent_session_id,
            "plan_id": operation.plan_id,
            "workflow_id": operation.workflow_id,
            "workflow_run_id": operation.workflow_run_id,
            "workflow_step_id": step.step_id,
            "work_id": work_id,
            "operation_id": operation.operation_id,
            "device_id": device_id,
            "capability_id": capability_id,
        }
        mutation_value = {
            "schema": "apeir.reality-mutation-input/v1",
            "operation_id": operation.operation_id,
            "device_id": device_id,
            "capability_id": capability_id,
            "mutation": dict(mutation),
            "provenance": {key: value for key, value in provenance.items() if value},
        }
        if secret_handles:
            mutation_value["secret_handles"] = list(secret_handles)
        stored = self.artifacts.store_bytes(
            json.dumps(
                mutation_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            artifact_type="configuration",
            name=f"{operation.operation_id}-mutation.json",
            media_type="application/vnd.apeir.reality-mutation+json",
            produced_by=f"agent-session:{operation.agent_session_id or 'unknown'}",
            metadata={key: value for key, value in provenance.items() if value},
        )
        mutation_ref = _artifact_reference(str(stored["artifact"]["digest"]))
        operation = replace(operation, input_artifacts=(mutation_ref,))
        if existing is None or self.graph.get(work_id) is None:
            self._project_operation(device, operation)
        request = GovernanceRequest(
            operation_id=work_id,
            work_id=work_id,
            capability_id=capability_id,
            resource_id=device_id,
            subject_id=str(inputs.get("_agent_id") or "anonymous-agent"),
            agent_session_id=operation.agent_session_id,
            plan_id=operation.plan_id,
            workflow_run_id=operation.workflow_run_id,
            node_id=device.node_id,
            input_artifacts=operation.input_artifacts,
            expected_effect=dict(expected_effect),
            capability_inputs=self.governance.capability_inputs(capability_id),
            secret_handles=secret_handles,
        )
        authorization_id = self.governance.register_operation(request)
        distributed_step = replace(
            step,
            action="distributed",
            params={
                **params,
                "work_id": work_id,
                "intent": str(
                    params.get("intent") or step.params.get("name") or step.step_id
                ),
                "capability": capability_id,
                "requirements": {
                    **dict(params.get("requirements") or {}),
                    **({"node_ids": [device.node_id]} if device.node_id else {}),
                },
                "arguments": {
                    "operation": operation.to_dict(),
                    "mutation_artifact": mutation_ref,
                    "authorization_id": authorization_id,
                    **(
                        {"secret_handles": list(secret_handles)}
                        if secret_handles
                        else {}
                    ),
                },
                "input_artifacts": [mutation_ref],
                "target_resource_id": device_id,
                "expected_effect": dict(expected_effect),
                "operation_id": operation.operation_id,
                "require_effect_verification": True,
            },
        )
        try:
            output = self.distributed(distributed_step, context)
        except GovernanceApprovalRequired:
            raise
        except Exception as exc:
            current_controller = self.distributed._controller()
            assert current_controller.work_store is not None
            current = current_controller.work_store.get(work_id)
            raise DistributedWorkError(
                str(exc),
                workflow_output=(
                    DistributedWorkflowAdapter._output(current.to_dict())
                    if current
                    else {}
                ),
            ) from exc
        observed = self.graph.get(work_id)
        output.update(
            {
                "operation": dict(observed.attributes)
                if observed
                else operation.to_dict(),
                "receipt": dict(output["verification"]["remote_execution_receipt"]),
                "observations": [
                    dict(self.graph.get(item).attributes)
                    for item in output["effect_verification"].get("observation_ids", ())
                ],
                "execution_scope": "distributed-simulation",
                "kernel_traversed": False,
            }
        )
        return output

    def _authorize_work(self, work: DistributedWork) -> None:
        authorization_id = work.execution_arguments["authorization_id"]
        verdict = self.governance.evaluate_operation(authorization_id)
        if verdict is GovernanceDecision.REQUIRE_APPROVAL:
            approval = self.approvals.request_operation(
                authorization_id, gate=self.governance
            )
            raise GovernanceApprovalRequired(
                {
                    **DistributedWorkflowAdapter._output(work.to_dict()),
                    "approval_request_id": approval.request_id,
                    "authorization_id": authorization_id,
                    "governance_decision": verdict.value,
                }
            )
        if verdict is not GovernanceDecision.ALLOW:
            raise DistributedWorkError(f"Governance denied execution: {verdict.value}")

    def _observe_step(self, step, context, device):
        work_id = str(
            step.params.get("work_id")
            or DistributedWorkflowAdapter._work_id(step, context)
        )
        inputs = context.get("inputs") or {}
        request = GovernanceRequest(
            operation_id=work_id,
            work_id=work_id,
            capability_id="device.state.read",
            resource_id=device.device_id,
            subject_id=str(inputs.get("_agent_id") or "anonymous-agent"),
            agent_session_id=str(inputs.get("_agent_session_id") or ""),
            plan_id=str(inputs.get("_plan_id") or ""),
            workflow_run_id=context.get("run_id", ""),
            node_id=device.node_id,
            capability_inputs=self.governance.capability_inputs("device.state.read"),
        )
        authorization_id = self.governance.register_operation(request)
        adapter = DistributedWorkflowAdapter(
            self.controller_state, work_admitter=self._authorize_work
        )
        output = adapter(
            replace(
                step,
                action="distributed",
                params={
                    "work_id": work_id,
                    "capability": "device.state.read",
                    "arguments": {
                        "device_id": device.device_id,
                        "acquisition_id": work_id,
                        "authorization_id": authorization_id,
                    },
                    "requirements": {"node_ids": [device.node_id]},
                    "target_resource_id": device.device_id,
                    "wait_timeout_seconds": step.params.get("wait_timeout_seconds", 30),
                },
            ),
            context,
        )
        output["observation"] = adapter._controller().results[work_id]["output"]
        return output

    def recover_verified(self, work_id: str) -> DistributedWork:
        """Resume only the observation/verification phase; never replay the effect."""
        controller = self.distributed._controller()
        assert controller.work_store is not None
        work = controller.work_store.get(work_id)
        if work is None:
            raise DistributedWorkError(f"Work does not exist: {work_id}")
        if work.state is DistributedWorkState.COMMITTED:
            return work
        if work.work_id in controller.results:
            controller.reconcile_work(work_id)
            work = controller.work_store.get(work_id)
        return self._finalize(
            controller,
            work,
            WorkflowStep(
                "recovery", action="distributed", step_type=StepType.CAPABILITY
            ),
            {"run_id": work.provenance.get("workflow_run_id", ""), "inputs": {}},
        )

    def _finalize(
        self,
        controller: NodeRelayServer,
        work: DistributedWork,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> DistributedWork:
        if work.state is not DistributedWorkState.VERIFIED:
            raise DistributedWorkError("Reality finalization requires VERIFIED Work")
        controller.reconcile_work(work.work_id)
        if work.effect_verification.get("verdict") == "MATCH":
            assert controller.work_store is not None
            return controller.work_store.transition(
                work.work_id,
                DistributedWorkState.COMMITTED,
                reason="Recovered persisted independent MATCH and verified evidence",
            )
        operation_value = work.execution_arguments.get("operation")
        if not isinstance(operation_value, Mapping):
            raise DistributedWorkError("Reality Work lost its Operation binding")
        receipt = work.result_summary.get("remote_execution_receipt")
        if not isinstance(receipt, Mapping):
            raise DistributedWorkError("Reality Work has no OperationReceipt")
        operation = _operation_from_dict(operation_value, node_id=work.assigned_node)
        device = self.registry.get(operation.target_resource_id)
        if device is None:
            raise DistributedWorkError("Reality target disappeared")
        acquisition_id = f"observe_{uuid.uuid4().hex}"
        operation = replace(operation, observation_request_id=acquisition_id)
        original_request = self.governance.get_operation_request(
            work.execution_arguments["authorization_id"]
        )
        read_request = replace(
            original_request,
            operation_id=acquisition_id,
            work_id=acquisition_id,
            capability_id="device.state.read",
            secret_handles=(),
            expected_effect={},
            capability_inputs=self.governance.capability_inputs("device.state.read"),
        )
        read_authorization = self.governance.register_operation(read_request)
        read_adapter = DistributedWorkflowAdapter(self.controller_state)
        read_step = replace(
            step,
            action="distributed",
            params={
                "capability": "device.state.read",
                "work_id": acquisition_id,
                "arguments": {
                    "device_id": device.device_id,
                    "acquisition_id": acquisition_id,
                    "authorization_id": read_authorization,
                },
                "requirements": {"node_ids": [work.assigned_node]},
                "input_artifacts": list(work.input_artifacts),
                "target_resource_id": device.device_id,
                "wait_timeout_seconds": step.params.get("wait_timeout_seconds", 30),
            },
        )
        read_output = read_adapter(read_step, context)
        self.artifacts = ContentAddressedArtifactStore(
            self.controller_state / "artifacts"
        )
        read_controller = read_adapter._controller()
        read_payload = read_controller.results[acquisition_id].get("output")
        if not isinstance(read_payload, Mapping):
            raise DistributedWorkError("Node observation output is invalid")
        observation = Observation(**dict(read_payload))
        verification = EffectVerifier().verify(operation, receipt, [observation])
        self.graph.add_operation(operation)
        registration = controller.reports.get(work.assigned_node, {}).get(
            "REGISTER", {}
        )
        identity_value = registration.get("identity")
        if isinstance(identity_value, dict):
            self.graph.add_node(NodeIdentity.from_dict(identity_value))
            self.graph.relate(work.assigned_node, RelationKind.HOSTS, device.device_id)
        self.graph.add_observation(observation)
        self.graph.relate(
            operation.operation_id,
            RelationKind.OBSERVED_BY,
            observation.observation_id,
        )
        self.graph.relate(
            device.device_id,
            RelationKind.OBSERVED_BY,
            observation.observation_id,
        )
        observation_stored = self.artifacts.store_bytes(
            json.dumps(
                observation.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            artifact_type="evidence",
            name=f"{operation.operation_id}-observation.json",
            media_type="application/vnd.apeir.observation+json",
            produced_by=f"reality-observation:{device.device_id}",
            derived_from=tuple(
                _digest_from_reference(item) for item in work.input_artifacts
            ),
            depends_on=tuple(
                _digest_from_reference(item) for item in read_output["evidence_refs"]
            ),
            metadata={
                **work.provenance,
                "observation_id": observation.observation_id,
                "device_id": device.device_id,
                "observation_work_id": acquisition_id,
                "node_id": work.assigned_node,
            },
        )
        observation_digest = str(observation_stored["artifact"]["digest"])
        verification_stored = self.artifacts.store_bytes(
            json.dumps(
                verification.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            artifact_type="verification_result",
            name=f"{operation.operation_id}-effect-verification.json",
            media_type="application/vnd.apeir.effect-verification+json",
            produced_by="reality.effect-verifier/v1",
            depends_on=(
                observation_digest,
                *tuple(_digest_from_reference(item) for item in work.evidence_refs),
            ),
            derived_from=tuple(
                _digest_from_reference(item) for item in work.input_artifacts
            ),
            metadata={
                **work.provenance,
                "verification_id": verification.verification_id,
                "verdict": verification.verdict.value,
            },
        )
        verification_ref = _artifact_reference(
            str(verification_stored["artifact"]["digest"])
        )
        observation_ref = _artifact_reference(observation_digest)
        assert controller.work_store is not None
        recorded = controller.work_store.record_effect_verification(
            work.work_id,
            verification.to_dict(),
            evidence_refs=(observation_ref, verification_ref),
        )
        self.governance.record_operation_evidence(
            work.execution_arguments["authorization_id"],
            "effect.verified",
            verdict=verification.verdict.value,
            observation_ids=list(verification.observation_ids),
            receipt_digest=verification.receipt_digest,
            evidence_refs=[observation_ref, verification_ref],
        )
        if verification.verdict is EffectVerdict.MATCH:
            return controller.work_store.transition(
                recorded.work_id,
                DistributedWorkState.COMMITTED,
                reason="Independent Reality observation matched expected effect",
            )
        # Receipt verification remains durable; only the independent acquisition
        # is retried on recovery. Previous verdict artifacts remain in the CAS.
        return recorded

    def _project_operation(self, device: Any, operation: Operation) -> None:
        self.graph.add_device(device)
        self.graph.add_transport(self.provider.transport.descriptor)
        contract = next(
            (
                c
                for c in self.governance.operation_contracts.list_all()
                if c.capability_id == operation.capability_id
            ),
            None,
        )
        if contract is None:
            raise DistributedWorkError("Unknown Reality capability")
        self.graph.add_capability(contract)
        self.graph.add_operation(operation)
        self.graph.relate(
            device.device_id,
            RelationKind.CONNECTED_TO,
            self.provider.transport.descriptor.transport_id,
        )
        self.graph.relate(
            device.device_id, RelationKind.EXPOSES, operation.capability_id
        )
        self.graph.relate(
            operation.operation_id, RelationKind.REQUIRES, operation.capability_id
        )


def _operation_from_dict(value: Mapping[str, Any], *, node_id: str) -> Operation:
    return Operation(
        work_id=str(value.get("work_id") or ""),
        capability_id=str(value.get("capability_id") or ""),
        target_resource_id=str(value.get("target_resource_id") or ""),
        expected_effect=dict(value.get("expected_effect") or {}),
        operation_id=str(value.get("operation_id") or ""),
        requested_at=str(value.get("requested_at") or ""),
        agent_session_id=str(value.get("agent_session_id") or ""),
        plan_id=str(value.get("plan_id") or ""),
        workflow_id=str(value.get("workflow_id") or ""),
        workflow_run_id=str(value.get("workflow_run_id") or ""),
        node_id=node_id,
        input_artifacts=tuple(value.get("input_artifacts") or ()),
    )


def _artifact_digest(reference: str) -> str:
    prefix = "artifact://sha256/"
    if not reference.startswith(prefix) or len(reference) != len(prefix) + 64:
        raise ValueError("Reality mutation must use an artifact://sha256 reference")
    return "sha256:" + reference.removeprefix(prefix)


def _digest_from_reference(reference: str) -> str:
    return _artifact_digest(reference)


def _artifact_reference(digest: str) -> str:
    if not digest.startswith("sha256:"):
        raise ValueError("Artifact digest must use sha256")
    return "artifact://sha256/" + digest.removeprefix("sha256:")


__all__ = ["RealityOperationWorkflowHandler", "SimulatedDeviceOperationHandler"]
