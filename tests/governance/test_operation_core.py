"""Deterministic Operation policy, scoped leases and human authority contracts."""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from nous_runtime.capability.contract import CapabilityContract, VerificationMethod
from nous_runtime.governance import (
    ApprovalManager,
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceDecision as Decision,
    GovernanceRequest,
    GovernanceStore,
    GrantScope,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.permission import PermissionEngine, PermissionRule

pytestmark = pytest.mark.unit


@pytest.fixture
def gate(tmp_path):
    return ExecutionAuthorizationGate(GovernanceStore(tmp_path))


def request(
    gate, operation="operation-one", capability="device.firmware.update", **fields
):
    value = GovernanceRequest(
        operation_id=operation,
        work_id=operation,
        capability_id=capability,
        resource_id="device-one",
        subject_id="agent-one",
        agent_session_id="session-one",
        node_id="node-one",
        workflow_run_id="run-one",
        plan_id="plan-one",
        expected_effect={"firmware_version": "2.0.0"},
        capability_inputs=gate.capability_inputs(capability),
    )
    value = replace(value, **fields)
    gate.register_operation(value)
    return value


@pytest.mark.parametrize(
    "capability,decision",
    [
        ("device.state.read", Decision.ALLOW),
        ("device.state.set", Decision.REQUIRE_APPROVAL),
        ("device.firmware.update", Decision.REQUIRE_APPROVAL),
        ("not-registered", Decision.DENY),
    ],
)
def test_policy_never_auto_allows_a_mutation(gate, capability, decision):
    value = request(gate, capability=capability)
    assert gate.evaluate_operation(value.authorization_id) is decision


def test_critical_and_unknown_inputs_fail_closed_even_with_grant(gate):
    gate.operation_contracts.register(
        CapabilityContract(
            capability_id="critical-operation",
            risk_level="CRITICAL",
            side_effect_class="destructive",
        )
    )
    value = request(gate, capability="critical-operation")
    gate.issue_operation_grant(value.authorization_id, _build_context())
    assert gate.evaluate_operation(value.authorization_id) is Decision.DENY
    missing = request(gate, "unknown-verification")
    contract = next(
        c
        for c in gate.operation_contracts.list_all()
        if c.capability_id == missing.capability_id
    )
    contract.verification_method = VerificationMethod.NONE
    changed = request(gate, "no-verifier")
    assert gate.evaluate_operation(missing.authorization_id) is Decision.UNKNOWN
    assert gate.evaluate_operation(changed.authorization_id) is Decision.UNKNOWN


def test_explicit_read_policy_and_permission_deny_are_required(gate):
    value = request(gate, capability="device.state.read")
    gate.operation_policy.auto_approve_read_only = False
    assert gate.evaluate_operation(value.authorization_id) is Decision.REQUIRE_APPROVAL
    gate.operation_policy.auto_approve_read_only = True
    gate.permission_engine = PermissionEngine((PermissionRule("*", "*", "*", "deny"),))
    assert gate.evaluate_operation(value.authorization_id) is Decision.DENY


@pytest.mark.parametrize("scope", list(GrantScope))
def test_scope_boundaries_and_explicit_expiration(gate, scope):
    value = request(gate)
    grant = gate.issue_operation_grant(
        value.authorization_id, _build_context(), scope=scope, max_uses=1
    )
    assert grant.expires_at
    assert gate.evaluate_operation(value.authorization_id) is Decision.ALLOW
    other = request(gate, "other-operation")
    assert (gate.evaluate_operation(other.authorization_id) is Decision.ALLOW) == (
        scope
        in {
            GrantScope.SESSION,
            GrantScope.RESOURCE,
            GrantScope.CAPABILITY,
        }
    )
    other_resource = request(gate, "other-resource-operation", resource_id="device-two")
    assert (
        gate.evaluate_operation(other_resource.authorization_id) is Decision.ALLOW
    ) == (scope is GrantScope.CAPABILITY)
    other_subject = request(gate, "other-subject-operation", subject_id="another-agent")
    assert gate.evaluate_operation(other_subject.authorization_id) is not Decision.ALLOW
    other_node = request(gate, "other-node-operation", node_id="another-node")
    assert gate.evaluate_operation(other_node.authorization_id) is not Decision.ALLOW


@pytest.mark.parametrize(
    "subject_type",
    [
        "model",
        "planner",
        "scheduler",
        "node",
        "provider",
        "operation",
        "agent",
        "service",
    ],
)
def test_nonhuman_cannot_grant_approve_or_deny(gate, subject_type):
    value = request(gate)
    pending = ApprovalBroker(gate.store).request_operation(
        value.authorization_id, gate=gate
    )
    actor = replace(_build_context(), subject_type=subject_type, authn_confidence=1.0)
    broker = ApprovalBroker(gate.store)
    with pytest.raises(PermissionError):
        gate.issue_operation_grant(value.authorization_id, actor)
    with pytest.raises(PermissionError):
        broker.approve_operation_once(pending.request_id, actor, gate=gate)
    with pytest.raises(PermissionError):
        broker.deny_operation(pending.request_id, actor, gate=gate)
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert gate.store.list_active_leases() == []


def test_self_approval_and_legacy_api_bypass_are_rejected(gate):
    value = request(gate, subject_id=_build_context().subject_id)
    broker = ApprovalBroker(gate.store)
    pending = broker.request_operation(value.authorization_id, gate=gate)
    with pytest.raises(PermissionError):
        broker.approve_operation_once(pending.request_id, _build_context(), gate=gate)
    with pytest.raises(PermissionError):
        broker.approve(
            pending.request_id, approver_id="forged-human", prevent_self_approval=False
        )
    with pytest.raises(PermissionError):
        ApprovalManager(gate.store).approve(pending.request_id, "forged-human")
    with pytest.raises(PermissionError):
        broker.deny(pending.request_id, approver_id="forged-human")


def test_claims_and_api_service_token_do_not_establish_human_identity(gate):
    value = request(gate)
    for actor in (
        AuthorizationContext.from_dict(_build_context().to_dict()),
        AuthorizationContext(
            subject_type="user",
            subject_id="forged-human",
            authn_method="cli_os_user",
            authn_confidence=1.0,
        ),
        replace(_build_context(), authn_method="api_bearer_token"),
        replace(_build_context(), session_locality="remote"),
    ):
        with pytest.raises(PermissionError):
            gate.issue_operation_grant(value.authorization_id, actor)


def test_once_consumption_and_audit_survive_restart(gate, tmp_path):
    value = request(gate)
    broker = ApprovalBroker(gate.store)
    pending = broker.request_operation(value.authorization_id, gate=gate)
    broker.approve_operation_once(pending.request_id, _build_context(), gate=gate)
    with gate.admit_operation(value.authorization_id, resource_check=lambda: True):
        pass
    restored = ExecutionAuthorizationGate(GovernanceStore(tmp_path))
    with pytest.raises(PermissionError):
        with restored.admit_operation(
            value.authorization_id, resource_check=lambda: True
        ):
            pytest.fail("A consumed grant executed twice")
    events = [row["event_type"] for row in restored.store.operation_audit()]
    assert events.count("execution.admitted") == 1
    assert {"approval.requested", "approval.decided", "grant.issued"} <= set(events)
    assert restored.store.verify_audit_chain()


@pytest.mark.parametrize("resource", [False, True])
def test_revocation_cannot_be_restored_by_lease_replacement_or_restart(
    gate, tmp_path, resource
):
    value = request(gate)
    grant = gate.issue_operation_grant(value.authorization_id, _build_context())
    gate.revoke_operation_authority(
        value.authorization_id,
        _build_context(),
        grant_id=grant.lease_id,
        resource=resource,
    )
    # Legacy mutable storage must not resurrect an Operation grant.
    gate.store.save_lease(grant.to_dict())
    restored = ExecutionAuthorizationGate(GovernanceStore(tmp_path))
    assert restored.evaluate_operation(value.authorization_id) is not Decision.ALLOW
    with pytest.raises(PermissionError):
        with restored.admit_operation(
            value.authorization_id, resource_check=lambda: True
        ):
            pytest.fail("Revoked authority reached execution")


def test_expiration_and_resource_toctou_are_revalidated_at_admission(gate):
    value = request(gate)
    grant = gate.issue_operation_grant(value.authorization_id, _build_context())
    assert gate.evaluate_operation(value.authorization_id) is Decision.ALLOW
    with gate.store.operation_transaction() as db:
        db.execute(
            "UPDATE governance_leases SET expires_at='2000-01-01T00:00:00Z' WHERE lease_id=?",
            (grant.lease_id,),
        )
    with pytest.raises(PermissionError):
        with gate.admit_operation(value.authorization_id, resource_check=lambda: True):
            pytest.fail("Expired grant admitted")
    second = request(gate, "resource-race")
    gate.issue_operation_grant(second.authorization_id, _build_context())
    checks = iter((True, False))
    with pytest.raises(PermissionError, match="changed immediately"):
        with gate.admit_operation(
            second.authorization_id, resource_check=lambda: next(checks)
        ):
            pytest.fail("Changed resource admitted")


def test_append_audit_serializes_multiple_store_instances(gate, tmp_path):
    value = request(gate)

    def append(index):
        other = ExecutionAuthorizationGate(GovernanceStore(tmp_path))
        other.record_operation_evidence(
            value.authorization_id, "contract.observed", sample=index
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(12)))
    rows = gate.store.operation_audit()
    assert len(rows) == 12
    assert gate.store.verify_audit_chain()
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        assert evidence["work_id"] == value.work_id
        assert evidence["agent_session_id"] == value.agent_session_id
        assert evidence["authorization_id"] == value.authorization_id


