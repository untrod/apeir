"""External harnesses stay behind canonical Governance and Node journals."""

import json
import shlex
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.agents.external.models import AgentDescriptor, AgentRunRequest
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    RetryStrategy,
    VerificationMethod,
)
from nous_runtime.core.redaction import register_sensitive_value
from nous_runtime.environments.providers import ProviderExecutionResult
from nous_runtime.governance import (
    ExecutionAuthorizationGate,
    GovernanceStore,
    GovernanceRequest,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.operation_contracts import GovernanceDecision
from nous_runtime.node_runtime.service import (
    NodeRuntimeConfig,
    NodeRuntimeService,
    WorkloadResponseLost,
)
from nous_runtime.provider.interoperability import ExternalAgentOperationHandler

pytestmark = pytest.mark.unit


def setup_agent(root, runner, *, policy=None):
    gate = ExecutionAuthorizationGate(
        GovernanceStore(root / "governance"), operation_policy_provider=policy
    )
    gate.operation_contracts.register(
        CapabilityContract(
            capability_id="agent.external.run",
            name="External agent",
            risk_level="HIGH",
            side_effect_class="local_write",
            idempotency=Idempotency.NOT_IDEMPOTENT,
            retry_strategy=RetryStrategy.NONE,
            verification_method=VerificationMethod.DIFF_CHECK,
            observation_method="workspace.digest",
            max_retries=0,
        )
    ).unwrap()
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    descriptor = AgentDescriptor(
        agent_id="reference-agent",
        executable_reference=shlex.quote(sys.executable),
        default_timeout_ms=5000,
    )
    artifacts = ContentAddressedArtifactStore(root / "node" / "artifacts")
    handler = ExternalAgentOperationHandler(
        descriptor,
        workspace,
        artifacts,
        governance=gate,
        execution_runner=runner,
    )
    node = NodeRuntimeService(
        NodeRuntimeConfig(root / "node"),
        capability_handlers={
            handler.capability_id: handler,
        },
    )
    run = AgentRunRequest(
        run_id="work-external",
        task_id="work-external",
        agent_id=descriptor.agent_id,
        objective="Propose an upgrade; output is not authority",
        timeout_ms=5000,
        approval_policy="always_allow",
    )
    payload = {
        "schema": "apeir.external-agent-input/v1",
        "descriptor_digest": handler.discover()["descriptor_digest"],
        "request": run.to_dict(),
    }
    stored = artifacts.store_bytes(
        json.dumps(payload).encode(), artifact_type="configuration", name="input.json"
    )
    reference = "artifact://sha256/" + stored["artifact"]["digest"].removeprefix(
        "sha256:"
    )
    request = GovernanceRequest(
        work_id=run.run_id,
        operation_id=run.run_id,
        subject_id="external-session-agent",
        capability_id=handler.capability_id,
        resource_id=handler.resource_id,
        node_id=node.identity.node_id,
        input_artifacts=(reference,),
        agent_session_id="session-external",
        plan_id="plan-external",
        workflow_run_id="run-external",
        capability_inputs=gate.capability_inputs(handler.capability_id),
    )
    gate.register_operation(request)
    arguments = {
        "authorization_id": request.authorization_id,
        "input_artifact": reference,
    }
    binding = {
        name: "bound"
        for name in (
            "intent_id",
            "effect_contract_digest",
            "target_binding_digest",
            "workload_id",
            "request_digest",
            "provider_revision",
        )
    }
    binding["target_ref"] = (
        f"resource://{handler.resource_id}/capability/{handler.capability_id}"
    )
    return SimpleNamespace(
        gate=gate,
        handler=handler,
        node=node,
        request=request,
        arguments=arguments,
        binding=binding,
        payload=payload,
        artifacts=artifacts,
    )


def approve(fixture):
    broker = ApprovalBroker(fixture.gate.store)
    approval = broker.request_operation(
        fixture.request.authorization_id, gate=fixture.gate
    )
    return broker.approve_operation_once(
        approval.request_id, _build_context(), gate=fixture.gate
    )


def execute(fixture, **kwargs):
    return fixture.node.execute_workload(
        fixture.request.operation_id,
        fixture.handler.capability_id,
        fixture.arguments,
        binding=fixture.binding,
        delivery_semantics="at_most_once",
        **kwargs,
    )


@pytest.mark.parametrize(
    "verdict",
    [
        GovernanceDecision.ALLOW,
        GovernanceDecision.DENY,
        GovernanceDecision.UNKNOWN,
        GovernanceDecision.REQUIRE_APPROVAL,
        "ALLOW",
        None,
    ],
)
def test_policy_provider_never_grants_authority(tmp_path, verdict):
    policy = SimpleNamespace(evaluate=lambda request: verdict)
    fixture = setup_agent(
        tmp_path, lambda *args: pytest.fail("unauthorized execution"), policy=policy
    )
    actual = fixture.gate.evaluate_operation(fixture.request.authorization_id)
    expected = (
        GovernanceDecision.REQUIRE_APPROVAL
        if verdict
        in {
            GovernanceDecision.ALLOW,
            GovernanceDecision.REQUIRE_APPROVAL,
        }
        and isinstance(verdict, GovernanceDecision)
        else verdict
        if isinstance(verdict, GovernanceDecision)
        else GovernanceDecision.UNKNOWN
    )
    assert actual is expected
    assert actual is not GovernanceDecision.ALLOW


def test_policy_exception_fails_closed(tmp_path):
    def unavailable(request):
        raise ConnectionError("policy unavailable")

    fixture = setup_agent(tmp_path, None, policy=SimpleNamespace(evaluate=unavailable))
    assert (
        fixture.gate.evaluate_operation(fixture.request.authorization_id)
        is GovernanceDecision.UNKNOWN
    )


def test_policy_receives_detached_inputs_and_cannot_rewrite_core(tmp_path):
    def policy(request):
        request.capability_inputs["risk"] = "LOW"
        request.capability_inputs["side_effect_class"] = "read_only"
        return GovernanceDecision.ALLOW

    fixture = setup_agent(tmp_path, None, policy=SimpleNamespace(evaluate=policy))
    assert (
        fixture.gate.evaluate_operation(fixture.request.authorization_id)
        is GovernanceDecision.REQUIRE_APPROVAL
    )
    persisted = fixture.gate.get_operation_request(fixture.request.authorization_id)
    assert persisted.capability_inputs["risk"] == "HIGH"
    assert persisted.capability_inputs["side_effect_class"] == "local_write"


@pytest.mark.parametrize("risk", ["CRITICAL", "undeclared"])
def test_external_allow_cannot_override_core_denial(tmp_path, risk):
    fixture = setup_agent(
        tmp_path,
        None,
        policy=SimpleNamespace(evaluate=lambda request: GovernanceDecision.ALLOW),
    )
    contract = next(
        c
        for c in fixture.gate.operation_contracts.list_all()
        if c.capability_id == fixture.handler.capability_id
    )
    fixture.gate.operation_contracts.register(
        replace(contract, risk_level=risk)
    ).unwrap()
    # Core rejects changed/unsafe facts even if an external engine says ALLOW.
    assert fixture.gate.evaluate_operation(fixture.request.authorization_id) in {
        GovernanceDecision.DENY,
        GovernanceDecision.UNKNOWN,
    }


@pytest.mark.parametrize("subject", ["agent", "node", "provider", "scheduler"])
def test_external_provider_cannot_approve_itself(tmp_path, subject):
    fixture = setup_agent(tmp_path, lambda *args: pytest.fail("self-authorized"))
    broker = ApprovalBroker(fixture.gate.store)
    approval = broker.request_operation(
        fixture.request.authorization_id, gate=fixture.gate
    )
    with pytest.raises(PermissionError):
        broker.approve_operation_once(
            approval.request_id,
            AuthorizationContext(
                subject_type=subject,
                subject_id=fixture.request.subject_id,
                authn_confidence=1.0,
            ),
            gate=fixture.gate,
        )
    assert execute(fixture)["state"] == "FAILED"


def test_direct_calls_and_idempotent_delivery_are_rejected(tmp_path):
    fixture = setup_agent(tmp_path, lambda *args: pytest.fail("bypass"))
    approve(fixture)
    with pytest.raises(PermissionError):
        fixture.handler(fixture.arguments)
    with pytest.raises(PermissionError):
        fixture.node.execute_workload(
            "work-external",
            fixture.handler.capability_id,
            fixture.arguments,
            binding=fixture.binding,
        )


def test_approved_run_uses_original_input_and_redacts_result(tmp_path):
    fake_material = "apeir-m4-deterministic-fake-sensitive-material-381927"
    register_sensitive_value(fake_material)
    calls = []

    def runner(command, env, cwd, timeout):
        calls.append(json.loads(open(command[-1], encoding="utf-8").read()))
        assert fake_material not in json.dumps(calls[-1])
        assert not any("token" in key.lower() for key in env)
        return ProviderExecutionResult(
            True, 0, stdout=fake_material, stderr=fake_material
        )

    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    result = execute(fixture)
    assert result["state"] == "COMPLETED"
    assert not result["output"]["effect_verified"]
    assert calls[0]["objective"] == fixture.payload["request"]["objective"]
    assert fake_material not in json.dumps(result)
    assert len(calls) == 1
    assert execute(fixture) == result
    assert len(calls) == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert fake_material.encode() not in path.read_bytes()


@pytest.mark.parametrize("change", ["node", "target", "artifact", "extra", "context"])
def test_execution_binding_mismatch_fails_closed(tmp_path, change):
    fixture = setup_agent(tmp_path, lambda *args: pytest.fail("unbound execution"))
    approve(fixture)
    if change == "target":
        fixture.binding["target_ref"] = "resource://wrong"
    elif change == "extra":
        fixture.arguments["executable"] = "other-agent"
    elif change == "artifact":
        fixture.arguments["input_artifact"] = "artifact://sha256/" + "0" * 64
    elif change == "node":
        fixture.node._handlers[fixture.handler.capability_id] = (
            ExternalAgentOperationHandler(
                replace(fixture.handler._descriptor, version="2"),
                tmp_path / "workspace",
                fixture.artifacts,
                governance=fixture.gate,
                execution_runner=lambda *args: pytest.fail("different descriptor"),
            )
        )
    else:
        with pytest.raises(PermissionError):
            fixture.handler.execute_bound(
                fixture.arguments,
                workload_id="work-external",
                node_id=fixture.node.identity.node_id,
                binding=fixture.binding,
                authorization_context=AuthorizationContext(
                    subject_type="node", subject_id=fixture.node.identity.node_id
                ),
            )
        return
    assert execute(fixture)["state"] == "FAILED"


def test_policy_is_rechecked_immediately_before_spawn(tmp_path, monkeypatch):
    policy = SimpleNamespace(evaluate=lambda request: GovernanceDecision.ALLOW)
    fixture = setup_agent(
        tmp_path, lambda *args: pytest.fail("revoked policy"), policy=policy
    )
    approve(fixture)
    from nous_runtime.agents.adapters.supervisor import ProcessSupervisor

    original = ProcessSupervisor._build_command

    def build(*args, **kwargs):
        value = original(*args, **kwargs)
        policy.evaluate = lambda request: GovernanceDecision.DENY
        return value

    monkeypatch.setattr(ProcessSupervisor, "_build_command", build)
    assert execute(fixture)["state"] == "FAILED"
    assert (
        fixture.node.execute_workload(
            "work-external",
            fixture.handler.capability_id,
            fixture.arguments,
            binding=fixture.binding,
            delivery_semantics="at_most_once",
        )["state"]
        == "FAILED"
    )


def test_lost_response_is_reconciled_from_node_journal_without_rerun(tmp_path):
    calls = []

    def runner(*args):
        calls.append("effect")
        raise WorkloadResponseLost(
            "response lost", output={"provider_status": "COMPLETED"}, completed=True
        )

    fixture = setup_agent(tmp_path, runner)
    approve(fixture)
    with pytest.raises(WorkloadResponseLost):
        execute(fixture)
    restored = NodeRuntimeService(
        NodeRuntimeConfig(tmp_path / "node"),
        capability_handlers={
            fixture.handler.capability_id: fixture.handler,
        },
    )
    fixture.node = restored
    reconciled = execute(fixture)
    assert reconciled["state"] == "COMPLETED"
    assert reconciled["error_code"] == "NOUS_NODE_RESPONSE_LOST"
    assert calls == ["effect"]


def test_missing_isolated_runner_has_no_host_process_fallback(tmp_path):
    fixture = setup_agent(tmp_path, None)
    approve(fixture)
    assert fixture.handler.health()["state"] == "unavailable"
    assert execute(fixture)["state"] == "FAILED"
