# -*- coding: utf-8 -*-
"""P15 approval-expiry closure for network and other governed effects."""
from __future__ import annotations

import pytest

from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance.store import GovernanceStore


def test_expired_pending_approval_cannot_issue_authorization_lease(tmp_path):
    store = GovernanceStore(tmp_path)
    broker = ApprovalBroker(store=store)
    proposal = ActionProposal(
        action_type="network.fetch",
        capability_id="network.fetch",
        target_workspace=str(tmp_path),
        external_recipients=("example.com",),
        side_effect_class="external_write",
        reversibility="irreversible",
        retry_behavior="idempotent",
    )
    context = AuthorizationContext(
        subject_type="user",
        subject_id="owner",
        authn_method="test",
        authn_confidence=1.0,
        session_locality="local",
    )
    request = broker.request_approval(
        run_id="network-expired",
        task_id="research.fetch:expired",
        proposal=proposal,
        context=context,
        requester="owner",
        ttl_hours=-1,
    )

    with pytest.raises(ValueError, match="expired"):
        broker.approve(request.request_id, approver_id="desktop-confirmation")

    persisted = store.get_approval_request(request.request_id)
    assert persisted["status"] == "EXPIRED"
    assert store.get_active_lease_for_proposal(proposal.proposal_hash, "owner") is None

    reopened = ApprovalBroker(store=GovernanceStore(tmp_path))
    with pytest.raises(ValueError, match="not PENDING"):
        reopened.approve(request.request_id, approver_id="desktop-confirmation")
