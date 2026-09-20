# -*- coding: utf-8 -*-
"""Tests for unified ApprovalBroker."""

import tempfile
import threading

import pytest

from nous_runtime.governance.broker import (
    ApprovalBroker,
    ApprovalPolicy,
    ApprovalEvidence,
)
from nous_runtime.governance.contracts import (
    ActionProposal,
    AuthorizationContext,
)


@pytest.fixture
def broker():
    """Create a broker with a temporary store."""
    with tempfile.TemporaryDirectory() as d:
        from nous_runtime.governance.store import GovernanceStore
        yield ApprovalBroker(store=GovernanceStore(d))


@pytest.fixture
def proposal():
    return ActionProposal(
        action_type="capability.execute",
        capability_id="file.write",
        target_workspace="/tmp/test",
        side_effect_class="local_write",
        reversibility="reversible",
    )


@pytest.fixture
def context():
    return AuthorizationContext(
        subject_type="user",
        subject_id="user_test",
        authn_method="cli_os_user",
        authn_confidence=0.9,
        session_locality="local",
    )


class TestApprovalPolicy:
    def test_default_allows_low(self):
        """Default policy auto-approves low-risk (max_auto_approve_risk='low')."""
        policy = ApprovalPolicy(agent_id="agent.test")
        assert policy.evaluate("low", True, False) == "allow"

    def test_default_asks_high(self):
        """Default policy requires approval for high-risk."""
        policy = ApprovalPolicy(agent_id="agent.test")
        assert policy.evaluate("high", False, False) == "ask"

    def test_always_allow(self):
        policy = ApprovalPolicy(agent_id="agent.test", scope="always_allow")
        assert policy.evaluate("high", False, False) == "allow"
        assert policy.evaluate("critical", False, False) == "ask"

    def test_auto_approve_read_only(self):
        policy = ApprovalPolicy(
            agent_id="agent.test",
            scope="policy_controlled",
            auto_approve_read_only=True,
        )
        assert policy.evaluate("high", True, False) == "allow"
        assert policy.evaluate("high", False, False) == "ask"

    def test_auto_approve_tests(self):
        policy = ApprovalPolicy(
            agent_id="agent.test",
            scope="policy_controlled",
            auto_approve_tests=True,
        )
        assert policy.evaluate("high", False, True) == "allow"

    def test_max_auto_approve_risk_medium(self):
        policy = ApprovalPolicy(agent_id="agent.test", max_auto_approve_risk="medium")
        assert policy.evaluate("low", False, False) == "allow"
        assert policy.evaluate("medium", False, False) == "allow"
        assert policy.evaluate("high", False, False) == "ask"


class TestApprovalBroker:
    def test_request_approval(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            requester="user_test",
        )
        assert req.request_id.startswith("apr_")
        assert req.status == "PENDING"

    def test_approve_pending(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            requester="user_test",
        )
        resp = broker.approve(
            req.request_id,
            approver_id="admin",
            reason="Looks safe",
        )
        assert resp.decision == "APPROVED"

    def test_approve_pending_atomically_issues_subject_bound_one_use_lease(
        self, broker, proposal, context
    ):
        req = broker.request_approval(
            run_id="run_lease",
            task_id="task_lease",
            proposal=proposal,
            context=context,
            requester=context.subject_id,
        )

        broker.approve(req.request_id, approver_id="admin", reason="Reviewed")
        lease = broker._store.get_active_lease_for_proposal(
            proposal.proposal_hash,
            context.subject_id,
        )

        assert lease is not None
        assert lease["approval_id"]
        assert lease["remaining_uses"] == 1
        assert lease["scope"]["proposal_hash"] == proposal.proposal_hash
    def test_deny_pending(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            requester="user_test",
        )
        resp = broker.deny(req.request_id, approver_id="admin", reason="Too risky")
        assert resp.decision == "DENIED"

    def test_cannot_self_approve(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            requester="agent.test",
        )
        resp = broker.approve(req.request_id, approver_id="agent.test")
        assert resp.decision == "DENIED"
        assert "self-approval" in resp.reason.lower()

    def test_approving_non_pending_raises(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
        )
        broker.approve(req.request_id, approver_id="admin")
        with pytest.raises(ValueError):
            broker.approve(req.request_id, approver_id="admin")

    def test_get_pending(self, broker, proposal, context):
        broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            requester="user_test",
        )
        pending = broker.get_pending()
        assert len(pending) >= 1

    def test_expire_old(self, broker, proposal, context):
        broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
            ttl_hours=-1,
        )
        assert broker.expire_old() == 1

    def test_set_and_get_policy(self, broker):
        policy = ApprovalPolicy(
            agent_id="agent.test",
            capability_id="file.write",
            scope="always_ask",
        )
        broker.set_policy(policy)
        retrieved = broker.get_policy("agent.test", "file.write")
        assert retrieved is not None
        assert retrieved.scope == "always_ask"

    def test_should_auto_approve(self, broker):
        policy = ApprovalPolicy(
            agent_id="agent.test",
            capability_id="file.read",
            scope="always_allow",
        )
        broker.set_policy(policy)
        assert broker.should_auto_approve("agent.test", "file.read", "low", True, False) is True

    def test_event_listener(self, broker, proposal, context):
        events = []

        def listener(event_type, data):
            events.append((event_type, data))

        broker.register_listener(listener)
        broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
        )
        assert any(e[0] == "approval.requested" for e in events)


