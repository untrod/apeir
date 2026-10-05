"""Cryptographic fake-IdP contracts for the trusted human boundary."""

import base64
import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nous_runtime.control_plane.human_sessions import (
    HumanSessionAuth,
    OIDCHumanIdentityProvider,
    is_human_session_context,
)
from nous_runtime.governance import (
    ExecutionAuthorizationGate,
    GovernanceStore,
    GovernanceRequest,
    AuthorizationContext,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.permission import PermissionEngine, PermissionRule

pytestmark = pytest.mark.unit
VERIFIER = "m35.fake.pkce.verifier." + "x" * 64
CODE = "m35.fake.authorization.code.not-a-production-credential"
ISSUER = "https://identity.example.test"


@pytest.fixture
def human_env(tmp_path):
    key = Ed25519PrivateKey.from_private_bytes(b"t" * 32)
    client = SimpleNamespace(claims={}, calls=0)

    def exchange(*args, **kwargs):
        assert kwargs["code_verifier"] == VERIFIER
        assert kwargs["code"] == CODE
        client.calls += 1
        return {"id_token": jwt.encode(client.claims, key, algorithm="EdDSA")}

    client.fetch_token = exchange
    provider = OIDCHumanIdentityProvider(
        {
            "issuer": ISSUER,
            "client_id": "apeir-operations",
            "redirect_uri": "https://console.example.test/auth/callback",
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token",
            "jwks_uri": ISSUER + "/keys",
            "subjects": ["alice"],
        },
        jwk_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda assertion: SimpleNamespace(
                key=key.public_key()
            )
        ),
        oauth_client=client,
    )
    gate = ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance"))
    policy = PermissionEngine(
        (PermissionRule("oidc:*:alice", "governance.approve", "device-1"),)
    )
    auth = HumanSessionAuth(gate.store, provider, permissions=policy)
    return gate, auth, client, key


def challenge(auth, client):
    pkce = (
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
        .decode()
        .rstrip("=")
    )
    issued = auth.challenge(pkce)
    params = parse_qs(urlsplit(issued["authorization_url"]).query)
    now = int(time.time())
    client.claims = {
        "iss": ISSUER,
        "sub": "alice",
        "aud": "apeir-operations",
        "iat": now,
        "exp": now + 600,
        "auth_time": now,
        "amr": ["mfa"],
        "nonce": params["nonce"][0],
    }
    return issued["challenge_id"]


def login(auth, client):
    issued = auth.login(challenge(auth, client), CODE, VERIFIER)
    return issued, auth.authenticate(issued.session_cookie)


def operation(gate, *, resource="device-1", subject="agent-1"):
    request = GovernanceRequest(
        operation_id="firmware-work",
        work_id="firmware-work",
        node_id="node-1",
        resource_id=resource,
        subject_id=subject,
        capability_id="device.firmware.update",
        capability_inputs=gate.capability_inputs("device.firmware.update"),
    )
    gate.register_operation(request)
    return request, ApprovalBroker(gate.store).request_operation(
        request.authorization_id, gate=gate
    )


def test_verified_remote_human_approves_exact_operation_through_existing_authority(
    human_env,
):
    gate, auth, client, _ = human_env
    issued, context = login(auth, client)
    request, pending = operation(gate)
    original = request.authorization_id
    response = ApprovalBroker(gate.store).respond_operation(
        pending.request_id, "approve", context, gate=gate
    )
    assert response.approver_id == context.subject_id
    assert response.approver_method == "oidc_pkce"
    assert gate.get_operation_request(original) == request
    assert is_human_session_context(context, gate.store)
    assert issued.session_cookie not in json.dumps(issued)
    audit = json.dumps(gate.store.operation_audit())
    assert context.subject_id in audit and context.context_id in audit
    assert (
        issued.session_cookie not in audit
        and CODE not in audit
        and VERIFIER not in audit
    )
    for path in __import__("pathlib").Path(gate.store.db_path).parent.rglob("*"):
        if path.is_file():
            assert issued.session_cookie.encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://untrusted.example.test"},
        {"aud": "other-client"},
        {"sub": "model-1"},
        {"amr": ["pwd"]},
        {"nonce": "unbound-nonce"},
        {"exp": 1},
        {"auth_time": 1},
        {"auth_time": time.time() + 3600},
        {"azp": "other-client"},
        {"amr": "mfa"},
    ],
)
def test_identity_claims_fail_closed(human_env, changes):
    _, auth, client, _ = human_env
    cid = challenge(auth, client)
    client.claims.update(changes)
    with pytest.raises(PermissionError, match="authentication failed"):
        auth.login(cid, CODE, VERIFIER)
    with auth.store.operation_transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM governance_human_sessions").fetchone()[0]
            == 0
        )


def test_untrusted_signing_key_cannot_create_human_session(human_env):
    _, auth, client, _ = human_env
    cid = challenge(auth, client)
    attacker = Ed25519PrivateKey.from_private_bytes(b"u" * 32)
    client.fetch_token = lambda *args, **kwargs: {
        "id_token": jwt.encode(client.claims, attacker, algorithm="EdDSA")
    }
    with pytest.raises(PermissionError):
        auth.login(cid, CODE, VERIFIER)


