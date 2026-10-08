"""Replaceable roles and admitted external-agent execution, not new authority.

The host supplies an isolated Environment Provider runner. There is deliberately
no direct host-process fallback. External-agent results remain untrusted content;
the existing Node journal owns execution receipts and uncertain-effect recovery.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import requests

from nous_runtime.agents.adapters.command_adapter import CommandAgentAdapter
from nous_runtime.agents.adapters.supervisor import AdmissionAwareExecutionRunner
from nous_runtime.agents.external.models import (
    AgentDescriptor,
    AgentRunContext,
    AgentRunRequest,
)
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.control_plane.human_sessions import (
    HumanIdentityProvider as IdentityProvider,
)
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.governance.credentials import SecretBackend as SecretProvider
from nous_runtime.governance.operation_contracts import (
    GovernanceDecision,
    GovernanceRequest,
)
from nous_runtime.model_runtime.adapters import (
    ModelBackendAdapter as IntelligenceProvider,
)
from nous_runtime.reality.provider import DeviceProvider
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.operation_contracts import GovernanceApprovalRequired
from nous_runtime.node_runtime.distributed_workflow import DistributedWorkflowAdapter
from nous_runtime.node_runtime.distributed_work import DistributedWorkError
from nous_runtime.workflow.models import WorkflowStep


class PolicyProvider(Protocol):
    """Restrict Core policy; ALLOW cannot grant authority or bypass Core denial."""

    def evaluate(self, request: GovernanceRequest) -> GovernanceDecision: ...


class OpaPolicyProvider:
    """Host-selected OPA Data API adapter; decisions only restrict Core.

    Service authentication and production remote-policy qualification are not
    supplied here. HTTPS uses the platform trust store; plaintext transport is
    limited to loopback. Neither Work nor model output selects this endpoint.
    """

    provider_id = "opa.data-api.v1"
    protocol_revision = "apeir.opa-policy/v1"
    max_response_bytes = 65_536

    def __init__(
        self,
        endpoint: str,
        *,
        policy_path: str = "apeir/decision",
        timeout_seconds: float = 2.0,
    ):
        configuration = {"endpoint": endpoint, "policy_path": policy_path}
        if redact_sensitive_data(configuration) != configuration:
            raise ValueError("OPA configuration must not contain credential material")
        try:
            parsed = urlsplit(endpoint)
        except ValueError:
            raise ValueError("OPA service origin is invalid") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("OPA requires a credential-free service origin")
        # Validate the port now, rather than treating a malformed origin as an
        # unavailable policy during an Operation's authorization transaction.
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("OPA service port is invalid") from None
        if parsed.scheme == "http":
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = parsed.hostname == "localhost"
            if not loopback:
                raise ValueError("OPA plaintext transport requires loopback")
        if (
            not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*",
                policy_path,
            )
            or len(policy_path) > 256
        ):
            raise ValueError("OPA policy path is invalid")
        try:
            timeout = float(timeout_seconds)
        except (ValueError, TypeError):
            raise ValueError("OPA socket timeout is invalid") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError("OPA socket timeout must be between zero and ten seconds")
        self._endpoint = endpoint.rstrip("/")
        self._policy_path = policy_path
        self._timeout = timeout

    def discover(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "role": "policy",
            "capabilities": ["policy.evaluate"],
            "protocol_revision": self.protocol_revision,
            "policy_path": self._policy_path,
            "decisions": [decision.value for decision in GovernanceDecision],
            "authority": False,
        }

    def _query(self, method: str, path: str, payload: dict | None = None) -> dict:
        with requests.Session() as session:
            # Suppress implicit netrc service credentials while retaining the
            # platform's proxy/CA environment. This policy role has no credential
            # resolution authority; explicit callable auth leaves requests intact.
            session.auth = lambda prepared: prepared
            # No redirects, response-body logging, credential store access,
            # caller-supplied headers or implicit policy retry.
            with session.request(
                method,
                self._endpoint + path,
                json=payload,
                timeout=(self._timeout, self._timeout),
                allow_redirects=False,
                stream=True,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise ValueError("OPA service did not return a policy result")
                if (
                    response.headers.get("Content-Type", "").split(";", 1)[0]
                    != "application/json"
                ):
                    raise ValueError("OPA response content type is invalid")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=1024):
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise ValueError("OPA response exceeds its bound")
                value = json.loads(bytes(body))
                if not isinstance(value, dict):
                    raise ValueError("OPA response must be an object")
                return value

    def health(self) -> dict:
        try:
            self._query("GET", "/health")
        except (requests.RequestException, OSError, ValueError, TypeError):
            return {"state": "unavailable", "verified_live": False}
        return {"state": "healthy", "verified_live": True}

    def evaluate(self, request: GovernanceRequest) -> GovernanceDecision:
        try:
            facts = request.to_dict()
            if redact_sensitive_data(facts) != facts:
                return GovernanceDecision.UNKNOWN
            authorization_id = request.authorization_id
            value = self._query(
                "POST",
                "/v1/data/" + self._policy_path,
                {
                    "input": {
                        "schema": self.protocol_revision,
                        "authorization_id": authorization_id,
                        "request": facts,
                    }
                },
            )
            result = value.get("result")
            if (
                not isinstance(result, dict)
                or set(result) != {"decision", "authorization_id"}
                or result["authorization_id"] != authorization_id
                or not isinstance(result["decision"], str)
            ):
                return GovernanceDecision.UNKNOWN
            return GovernanceDecision(result["decision"])
        except (requests.RequestException, OSError, ValueError, TypeError):
            # Errors are availability/evidence failures, never an ALLOW. Their
            # raw bodies and exceptions never enter ordinary audit or Work.
            return GovernanceDecision.UNKNOWN


class ExecutionProvider(Protocol):
    """Existing Node bound handler, distinct from the legacy NPA infer interface."""

    accepts_authorization_context: bool

    def execute_bound(
        self,
        arguments: dict,
        *,
        workload_id: str,
        node_id: str,
        binding: Mapping[str, str],
        authorization_context=None,
    ) -> dict: ...


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ExternalAgentOperationHandler:
    """Host-registered CommandAgentAdapter admitted through canonical Node Work.

    Runtime inputs can supply an objective and references, never a new executable,
    workspace, environment, credentials, runner or authority. A host-runner must
    enforce its advertised isolation; workspace validation alone is not sandboxing.
    """

    capability_id = "agent.external.run"
    accepts_authorization_context = True
    requires_at_most_once = True

    def __init__(
        self,
        descriptor: AgentDescriptor,
        workspace: str | Path,
        artifacts: ContentAddressedArtifactStore,
        *,
        governance,
        execution_runner: Callable | AdmissionAwareExecutionRunner | None = None,
    ):
        if descriptor.validate():
            raise ValueError("Invalid external-agent descriptor")
        self._descriptor = AgentDescriptor.from_dict(descriptor.to_dict())
        self._descriptor_digest = _digest(self._descriptor.to_dict())
        self._workspace = Path(workspace).resolve()
        self._artifacts = artifacts
        self._governance = governance
        self._runner = execution_runner

    @property
    def resource_id(self) -> str:
        return f"agent-provider:{self._descriptor.agent_id}:{self._descriptor_digest}"

    def discover(self) -> dict:
        return {
            "provider_id": self._descriptor.agent_id,
            "resource_id": self.resource_id,
            "capabilities": [self.capability_id],
            "descriptor_digest": self._descriptor_digest,
            "authority": False,
        }

    def health(self) -> dict:
        # No executable probe or model invocation on metadata discovery.
        return {
            "state": "configured" if self._runner is not None else "unavailable",
            "verified_live": False,
            "isolation_required": True,
        }

    def __call__(self, arguments: dict) -> dict:
        raise PermissionError("External agents require bound Node admission")

    def execute_bound(
        self,
        arguments: dict,
        *,
        workload_id: str,
        node_id: str,
        binding: Mapping[str, str],
        authorization_context=None,
    ) -> dict:
        if self._runner is None:
            raise PermissionError("An isolated Environment Provider is required")
        if set(arguments) != {"authorization_id", "input_artifact"}:
            raise PermissionError("External-agent Work contains unbound inputs")
        request = self._governance.get_operation_request(arguments["authorization_id"])
        from nous_runtime.node_runtime.service import _is_node_execution_context

        if not _is_node_execution_context(authorization_context, node_id, workload_id):
            raise PermissionError("An authenticated Node execution context is required")
        reference = arguments["input_artifact"]
        if (
            request.operation_id != workload_id
            or request.work_id != workload_id
            or request.node_id != node_id
            or request.resource_id != self.resource_id
            or request.capability_id != self.capability_id
            or request.input_artifacts != (reference,)
            or request.secret_handles
            or binding.get("target_ref")
            != f"resource://{self.resource_id}/capability/{self.capability_id}"
        ):
            raise PermissionError("External-agent authorization binding differs")
        if not isinstance(reference, str) or not reference.startswith(
            "artifact://sha256/"
        ):
            raise ValueError("External-agent CAS reference is required")
        # Artifact transfer is performed by the Node's canonical CAS instance.
        # Reload its persisted index rather than relying on startup discovery.
        artifacts = ContentAddressedArtifactStore(self._artifacts.root)
        path = artifacts.resolve(
            "sha256:" + reference.removeprefix("artifact://sha256/"), verify=True
        )
        if path.stat().st_size > 1_000_000:
            raise ValueError("External-agent input exceeds its bound")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "descriptor_digest", "request"}
            or payload["schema"] != "apeir.external-agent-input/v1"
            or payload["descriptor_digest"] != self._descriptor_digest
            or redact_sensitive_data(payload) != payload
        ):
            raise ValueError("External-agent input is invalid or contains credentials")
        run = AgentRunRequest.from_dict(payload["request"])
        if (
            run.run_id != workload_id
            or run.task_id != request.work_id
            or run.agent_id != self._descriptor.agent_id
            or run.environment_policy
            or run.allowed_capabilities
            or run.expected_artifacts
            or run.plan
            or run.timeout_ms > self._descriptor.default_timeout_ms
            or run.timeout_ms < 1000
            or run.to_dict() != payload["request"]
            or run.schema_version != self._descriptor.schema_version
        ):
            raise PermissionError(
                "External-agent request differs from its approved scope"
            )
        context = AgentRunContext(
            run_id=run.run_id,
            workspace_path=str(self._workspace),
            session_id=request.agent_session_id,
            node_id=node_id,
        )
        with self._governance.admit_operation(
            request.authorization_id,
            authorization_context=authorization_context,
            resource_check=lambda: (
                self._workspace.is_dir()
                and _digest(self._descriptor.to_dict()) == self._descriptor_digest
            ),
        ) as revalidate:
            adapter = CommandAgentAdapter(
                self._descriptor, before_spawn=revalidate, execution_runner=self._runner
            )
            result = redact_sensitive_data(adapter.execute(run, context).to_dict())
        stored = artifacts.store_bytes(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode(),
            artifact_type="report",
            name=f"{workload_id}-external-agent.json",
            produced_by=f"node:{node_id}",
            metadata={
                "work_id": workload_id,
                "operation_id": workload_id,
                "authorization_id": request.authorization_id,
                "agent_session_id": request.agent_session_id,
                "plan_id": request.plan_id,
                "workflow_run_id": request.workflow_run_id,
                "capability_id": request.capability_id,
                "resource_id": request.resource_id,
                "provider_id": self._descriptor.agent_id,
                "input_artifacts": [reference],
                "trust": "untrusted-provider-result",
            },
        )
        if result["status"] != "COMPLETED":
            raise RuntimeError(
                f"External agent {result['status']}; evidence {stored['artifact']['digest']}"
            )
        return {
            "provider_id": self._descriptor.agent_id,
            "provider_status": result["status"],
            "result": result,
            "result_artifact": "artifact://sha256/"
            + stored["artifact"]["digest"].removeprefix("sha256:"),
            "authorization_id": request.authorization_id,
            "effect_verified": False,
        }


class ExternalAgentWorkflowHandler:
    """Map an untrusted Goal/Plan step to the same durable Work and approvals.

    The trusted host fixes descriptor and Node. Models can select neither a shell
    command nor an execution environment. Resume rebuilds the exact original CAS
    input and authorization, including all available Workflow provenance.
    """

    def __init__(
        self, state_dir, descriptor: AgentDescriptor, node_id: str, *, governance
    ):
        if descriptor.validate() or not node_id:
            raise ValueError("A valid host-registered descriptor and Node are required")
        self._descriptor = AgentDescriptor.from_dict(descriptor.to_dict())
        self._node_id = node_id
        self._gate = governance
        self._broker = ApprovalBroker(governance.store)
        self._artifacts = ContentAddressedArtifactStore(Path(state_dir) / "artifacts")
        self._distributed = DistributedWorkflowAdapter(
            state_dir, work_admitter=self._admit
        )

    def _admit(self, work):
        authorization_id = work.execution_arguments["authorization_id"]
        verdict = self._gate.evaluate_operation(authorization_id)
        if verdict is GovernanceDecision.REQUIRE_APPROVAL:
            approval = self._broker.request_operation(authorization_id, gate=self._gate)
            raise GovernanceApprovalRequired(
                {
                    **DistributedWorkflowAdapter._output(work.to_dict()),
                    "approval_request_id": approval.request_id,
                    "authorization_id": authorization_id,
                    "governance_decision": verdict.value,
                }
            )
        if verdict is not GovernanceDecision.ALLOW:
            raise DistributedWorkError(f"External-agent Governance: {verdict.value}")

    def __call__(self, step, context):
        if set(step.params) - {
            "objective",
            "name",
            "work_id",
            "timeout_ms",
            "wait_timeout_seconds",
        }:
            raise ValueError("External-agent Plan contains execution configuration")
        inputs = context.get("inputs") or {}
        work_id = str(
            step.params.get("work_id") or self._distributed._work_id(step, context)
        )
        controller = self._distributed._controller()
        prior = controller.work_store.get(work_id)
        created_at = {}
        if prior:
            reference = prior.execution_arguments["input_artifact"]
            original = json.loads(
                ContentAddressedArtifactStore(self._artifacts.root)
                .resolve(
                    "sha256:" + reference.removeprefix("artifact://sha256/"),
                    verify=True,
                )
                .read_text(encoding="utf-8")
            )
            created_at = {"created_at": original["request"]["created_at"]}
        run = AgentRunRequest(
            run_id=work_id,
            task_id=work_id,
            agent_id=self._descriptor.agent_id,
            objective=str(step.params.get("objective") or step.action),
            timeout_ms=int(
                step.params.get("timeout_ms") or self._descriptor.default_timeout_ms
            ),
            **created_at,
        )
        if not 1000 <= run.timeout_ms <= self._descriptor.default_timeout_ms:
            raise ValueError("External-agent timeout exceeds its host contract")
        payload = {
            "schema": "apeir.external-agent-input/v1",
            "descriptor_digest": _digest(self._descriptor.to_dict()),
            "request": run.to_dict(),
        }
        if redact_sensitive_data(payload) != payload:
            raise ValueError("Credential material cannot enter external-agent context")
        stored = ContentAddressedArtifactStore(self._artifacts.root).store_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            artifact_type="configuration",
            name=f"{work_id}-input.json",
            produced_by=f"agent-session:{inputs.get('_agent_session_id', 'unknown')}",
            metadata={"work_id": work_id, "operation_id": work_id},
        )
        reference = "artifact://sha256/" + stored["artifact"]["digest"].removeprefix(
            "sha256:"
        )
        resource = f"agent-provider:{self._descriptor.agent_id}:{_digest(self._descriptor.to_dict())}"
        request = GovernanceRequest(
            operation_id=work_id,
            work_id=work_id,
            capability_id="agent.external.run",
            resource_id=resource,
            node_id=self._node_id,
            input_artifacts=(reference,),
            subject_id=str(inputs.get("_agent_id") or "anonymous-agent"),
            agent_session_id=str(inputs.get("_agent_session_id") or ""),
            plan_id=str(inputs.get("_plan_id") or ""),
            workflow_run_id=context["run_id"],
            capability_inputs=self._gate.capability_inputs("agent.external.run"),
        )
        authorization_id = self._gate.register_operation(request)
        delegated = WorkflowStep(
            step_id=step.step_id,
            step_type=step.step_type,
            action=step.action,
            params={
                "capability": request.capability_id,
                "work_id": work_id,
                "target_resource_id": resource,
                "input_artifacts": [reference],
                "requirements": {"node_ids": [self._node_id]},
                "arguments": {
                    "authorization_id": authorization_id,
                    "input_artifact": reference,
                },
                "wait_timeout_seconds": step.params.get("wait_timeout_seconds", 30),
            },
        )
        return self._distributed(delegated, context)


__all__ = [
    "DeviceProvider",
    "ExecutionProvider",
    "ExternalAgentOperationHandler",
    "ExternalAgentWorkflowHandler",
    "IdentityProvider",
    "IntelligenceProvider",
    "PolicyProvider",
    "SecretProvider",
]