class TestApprovalEvidence:
    def test_create(self):
        evidence = ApprovalEvidence(
            command_preview="pip install pytest",
            affected_files=("requirements.txt",),
            workspace_path="/tmp/ws",
            capability_request="package.install",
        )
        d = evidence.to_dict()
        assert d["command_preview"] == "pip install pytest"
        assert d["affected_files"] == ["requirements.txt"]

    def test_roundtrip(self):
        evidence = ApprovalEvidence(
            command_preview="rm -rf build/",
            affected_files=("build/",),
            risk_envelope={"level": "high"},
        )
        d = evidence.to_dict()
        restored = ApprovalEvidence.from_dict(d)
        assert restored.command_preview == evidence.command_preview
        assert restored.risk_envelope == {"level": "high"}


class TestApprovalConcurrency:
    def test_concurrent_approve_deny(self, broker, proposal, context):
        """Two threads racing to approve/deny produce exactly one terminal state."""
        req = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
        )

        results = []
        errors = []
        barrier = threading.Barrier(2, timeout=10)

        def approve():
            try:
                barrier.wait()
                resp = broker.approve(req.request_id, approver_id="admin1")
                results.append(resp.decision)
            except Exception as exc:
                errors.append(exc)

        def deny():
            try:
                barrier.wait()
                resp = broker.deny(req.request_id, approver_id="admin2", reason="No")
                results.append(resp.decision)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=approve)
        t2 = threading.Thread(target=deny)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not t1.is_alive(), "Thread 1 should have completed"
        assert not t2.is_alive(), "Thread 2 should have completed"
        assert len(results) == 1
        assert len(errors) == 1
        assert results[0] in {"APPROVED", "DENIED"}
        assert "PENDING" in str(errors[0])

        stored = broker._store.get_approval_request(req.request_id)
        assert stored is not None
        assert stored["status"] == results[0]

    def test_deny_after_approval_is_rejected(self, broker, proposal, context):
        req = broker.request_approval(
            run_id="run_1", task_id="task_1", proposal=proposal, context=context
        )
        broker.approve(req.request_id, approver_id="admin1")
        with pytest.raises(ValueError, match="not PENDING"):
            broker.deny(req.request_id, approver_id="admin2")

    def test_pending_request_retains_run_linkage(self, broker, proposal, context):
        broker.request_approval(
            run_id="run_1", task_id="task_1", proposal=proposal, context=context
        )
        pending = broker.get_pending_for_run("run_1")
        assert len(pending) == 1
        assert pending[0]["task_id"] == "task_1"


class TestApprovalReplay:
    def test_cannot_reuse_approval(self, broker, proposal, context):
        """An approval should not be reusable after it's been granted."""
        req1 = broker.request_approval(
            run_id="run_1",
            task_id="task_1",
            proposal=proposal,
            context=context,
        )
        broker.approve(req1.request_id, approver_id="admin")

        # Same proposal, new run
        req2 = broker.request_approval(
            run_id="run_2",
            task_id="task_2",
            proposal=proposal,
            context=context,
        )
        # Should be a new request with its own ID
        assert req2.request_id != req1.request_id
