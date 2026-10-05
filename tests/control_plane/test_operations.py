"""Canonical state, durable events and governed remote actions."""

import json
import threading
from urllib.request import Request, urlopen

import pytest

from nous_runtime.api.routes import route_server
from nous_runtime.api.server import RuntimeHTTPServer, RuntimeAPIHandler
from nous_runtime.control_plane import human_sessions, operations
from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.governance.permission import PermissionRule
from nous_runtime.governance.broker import ApprovalBroker
from tests.control_plane.test_human_sessions import (
    human_env as human_env_fixture,
    login,
    operation,
    challenge,
    CODE,
    VERIFIER,
)

human_env = human_env_fixture

pytestmark = pytest.mark.unit


@pytest.fixture
def plane(human_env, tmp_path, monkeypatch):
    gate, auth, client, _ = human_env
    auth.permissions.add(PermissionRule("oidc:*:alice", "control.*", "device-1"))
    view = OperationsPlane(tmp_path, gate=gate, health_loader=lambda: {"ok": True})
    monkeypatch.setattr(operations, "_operations", view)
    monkeypatch.setattr(human_sessions, "_configured_auth", auth)
    return view, auth, client


def test_projection_is_authoritative_and_does_not_provision_controller(plane):
    view, _, _ = plane
    data = view.snapshot()
    assert all(
        isinstance(data[key], list)
        for key in (
            "agents",
            "works",
            "workflows",
            "nodes",
            "devices",
            "approvals",
            "grants",
            "credential_leases",
            "artifacts",
            "evidence",
            "activity",
            "incidents",
        )
    )
    assert data["server_authoritative"]
    assert data["nodes"] == data["devices"] == data["works"] == []
    assert data["health"]["degraded"]
    assert data["health"]["components"][0]["status"] == "UNKNOWN"
    assert not (view.controller_state / "identity.ed25519.pem").exists()
    assert set(data) >= {
        "agents",
        "workflows",
        "approvals",
        "grants",
        "credential_leases",
        "artifacts",
        "evidence",
        "activity",
        "incidents",
    }


@pytest.mark.parametrize("answer", ["approve_once", "deny"])
def test_remote_action_binds_approval_session_nonce_and_original_operation(
    plane, answer
):
    view, auth, client = plane
    issued, context = login(auth, client)
    request, pending = operation(view.gate)
    body = {"kind": "approvals", "action": answer, "target_id": pending.request_id}
    path = "/api/v1/control/operations/actions"
    nonce = auth.nonce(context, "POST", path, body)["nonce"]
    headers = {
        "cookie": "apeir_human=" + issued.session_cookie,
        "x-control-nonce": nonce,
    }
    response = route_server("POST", path, body=body, auth={"headers": headers})
    assert response["ok"], response
    assert not response["data"]["replanned"]
    assert view.gate.get_operation_request(request.authorization_id) == request
    assert not route_server("POST", path, body=body, auth={"headers": headers})["ok"]
    records = view.gate.store.operation_audit()
    admitted = [
        row for row in records if row["event_type"] == "control.action.admitted"
    ]
    assert len(admitted) == 1
    assert (
        json.loads(admitted[0]["evidence_json"])["human_session_id"]
        == context.session_id
    )
    assert issued.session_cookie not in json.dumps(view.snapshot())


def test_authenticated_service_cannot_approve_its_own_request(plane, monkeypatch):
    view, _, _ = plane
    _, pending = operation(view.gate)
    monkeypatch.setenv("NOUS_API_TOKEN", "fake-local-service-token")
    response = route_server(
        "POST",
        "/api/v1/control/operations/actions",
        body={
            "kind": "approvals",
            "action": "approve_once",
            "target_id": pending.request_id,
        },
        auth={"token": "fake-local-service-token", "loopback": True},
    )
    assert not response["ok"]
    assert (
        ApprovalBroker(view.gate.store).get_operation_approval(
            pending.request_id, gate=view.gate
        )["status"]
        == "PENDING"
    )


def test_event_backfill_is_durable_monotonic_and_not_polling_noise(plane):
    view, _, _ = plane
    first = view.transitions()
    assert len(first) == 1
    assert view.transitions(since=first[0]["sequence"]) == []
    operation(view.gate)
    changed = view.transitions(since=first[0]["sequence"])
    assert len(changed) == 1
    restarted = OperationsPlane(
        view.root, gate=view.gate, health_loader=lambda: {"ok": True}
    )
    assert restarted.transitions() == first + changed
    assert changed[0]["payload"]["counts"]["approvals"] == 1


