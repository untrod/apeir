from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
    AuthorizationEvidenceBundle,
)
from nous_runtime.governance.enterprise import (
    EnterprisePolicyInterface,
    OrganizationMembership,
)
from nous_runtime.governance.store import GovernanceStore


class Decision:
    action_mode = "EXECUTE"
    reason_code = "TEST_EXECUTE"

    def to_dict(self):
        return {"action_mode": self.action_mode, "reason_code": self.reason_code}


class Gate:
    def __init__(self):
        self.calls = []

    def evaluate(self, proposal, context):
        self.calls.append((proposal, context))
        return Decision()


class AuditStore:
    def __init__(self, ok=True):
        self.ok = ok
        self.records = []

    def save_audit(self, record):
        self.records.append(record)
        return self.ok


def context(*, confidence=0.9, locality="remote"):
    return AuthorizationContext(
        subject_type="user",
        subject_id="alice",
        authn_method="api_bearer_token",
        authn_confidence=confidence,
        session_locality=locality,
    )


def membership(role="developer", workspaces=("workspace-a",)):
    return OrganizationMembership("org-a", "alice", (role,), workspaces)


def interface(member=None, *, audit_ok=True):
    gate = Gate()
    store = AuditStore(audit_ok)
    policy = EnterprisePolicyInterface(
        lambda subject_id: member if subject_id == "alice" else None,
        gate=gate,
        store=store,
    )
    return policy, gate, store


def test_viewer_read_is_scoped_and_write_is_denied_before_governance():
    policy, gate, store = interface(membership("viewer"))
    read = policy.evaluate(
        ActionProposal(
            action_type="runtime.inspect",
            target_workspace="workspace-a",
            side_effect_class="read_only",
        ),
        context(),
    )
    assert read.allowed is True
    assert len(gate.calls) == 1
    write = policy.evaluate(
        ActionProposal(
            action_type="workspace.update",
            target_workspace="workspace-a",
            side_effect_class="local_write",
        ),
        context(),
    )
    assert write.allowed is False
    assert write.reason_code == "ENTERPRISE_RBAC_DENIED"
    assert len(gate.calls) == 1
    assert len(store.records) == 2


def test_developer_capability_and_external_write_retain_approval_requirement():
    policy, gate, _ = interface(membership("developer"))
    result = policy.evaluate(
        ActionProposal(
            action_type="connector.execute",
            capability_id="connector.crm.write",
            target_workspace="workspace-a",
            side_effect_class="external_write",
        ),
        context(),
    )
    assert result.allowed is True
    assert result.requires_approval is True
    assert len(gate.calls) == 1


def test_cross_workspace_low_confidence_and_missing_membership_fail_closed():
    policy, gate, _ = interface(membership("developer"))
    cross_scope = policy.evaluate(
        ActionProposal(
            action_type="workspace.update",
            target_workspace="workspace-b",
            side_effect_class="local_write",
        ),
        context(),
    )
    assert cross_scope.reason_code == "ENTERPRISE_WORKSPACE_DENIED"
    low_auth = policy.evaluate(
        ActionProposal(action_type="runtime.inspect", side_effect_class="read_only"),
        context(confidence=0.6),
    )
    assert low_auth.reason_code == "ENTERPRISE_AUTHN_INSUFFICIENT"
    missing, _, _ = interface(None)
    denied = missing.evaluate(
        ActionProposal(action_type="runtime.inspect", side_effect_class="read_only"),
        context(),
    )
    assert denied.reason_code == "ENTERPRISE_MEMBERSHIP_DENIED"
    assert gate.calls == []


def test_approver_and_policy_description_use_explicit_authorities():
    policy, gate, _ = interface(membership("approver", ("*",)))
    result = policy.evaluate(
        ActionProposal(action_type="approval.decide", side_effect_class="read_only"),
        context(),
    )
    assert result.allowed is True
    description = policy.describe_policy()
    assert description["default"] == "deny"
    assert "approval.decide" in description["roles"]["approver"]
    assert description["approval_authority"] == "ApprovalBroker"
    assert len(gate.calls) == 1


def test_audit_unavailable_blocks_governance_execution():
    policy, gate, _ = interface(membership("viewer"), audit_ok=False)
    result = policy.evaluate(
        ActionProposal(action_type="runtime.inspect", side_effect_class="read_only"),
        context(),
    )
    assert result.reason_code == "ENTERPRISE_AUDIT_UNAVAILABLE"
    assert gate.calls == []


def test_governance_audit_chain_uses_content_hashes_and_detects_tampering(tmp_path):
    store = GovernanceStore(tmp_path)
    for index in range(2):
        bundle = AuthorizationEvidenceBundle(
            decision_id=f"decision-{index}",
            proposal_hash=f"proposal-{index}",
            evidence={"index": index},
        )
        assert store.save_audit(bundle.to_dict()) is True
    assert store.verify_audit_chain() is True
    with closing(sqlite3.connect(store.db_path)) as connection:
        connection.execute(
            "UPDATE governance_audit SET evidence_json = ? WHERE decision_id = ?",
            ('{"tampered": true}', "decision-0"),
        )
        connection.commit()
    assert store.verify_audit_chain() is False


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError, match="unknown enterprise roles"):
        membership("superuser")