def test_audit_failure_and_binding_tampering_fail_closed(gate, monkeypatch):
    value = request(gate)
    with pytest.raises(PermissionError, match="binding changed"):
        gate.register_operation(
            replace(value, expected_effect={"firmware_version": "3.0.0"})
        )
    with gate.store.operation_transaction() as db:
        db.execute(
            "UPDATE governance_operations SET request_json=? WHERE authorization_id=?",
            (
                json.dumps(replace(value, resource_id="another-device").to_dict()),
                value.authorization_id,
            ),
        )
    assert gate.evaluate_operation(value.authorization_id) is Decision.UNKNOWN
    read = request(gate, "audit-failure", "device.state.read")

    def fail(*args):
        raise OSError("Injected audit persistence failure")

    monkeypatch.setattr(gate.store, "append_operation_audit", fail)
    assert gate.evaluate_operation(read.authorization_id) is Decision.UNKNOWN
    with pytest.raises(OSError):
        with gate.admit_operation(read.authorization_id, resource_check=lambda: True):
            pytest.fail("Missing audit admitted execution")


def test_new_grant_cannot_readmit_an_operation_with_persisted_consumption(gate):
    value = request(gate)
    gate.issue_operation_grant(value.authorization_id, _build_context())
    with gate.admit_operation(value.authorization_id, resource_check=lambda: True):
        pass
    gate.issue_operation_grant(
        value.authorization_id, _build_context(), scope=GrantScope.RESOURCE, max_uses=2
    )
    with pytest.raises(PermissionError, match="cannot execute again"):
        with gate.admit_operation(value.authorization_id, resource_check=lambda: True):
            pytest.fail("Fresh authority must not license effect replay")