def test_human_cookie_http_only_and_authenticated_sse(plane):
    view, auth, client = plane
    issued_id = challenge(auth, client)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = "http://127.0.0.1:" + str(server.server_port)
    try:
        request = Request(
            endpoint + "/api/v1/control/human/session",
            data=json.dumps(
                {"challenge_id": issued_id, "code": CODE, "code_verifier": VERIFIER}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            cookie = response.headers["Set-Cookie"]
            result = response.read().decode()
            assert all(
                part in cookie for part in ("HttpOnly", "Secure", "SameSite=Strict")
            )
            token = cookie.split(";", 1)[0]
            assert token.split("=", 1)[1] not in result
        with urlopen(
            Request(
                endpoint + "/api/v1/control/events",
                headers={"Cookie": token, "Accept": "text/event-stream"},
            ),
            timeout=5,
        ) as stream:
            assert stream.headers["Content-Type"] == "text/event-stream"
            assert stream.readline().startswith(b"id: ")
            assert stream.readline() == b"event: control.state.changed\n"
            assert b"control.state.changed" in stream.readline()
            auth.logout(auth.authenticate(token.split("=", 1)[1]))
            # The active stream revalidates revocation and closes promptly.
            assert len(stream.read()) < 4096
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_expired_human_cannot_interrupt_even_with_attested_context(plane):
    view, auth, client = plane
    _, context = login(auth, client)
    request, _ = operation(view.gate)
    with view.gate.store.operation_transaction() as db:
        db.execute("UPDATE governance_human_sessions SET expires_at=0")
    with pytest.raises(PermissionError):
        view.gate.interrupt_operation(request.authorization_id, context)
    with view.gate.store.operation_transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM governance_revocations").fetchone()[0] == 0
        )


def test_remote_revoke_grant_is_durable_and_denies_revoked_lease(plane):
    from nous_runtime.governance.cli import _build_context

    view, auth, client = plane
    request, _ = operation(view.gate)
    grant = view.gate.issue_operation_grant(request.authorization_id, _build_context())
    _, context = login(auth, client)
    view.action(
        {"kind": "grants", "action": "revoke", "target_id": grant.lease_id}, context
    )
    assert (
        next(
            item
            for item in view.snapshot()["grants"]
            if item["lease_id"] == grant.lease_id
        )["effective_status"]
        == "REVOKED"
    )
    assert view.gate.evaluate_operation(request.authorization_id).value != "ALLOW"


def test_expired_grants_are_not_presented_as_active_authority(plane):
    from nous_runtime.governance.cli import _build_context

    view, _, _ = plane
    request, _ = operation(view.gate)
    grant = view.gate.issue_operation_grant(request.authorization_id, _build_context())
    with view.gate.store.operation_transaction() as db:
        value = json.loads(
            db.execute(
                "SELECT lease_json FROM governance_leases WHERE lease_id=?",
                (grant.lease_id,),
            ).fetchone()[0]
        )
        value["expires_at"] = "2000-01-01T00:00:00+00:00"
        db.execute(
            "UPDATE governance_leases SET lease_json=? WHERE lease_id=?",
            (json.dumps(value), grant.lease_id),
        )
    assert view.snapshot()["grants"][0]["effective_status"] == "EXPIRED"


def test_credential_collection_exposes_only_scoped_lease_metadata():
    from nous_runtime.core.redaction import (
        redact_sensitive_data,
        register_sensitive_value,
        REDACTED,
    )

    material = "m35.fake.unprintable.credential.lease.material.817652"
    register_sensitive_value(material)
    valid = {
        "credential_leases": [
            {"lease_id": "lease-1", "handle_id": "handle-1", "work_id": "work-1"}
        ]
    }
    assert redact_sensitive_data(valid) == valid
    assert (
        redact_sensitive_data({"credential_leases": [{"material": material}]})[
            "credential_leases"
        ]
        == REDACTED
    )
    assert material not in str(
        redact_sensitive_data({"credential_leases": [{"work_id": material}]})
    )


def test_incident_acknowledgement_survives_activity_window_and_restart(plane):
    from nous_runtime.node_runtime.distributed_work import (
        DistributedWork,
        DistributedWorkStore,
        DistributedWorkState,
    )

    view, auth, client = plane
    request, _ = operation(view.gate)
    DistributedWorkStore(view.controller_state).create(
        DistributedWork(
            intent="Reconcile uncertain simulated firmware effect",
            work_id=request.work_id,
            state=DistributedWorkState.UNKNOWN,
            target_resource_id=request.resource_id,
            execution_arguments={"authorization_id": request.authorization_id},
        )
    )
    _, context = login(auth, client)
    incident = view.snapshot()["incidents"][0]
    view.action(
        {
            "kind": "incidents",
            "action": "acknowledge",
            "target_id": incident["incident_id"],
        },
        context,
    )
    with view.gate.store.operation_transaction() as db:
        for index in range(501):
            view.gate.store.append_operation_audit(
                db, "test.unrelated.activity", {"sequence": index}
            )
    restarted = OperationsPlane(
        view.root, gate=view.gate, health_loader=lambda: {"ok": True}
    )
    snapshot = restarted.snapshot()
    assert len(snapshot["activity"]) == 500
    assert snapshot["incidents"][0]["acknowledged"]
    assert snapshot["works"][0]["state"] == "UNKNOWN"
