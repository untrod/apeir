"""Legacy API approvals reuse the current human boundary and durable transaction."""

import json

import pytest

from nous_runtime.api.routes import route_server
from nous_runtime.control_plane import human_sessions
from nous_runtime.governance import ActionProposal, AuthorizationContext
from nous_runtime.governance import broker as broker_module, gate as gate_module
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.permission import PermissionRule
from tests.control_plane.test_human_sessions import (
    human_env as human_env_fixture,
    login,
)

human_env = human_env_fixture


@pytest.fixture
def legacy(human_env, monkeypatch):
    gate, auth, client, _ = human_env
    broker = ApprovalBroker(gate.store)
    monkeypatch.setattr(broker_module, "_broker", broker)
    monkeypatch.setattr(gate_module, "_gate_instance", gate)
    monkeypatch.setattr(human_sessions, "_configured_auth", auth)
    auth.permissions.add(
        PermissionRule("oidc:*:alice", "control.approve_once", "device-1")
    )
    auth.permissions.add(PermissionRule("oidc:*:alice", "control.deny", "device-1"))
    proposal = ActionProposal(
        action_type="api.mutation",
        capability_id="environment.start",
        affected_resources=("device-1",),
        side_effect_class="external_write",
    )
    assert gate.store.save_proposal(proposal.to_dict())
    pending = broker.request_approval(
        run_id="original-run",
        task_id="original-task",
        proposal=proposal,
        context=AuthorizationContext(subject_type="service", subject_id="api-service"),
    )
    issued, context = login(auth, client)
    return gate, broker, auth, pending, issued, context


def request(legacy, answer, *, body=None, origin=""):
    _, _, auth, pending, issued, context = legacy
    path = f"/api/v1/approvals/{pending.request_id}/{answer}"
    body = body if body is not None else {}
    nonce = auth.nonce(context, "POST", path, body)["nonce"]
    headers = {
        "cookie": "apeir_human=" + issued.session_cookie,
        "x-control-nonce": nonce,
    }
    if origin:
        headers["origin"] = origin
    return (
        route_server("POST", path, body=body, auth={"headers": headers}),
        headers,
        path,
    )


@pytest.mark.parametrize("answer", ["approve", "deny"])
def test_service_bearer_cannot_decide_legacy_approval(legacy, monkeypatch, answer):
    gate, _, _, pending, _, _ = legacy
    monkeypatch.setenv("NOUS_API_TOKEN", "legacy.approval.fake.service.token")
    result = route_server(
        "POST",
        f"/api/v1/approvals/{pending.request_id}/{answer}",
        body={
            "approver_id": "human",
            "subject_type": "user",
            "approved": True,
        },
        auth={"token": "legacy.approval.fake.service.token", "loopback": True},
    )
    assert not result["ok"]
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert not gate.store.list_active_leases()


@pytest.mark.parametrize("answer", ["approve", "deny"])
def test_human_decision_binds_identity_audit_original_and_nonce(legacy, answer):
    gate, _, _, pending, _, context = legacy
    result, headers, path = request(
        legacy, answer, body={"approver_id": "forged-body-identity"}
    )
    assert result["ok"], result
    assert result["data"]["response"]["approver_id"] == context.subject_id
    assert not route_server(
        "POST",
        path,
        body={"approver_id": "forged-body-identity"},
        auth={"headers": headers},
    )["ok"]
    assert (
        gate.store.get_approval_request(pending.request_id)["proposal_hash"]
        == pending.proposal_hash
    )
    evidence = [
        json.loads(row["evidence_json"])
        for row in gate.store.operation_audit()
        if row["event_type"] == "approval.legacy.decision.admitted"
    ]
    assert len(evidence) == 1 and evidence[0]["human_session_id"] == context.session_id
    assert evidence[0]["run_id"] == "original-run"
    leases = gate.store.list_active_leases()
    assert len(leases) == (1 if answer == "approve" else 0)
    if leases:
        assert (
            leases[0]["subject_id"] == "api-service"
            and leases[0]["remaining_uses"] == 1
        )


