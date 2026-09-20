from __future__ import annotations

from nous_runtime.governance.contracts import (
    ActionProposal,
    ApprovalResponse,
    AuthorizationContext,
)
from nous_runtime.governance.gate import ExecutionAuthorizationGate
from nous_runtime.governance.lease import LeaseManager
from nous_runtime.governance.store import GovernanceStore


def test_gate_consumes_one_use_lease_and_does_not_reuse_it(tmp_path):
    store = GovernanceStore(tmp_path)
    proposal = ActionProposal(
        action_type="capability.execute",
        capability_id="tool.file_write",
        target_workspace="/workspace",
        affected_resources=("/workspace/output.txt",),
        side_effect_class="local_write",
        reversibility="reversible",
    )
    response = ApprovalResponse(
        request_id="approval_1",
        proposal_hash=proposal.proposal_hash,
        decision="APPROVED",
        approver_id="owner",
    )
    lease = LeaseManager(store).issue(
        proposal,
        response,
        subject_id="worker",
        max_uses=1,
    )
    gate = ExecutionAuthorizationGate(store=store)

    first = gate.evaluate(
        proposal,
        AuthorizationContext(
            subject_type="agent",
            subject_id="worker",
            authn_method="test",
            authn_confidence=1.0,
            request_id="execution_1",
        ),
    )
    second = gate.evaluate(
        proposal,
        AuthorizationContext(
            subject_type="agent",
            subject_id="worker",
            authn_method="test",
            authn_confidence=1.0,
            request_id="execution_2",
        ),
    )

    assert first.action_mode == "EXECUTE"
    assert first.lease_id == lease.lease_id
    assert store.get_lease(lease.lease_id)["status"] == "EXHAUSTED"
    assert second.lease_id == ""
    assert second.action_mode != "EXECUTE"


def test_gate_persists_and_audits_failsafe_decision(tmp_path):
    store = GovernanceStore(tmp_path)
    proposal = ActionProposal(
        action_type="capability.execute",
        capability_id="unknown.capability",
        side_effect_class="unknown",
    )
    decision = ExecutionAuthorizationGate(store=store).evaluate(
        proposal,
        AuthorizationContext(
            subject_type="user",
            subject_id="owner",
            authn_method="test",
            authn_confidence=1.0,
        ),
    )

    # v0.2.0: unregistered capability with unknown side effects is a
    # fail-safe (non-EXECUTE) outcome; the decision must still be
    # persisted and audited.
    assert decision.action_mode in {"DENY", "ESCALATE", "ASK_APPROVAL"}
    assert store.get_decision(decision.decision_id) is not None
    assert store.get_audit_for_decision(decision.decision_id) is not None
