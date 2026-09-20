from nous_runtime.governance.approval import ApprovalManager
from nous_runtime.governance.contracts import ActionProposal, ApprovalScope, AuthorizationContext, ApprovalResponse
from nous_runtime.governance.delegation import DelegationManager
from nous_runtime.governance.lease import LeaseManager
from nous_runtime.governance.store import GovernanceStore


def store(tmp_path):
    return GovernanceStore(tmp_path)


def proposal(**overrides):
    values = {
        "action_type": "capability.execute",
        "capability_id": "tool.file_read",
        "target_workspace": "/workspace",
        "affected_resources": ("/workspace/a.txt",),
        "side_effect_class": "read_only",
        "reversibility": "reversible",
        "created_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return ActionProposal(**values)


def context():
    return AuthorizationContext(subject_type="user", subject_id="alice", authn_method="cli_os_user", authn_confidence=0.9)


def test_approval_lifecycle_rejects_duplicate_response(tmp_path):
    mgr = ApprovalManager(store(tmp_path))
    req = mgr.create_request(proposal(), context())
    response = mgr.approve(req.request_id, "alice")
    assert response.decision == "APPROVED"
    try:
        mgr.deny(req.request_id, "alice")
    except ValueError as exc:
        assert "not PENDING" in str(exc)
    else:
        raise AssertionError("duplicate response was accepted")


def test_lease_consumption_exhaustion_restart_and_revocation(tmp_path):
    gov_store = store(tmp_path)
    prop = proposal()
    response = ApprovalResponse(request_id="req", proposal_hash=prop.proposal_hash, decision="APPROVED", approver_id="alice")
    lease_mgr = LeaseManager(gov_store)
    lease = lease_mgr.issue(prop, response, max_uses=1)

    assert lease_mgr.consume(lease.lease_id, "exec-1") == (True, 0)
    assert lease_mgr.consume(lease.lease_id, "exec-1") == (True, 0)
    assert lease_mgr.consume(lease.lease_id, "exec-2") == (False, 0)

    reopened = GovernanceStore(tmp_path)
    stored = reopened.get_lease(lease.lease_id)
    assert stored["status"] == "EXHAUSTED"
    assert reopened.consume_lease(lease.lease_id, "exec-3") == (False, 0)

    lease2 = LeaseManager(reopened).issue(prop, response, max_uses=2)
    LeaseManager(reopened).revoke(lease2.lease_id, "alice", reason="test")
    assert reopened.consume_lease(lease2.lease_id, "exec-4") == (False, 2)


def test_delegation_denies_capability_and_cost_expansion(tmp_path):
    mgr = DelegationManager(store(tmp_path))
    scope = ApprovalScope(
        capability_id="tool.file_read",
        workspace_path="/workspace",
        allowed_files=("/workspace/a.txt",),
        cost_ceiling_usd=1.0,
        allowed_side_effect_classes=("read_only",),
    )
    grant = mgr.create_grant(
        "owner",
        "delegate",
        scope,
        permitted_capabilities=("tool.file_read",),
        denied_capabilities=("tool.file_delete",),
    )
    assert mgr.validate_for_proposal(grant.grant_id, proposal(capability_id="tool.file_read", estimated_cost_usd=0.5))
    assert not mgr.validate_for_proposal(grant.grant_id, proposal(capability_id="tool.file_delete"))
    assert not mgr.validate_for_proposal(grant.grant_id, proposal(capability_id="tool.file_read", estimated_cost_usd=2.0))