@pytest.mark.parametrize("state", ["revoked", "expired"])
def test_identity_revalidation_at_atomic_decision_blocks_toctou(
    legacy, monkeypatch, state
):
    gate, _, auth, pending, _, context = legacy
    original = gate.store.resolve_approval

    def revoke_before_transaction(*args, **kwargs):
        if state == "revoked":
            auth.logout(context)
        else:
            with gate.store.operation_transaction() as db:
                db.execute("UPDATE governance_human_sessions SET expires_at=0")
        return original(*args, **kwargs)

    monkeypatch.setattr(gate.store, "resolve_approval", revoke_before_transaction)
    result, _, _ = request(legacy, "approve")
    assert not result["ok"]
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert not gate.store.list_active_leases()


def test_audit_failure_cannot_issue_legacy_grant(legacy, monkeypatch):
    gate, _, _, pending, _, _ = legacy
    original = gate.store.append_operation_audit

    def fail(db, event_type, evidence):
        if event_type == "approval.legacy.decision.admitted":
            raise OSError("deterministic audit failure")
        return original(db, event_type, evidence)

    monkeypatch.setattr(gate.store, "append_operation_audit", fail)
    result, _, _ = request(legacy, "approve")
    assert not result["ok"]
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert not gate.store.list_active_leases()


def test_untrusted_origin_cannot_consume_valid_human_nonce(legacy):
    gate, _, _, pending, _, _ = legacy
    result, _, _ = request(legacy, "approve", origin="https://evil.example.test")
    assert not result["ok"] and result["error"]["code"] == "NOUS_FORBIDDEN"
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert not gate.store.list_active_leases()


def test_missing_original_proposal_and_changed_request_fail_closed(legacy):
    gate, _, _, pending, _, _ = legacy
    with gate.store.operation_transaction() as db:
        db.execute(
            "UPDATE governance_approval_requests SET proposal_hash=? WHERE request_id=?",
            ("missing-original", pending.request_id),
        )
    result, _, _ = request(legacy, "approve")
    assert not result["ok"] and not gate.store.list_active_leases()


def test_self_declared_user_is_not_approval_authority(legacy):
    gate, broker, _, pending, _, _ = legacy
    forged = AuthorizationContext(
        subject_type="user",
        subject_id="forged-human",
        authn_method="cli_os_user",
        authn_confidence=1,
        session_locality="local",
    )
    with pytest.raises(PermissionError):
        broker.respond_legacy(pending.request_id, "approve", forged, gate=gate)
    assert not gate.store.list_active_leases()


@pytest.mark.parametrize("alteration", ["expiry", "proposal", "requester"])
def test_original_facts_revalidated_before_grant(legacy, monkeypatch, alteration):
    gate, _, _, pending, _, _ = legacy
    original = gate.store.resolve_approval

    def change_before_transaction(*args, **kwargs):
        with gate.store.operation_transaction() as db:
            if alteration == "expiry":
                db.execute(
                    "UPDATE governance_approval_requests SET expires_at='2000-01-01T00:00:00Z'"
                )
            elif alteration == "requester":
                db.execute(
                    "UPDATE governance_approval_requests SET requested_by='different-service'"
                )
            else:
                db.execute("UPDATE governance_proposals SET proposal_json='{}'")
        return original(*args, **kwargs)

    monkeypatch.setattr(gate.store, "resolve_approval", change_before_transaction)
    result, _, _ = request(legacy, "approve")
    assert not result["ok"]
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert not gate.store.list_active_leases()


def test_changed_proposal_cannot_reuse_claimed_digest(legacy):
    gate, _, _, pending, _, _ = legacy
    raw = gate.store.get_proposal(pending.proposal_hash)
    raw["affected_resources"] = ["wrong-device"]
    with gate.store.operation_transaction() as db:
        db.execute(
            "UPDATE governance_proposals SET proposal_json=?", (json.dumps(raw),)
        )
    result, _, _ = request(legacy, "approve")
    assert not result["ok"] and not gate.store.list_active_leases()


def test_persisted_parameter_digest_can_reconstruct_original_proposal():
    proposal = ActionProposal(
        action_type="api.mutation",
        capability_id="environment.create",
        params={"body": {"cpu_limit": 1, "memory_limit_mb": 256}},
    )
    persisted = proposal.to_dict()
    assert persisted["parameter_hash"]
    assert "params" not in persisted
    restored = ActionProposal.from_dict(persisted)
    assert restored._compute_hash() == proposal.proposal_hash
    assert restored.proposal_hash == proposal.proposal_hash