@pytest.mark.parametrize("mode", ["wrong_verifier", "expired", "replay"])
def test_pkce_and_durable_login_replay_protection(human_env, mode):
    _, auth, client, _ = human_env
    cid = challenge(auth, client)
    verifier = VERIFIER
    if mode == "wrong_verifier":
        verifier = "y" * 64
    elif mode == "expired":
        with auth.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_challenges SET expires_at=1")
    else:
        auth.login(cid, CODE, verifier)
    restored = HumanSessionAuth(auth.store, auth.provider, permissions=auth.permissions)
    with pytest.raises(PermissionError):
        restored.login(cid, CODE, verifier)
    assert client.calls == (1 if mode == "replay" else 0)


@pytest.mark.parametrize(
    "mode",
    [
        "expired",
        "revoked",
        "copied_context",
        "scope_mismatch",
        "no_permission",
        "self_authority",
    ],
)
def test_authentication_never_implicitly_grants_approval_authority(human_env, mode):
    gate, auth, client, _ = human_env
    issued, context = login(auth, client)
    resource, subject = "device-1", "agent-1"
    if mode == "expired":
        with gate.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_sessions SET expires_at=1")
    elif mode == "revoked":
        auth.logout(context)
    elif mode == "copied_context":
        context = AuthorizationContext.from_dict(context.to_dict())
    elif mode == "scope_mismatch":
        resource = "other-device"
    elif mode == "no_permission":
        auth.permissions = PermissionEngine()
        context = auth.authenticate(issued.session_cookie)
    else:
        subject = context.subject_id
    request, pending = operation(gate, resource=resource, subject=subject)
    with pytest.raises(PermissionError):
        ApprovalBroker(gate.store).respond_operation(
            pending.request_id, "approve", context, gate=gate
        )
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert gate.store.list_active_leases() == []


@pytest.mark.parametrize(
    "mode", ["expired", "body", "route", "method", "session", "replay"]
)
def test_action_nonce_is_single_use_durable_and_request_bound(human_env, mode):
    _, auth, client, _ = human_env
    _, context = login(auth, client)
    method, path, body = "POST", "/api/v1/approvals/apr_test/approve", {"scope": "ONCE"}
    proof = auth.nonce(context, method, path, body)
    if mode == "expired":
        with auth.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_nonces SET expires_at=1")
    elif mode == "body":
        body = {"scope": "CAPABILITY"}
    elif mode == "route":
        path = "/api/v1/approvals/apr_other/approve"
    elif mode == "method":
        method = "DELETE"
    elif mode == "session":
        _, context = login(auth, client)
    else:
        auth.admit_request(context, proof["nonce"], method, path, body)
    restored = HumanSessionAuth(auth.store, auth.provider, permissions=auth.permissions)
    with pytest.raises(PermissionError):
        restored.admit_request(context, proof["nonce"], method, path, body)


def test_logout_revocation_remains_terminal_after_restart(human_env):
    _, auth, client, _ = human_env
    issued, context = login(auth, client)
    auth.logout(context)
    restored = HumanSessionAuth(auth.store, auth.provider, permissions=auth.permissions)
    assert restored.authenticate(issued.session_cookie) is None


def test_challenge_and_session_audit_failure_do_not_issue_authority(
    human_env, monkeypatch
):
    _, auth, client, _ = human_env
    cid = challenge(auth, client)
    append = auth.store.append_operation_audit

    def fail(db, event, evidence):
        if event == "human.session.created":
            raise RuntimeError("injected audit failure")
        return append(db, event, evidence)

    monkeypatch.setattr(auth.store, "append_operation_audit", fail)
    with pytest.raises(RuntimeError):
        auth.login(cid, CODE, VERIFIER)
    with auth.store.operation_transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM governance_human_sessions").fetchone()[0]
            == 0
        )


def test_restart_revalidates_enrolled_subject_not_only_original_session(human_env):
    _, auth, client, _ = human_env
    issued, _ = login(auth, client)
    auth.provider.subjects = frozenset({"bob"})
    restarted = HumanSessionAuth(
        auth.store, auth.provider, permissions=auth.permissions
    )
    assert restarted.authenticate(issued.session_cookie) is None


def test_oauth_library_token_logs_are_redacted_before_proof_validation(
    human_env, caplog
):
    import logging

    gate, auth, client, _ = human_env
    issued_id = challenge(auth, client)
    exchange = client.fetch_token
    opaque = "m35.fake.opaque.idp.access.material.813276"

    def logged_exchange(*args, **kwargs):
        logging.getLogger("authlib-test").warning(
            "response: %r", {"access_token": opaque}
        )
        return exchange(*args, **kwargs)

    client.fetch_token = logged_exchange
    auth.login(issued_id, CODE, VERIFIER)
    assert opaque not in caplog.text
    assert opaque not in json.dumps(gate.store.operation_audit())