def test_plaintext_credentials_cannot_enter_governance_records(gate):
    with pytest.raises(ValueError, match="Credential"):
        request(gate, expected_effect={"api_key": "plaintext-value"})
    assert gate.store.operation_audit() == []


@pytest.mark.parametrize("action,status", [("approve", "APPROVED"), ("deny", "DENIED")])
def test_existing_cli_exposes_only_once_and_deny_for_agent_operation(
    gate, monkeypatch, action, status
):
    from typer.testing import CliRunner
    from nous_runtime.governance import cli

    value = request(gate)
    pending = ApprovalBroker(gate.store).request_operation(
        value.authorization_id, gate=gate
    )
    monkeypatch.setattr(cli, "ApprovalManager", lambda: ApprovalManager(gate.store))
    runner = CliRunner()
    listed = runner.invoke(cli.approval_app, ["list", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["pending"][0]["request_id"] == pending.request_id
    result = runner.invoke(cli.approval_app, [action, pending.request_id])
    assert result.exit_code == 0, result.output
    assert gate.store.get_approval_request(pending.request_id)["status"] == status
    if action == "approve":
        grants = gate.store.list_active_leases(value.subject_id)
        assert len(grants) == 1
        assert grants[0]["scope_kind"] == "ONCE"
        assert grants[0]["max_uses"] == 1
