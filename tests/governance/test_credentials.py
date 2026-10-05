"""Scoped secret delivery, protected storage, leakage and approval backend contracts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
import pickle

import pytest

from nous_runtime.core.redaction import REDACTED, redact_sensitive_data
from nous_runtime.governance import (
    AuthorizationContext,
    ExecutionAuthorizationGate,
    GovernanceRequest,
    GovernanceStore,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.cli import _build_context
from nous_runtime.governance.credentials import (
    CredentialBroker,
    SecretHandle,
    VaultSecretBackend,
    ReferenceSecretBackend,
)
from nous_runtime.node_runtime.service import _node_execution_context
from nous_runtime.governance import operation_gate

pytestmark = pytest.mark.unit
FAKE = "apeir-m34b-opaque-fixture-material-7318942"
HANDLE = "secret_" + "1" * 32
KEY = b"m" * 32


class CountingBackend:
    def __init__(self, backend):
        self.backend = backend
        self.calls = 0

    def resolve(self, handle):
        self.calls += 1
        return self.backend.resolve(handle)


@pytest.fixture
def credential_env(tmp_path):
    gate = ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance"))
    vault = VaultSecretBackend(tmp_path / "protected" / "vault.db", master_key=KEY)
    handle = vault.put(HANDLE, FAKE)
    backend = CountingBackend(vault)
    broker = CredentialBroker(gate, backend)
    request = make_request(gate)
    broker.register_handle(handle, request.authorization_id, _build_context())
    grant = gate.issue_operation_grant(request.authorization_id, _build_context())
    return gate, broker, request, backend, grant


def make_request(gate, work="credential-work", **overrides):
    request = GovernanceRequest(
        operation_id=work,
        work_id=work,
        subject_id="credential-agent",
        node_id="credential-node",
        resource_id="credential-device",
        capability_id="device.firmware.update",
        agent_session_id="credential-session",
        secret_handles=(HANDLE,),
        capability_inputs=gate.capability_inputs("device.firmware.update"),
    )
    request = replace(request, **overrides)
    gate.register_operation(request)
    return request


def run(gate, broker, request, callback):
    context = _node_execution_context(request.node_id, request.work_id)
    with gate.admit_operation(
        request.authorization_id,
        resource_check=lambda: True,
        authorization_context=context,
    ) as admission:
        return broker.run_provider(
            request.authorization_id, context, admission=admission, call=callback
        )


def test_secret_handle_reuses_kernel_reference_and_vault_is_encrypted(tmp_path):
    from nous_runtime.kernel.identity import SecretRef

    assert SecretHandle is SecretRef
    vault = VaultSecretBackend(tmp_path / "protected.db", master_key=KEY)
    handle = vault.put(HANDLE, FAKE)
    assert FAKE not in repr(handle)
    assert vault.resolve(handle) == FAKE
    restored = VaultSecretBackend(tmp_path / "protected.db", master_key=KEY)
    assert restored.resolve(handle) == FAKE
    assert FAKE.encode() not in (tmp_path / "protected.db").read_bytes()
    with pytest.raises(ValueError):
        VaultSecretBackend(tmp_path / "other.db", master_key=b"bad")


def test_context_is_execution_only_and_delivery_is_audited(credential_env):
    gate, broker, request, backend, grant = credential_env
    saved = []

    def provider(context):
        saved.append(context)
        assert context.get(HANDLE) == FAKE
        assert context.leases[0].authorization_id == request.authorization_id
        assert context.leases[0].work_id == request.work_id
        assert context.leases[0].resource_id == request.resource_id
        assert FAKE not in repr(context)
        with pytest.raises(TypeError):
            pickle.dumps(context)
        return {"provider_echo": context.get(HANDLE), "context": context}

    result = run(gate, broker, request, provider)
    assert result.pop("credential_lease_ids")
    assert result == {
        "provider_echo": REDACTED,
        "context": REDACTED,
    }
    with pytest.raises(PermissionError, match="closed"):
        saved[0].get(HANDLE)
    assert saved[0]._values == {}
    with gate.store.operation_transaction() as db:
        row = db.execute(
            "SELECT status,lease_json FROM governance_credential_leases"
        ).fetchone()
        assert row[0] == "CLOSED"
        assert FAKE not in row[1]
    assert backend.calls == 1
    events = {row["event_type"] for row in gate.store.operation_audit()}
    assert {
        "credential.handle.registered",
        "credential.lease.issued",
        "credential.lease.closed",
    } <= events
    assert gate.store.verify_audit_chain()
    with pytest.raises(PermissionError):
        run(gate, broker, request, lambda context: pytest.fail("replayed delivery"))
    assert backend.calls == 1


@pytest.mark.parametrize(
    "subject_type",
    [
        "agent",
        "model",
        "planner",
        "scheduler",
        "node",
        "provider",
        "operation",
        "service",
        "user",
    ],
)
def test_constructed_context_cannot_resolve_or_issue_credentials(
    credential_env, subject_type
):
    gate, broker, request, backend, _ = credential_env
    context = AuthorizationContext(
        subject_type=subject_type,
        subject_id=request.node_id,
        authn_method="node_key",
        authn_confidence=1.0,
        session_id=request.work_id,
    )
    with pytest.raises(PermissionError):
        with broker.execution(
            request.authorization_id, context, admission=lambda: None
        ):
            pytest.fail("raw credential delivered")
    with pytest.raises(PermissionError):
        with gate.admit_operation(
            request.authorization_id,
            resource_check=lambda: True,
            authorization_context=context,
        ):
            pytest.fail("constructed Node context trusted")
    with pytest.raises(PermissionError):
        broker.register_handle(SecretHandle(HANDLE), request.authorization_id, context)
    assert backend.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", "other-node"),
        ("resource_id", "other-resource"),
        ("capability_id", "device.state.set"),
        ("subject_id", "other-agent"),
    ],
)
def test_handle_scope_mismatch_fails_before_backend_resolution(
    credential_env, field, value
):
    gate, broker, first, backend, _ = credential_env
    changed = make_request(gate, "changed-work", **{field: value})
    if field == "capability_id":
        changed = replace(changed, capability_inputs=gate.capability_inputs(value))
        # Use a fresh identity because Operation bindings are immutable.
        changed = replace(
            changed, operation_id="changed-cap-work", work_id="changed-cap-work"
        )
        gate.register_operation(changed)
    gate.issue_operation_grant(changed.authorization_id, _build_context())
    with pytest.raises(PermissionError, match="scope"):
        run(
            gate,
            broker,
            changed,
            lambda context: pytest.fail("mismatched secret delivered"),
        )
    assert backend.calls == 0


@pytest.mark.parametrize("kind", ["missing", "expired", "revoked"])
def test_handle_unavailable_survives_restart_without_resolution(
    credential_env, tmp_path, kind
):
    gate, broker, request, backend, _ = credential_env
    if kind == "revoked":
        broker.revoke(request.authorization_id, _build_context(), handle_id=HANDLE)
    else:
        with gate.store.operation_transaction() as db:
            if kind == "missing":
                db.execute("DELETE FROM governance_secret_handles")
            else:
                db.execute(
                    "UPDATE governance_secret_handles SET expires_at='2000-01-01T00:00:00Z'"
                )
    restored = ExecutionAuthorizationGate(GovernanceStore(tmp_path / "governance"))
    delivery = CredentialBroker(restored, backend)
    with pytest.raises(PermissionError, match="missing, expired or revoked"):
        run(
            restored,
            delivery,
            request,
            lambda context: pytest.fail("unavailable secret delivered"),
        )
    if kind == "revoked":
        with pytest.raises(PermissionError, match="remains revoked"):
            delivery.register_handle(
                SecretHandle(HANDLE), request.authorization_id, _build_context()
            )
    assert backend.calls == 0


@pytest.mark.parametrize("change", ["expiry", "revocation"])
def test_live_credential_lease_revalidates_and_cannot_outlive_effect_admission(
    credential_env, monkeypatch, change
):
    gate, broker, request, _, _ = credential_env

    def provider(context):
        assert context.get(HANDLE) == FAKE
        if change == "expiry":
            later = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            monkeypatch.setattr(operation_gate, "_utc_now", lambda: later)
        else:
            db = next(iter(gate._execution_admissions.values()))[2]
            db.execute("UPDATE governance_credential_leases SET status='REVOKED'")
        context.get(HANDLE)
        pytest.fail("expired/revoked credential reused")

    with pytest.raises(RuntimeError, match="expired, revoked or closed"):
        run(gate, broker, request, provider)


def test_authorization_revocation_blocks_resolution_even_with_handle(credential_env):
    gate, broker, request, backend, grant = credential_env
    gate.revoke_operation_authority(
        request.authorization_id, _build_context(), grant_id=grant.lease_id
    )
    with pytest.raises(PermissionError):
        run(
            gate, broker, request, lambda context: pytest.fail("revoked grant resolved")
        )
    assert backend.calls == 0


def test_environment_backend_reuses_reference_resolver_without_persisting_value(
    credential_env, monkeypatch
):
    gate, _, request, _, _ = credential_env
    monkeypatch.setenv("APEIR_M34B_FAKE_KEY", FAKE)
    broker = CredentialBroker(
        gate, ReferenceSecretBackend({HANDLE: "env:APEIR_M34B_FAKE_KEY"})
    )
    result = run(gate, broker, request, lambda context: {"echo": context.get(HANDLE)})
    assert result.pop("credential_lease_ids")
    assert result == {"echo": REDACTED}
    assert FAKE not in json.dumps(gate.store.operation_audit())


def test_provider_logging_exceptions_prints_and_late_logs_are_redacted(
    credential_env, caplog, capsys
):
    gate, broker, request, _, _ = credential_env

    def provider(context):
        value = context.get(HANDLE)
        print(value)
        logging.getLogger("apeir.fake-provider").warning(
            "Provider %s", value, extra={"provider_detail": {"nested": value}}
        )
        try:
            raise ValueError("Provider rejected " + value)
        except ValueError:
            logging.getLogger("apeir.fake-provider").exception("Credential failure")
            raise

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError) as error:
            run(gate, broker, request, provider)
        logging.getLogger("apeir.fake-provider").warning("Late output %s", FAKE)
    captured = capsys.readouterr()
    assert FAKE not in captured.out + captured.err + caplog.text + str(error.value)
    assert FAKE not in repr([record.__dict__ for record in caplog.records])
    assert REDACTED in captured.out
    assert FAKE not in json.dumps(gate.store.operation_audit())


def test_backend_failure_is_static_and_does_not_expose_backend_error(credential_env):
    gate, _, request, _, _ = credential_env

    class FailedBackend:
        def resolve(self, handle):
            raise ValueError(FAKE)

    with pytest.raises(
        PermissionError, match="Secret backend resolution failed"
    ) as error:
        run(
            gate,
            CredentialBroker(gate, FailedBackend()),
            request,
            lambda context: pytest.fail("effect after backend error"),
        )
    assert FAKE not in str(error.value)


def test_approval_backend_lists_details_and_never_trusts_remote_service(credential_env):
    gate, _, request, _, _ = credential_env
    broker = ApprovalBroker(gate.store)
    pending = broker.request_operation(request.authorization_id, gate=gate)
    listed = broker.list_operation_approvals(gate=gate)
    assert listed[0]["request_id"] == pending.request_id
    assert listed[0]["bindings"]["secret_handles"] == [HANDLE]
    assert broker.get_operation_approval(pending.request_id, gate=gate)[
        "scope_summary"
    ].startswith("Approve Once")
    service = AuthorizationContext(
        subject_type="service",
        subject_id="api-service",
        authn_method="api_bearer_token",
        authn_confidence=0.9,
    )
    for action in ("approve", "deny"):
        with pytest.raises(PermissionError):
            broker.respond_operation(pending.request_id, action, service, gate=gate)
    assert (
        broker.respond_operation(
            pending.request_id, "deny", _build_context(), gate=gate
        ).decision
        == "DENIED"
    )
    assert broker.list_operation_approvals(gate=gate) == []


def test_redaction_preserves_only_nonsecret_handle_and_authorization_references():
    assert redact_sensitive_data(
        {"secret_handles": [HANDLE], "authorization_id": "gov_123", "secret": FAKE}
    ) == {"secret_handles": [HANDLE], "authorization_id": "gov_123", "secret": REDACTED}


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_remote_approval_routes_reject_body_identity_claims(
    credential_env, monkeypatch, action
):
    from nous_runtime.api.routes import route
    import nous_runtime.governance.broker as broker_module
    import nous_runtime.governance.gate as gate_module

    gate, _, request, _, _ = credential_env
    broker = ApprovalBroker(gate.store)
    pending = broker.request_operation(request.authorization_id, gate=gate)
    monkeypatch.setattr(broker_module, "get_broker", lambda: broker)
    monkeypatch.setattr(gate_module, "get_gate", lambda: gate)
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    api_token = "m34b-fixture-service-token"
    monkeypatch.setenv("NOUS_API_TOKEN", api_token)
    auth = {"headers": {"Authorization": "Bearer " + api_token}}
    assert not route("GET", "/api/v1/approvals")["ok"]
    listed = route("GET", "/api/v1/approvals", auth=auth)
    assert listed["data"]["approvals"][0]["request_id"] == pending.request_id
    detail = route("GET", f"/api/v1/approvals/{pending.request_id}", auth=auth)
    assert detail["ok"]
    result = route(
        "POST",
        f"/api/v1/approvals/{pending.request_id}/{action}",
        auth=auth,
        body={
            "subject_type": "human",
            "authn_method": "local_os_owner",
            "approver_id": "owner",
            "echo": FAKE,
        },
    )
    assert result["error"]["code"] == "NOUS_HUMAN_APPROVAL_REQUIRED"
    assert gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
    assert FAKE not in json.dumps(
        [listed, detail, result, gate.store.operation_audit()]
    )


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_local_approval_cli_reuses_authority_and_outputs_no_secret(
    credential_env, monkeypatch, action
):
    from typer.testing import CliRunner
    from nous_runtime.governance import cli

    gate, _, request, _, _ = credential_env
    pending = ApprovalBroker(gate.store).request_operation(
        request.authorization_id, gate=gate
    )
    monkeypatch.setattr(
        cli,
        "ApprovalManager",
        lambda: __import__(
            "nous_runtime.governance.approval", fromlist=["ApprovalManager"]
        ).ApprovalManager(gate.store),
    )
    result = CliRunner().invoke(cli.approval_app, [action, pending.request_id])
    assert result.exit_code == 0, result.output
    assert FAKE not in result.output
    assert gate.store.get_approval_request(pending.request_id)["status"] == (
        "APPROVED" if action == "approve" else "DENIED"
    )


@pytest.mark.parametrize("source", ["bytes", "file", "chunk_boundary"])
def test_artifact_payload_cannot_persist_resolved_material(
    credential_env, tmp_path, source
):
    from nous_runtime.artifact import ContentAddressedArtifactStore
    from nous_runtime.core.errors import ArtifactError

    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    content = FAKE.encode()
    if source == "chunk_boundary":
        content = b"x" * (1024 * 1024 - 5) + content
    with pytest.raises(ArtifactError, match="Secret material"):
        if source == "bytes":
            store.store_bytes(content, artifact_type="evidence", name="fixture")
        else:
            protected_source = tmp_path / "protected" / "fixture-source"
            protected_source.write_bytes(content)
            try:
                store.store_file(
                    protected_source, artifact_type="evidence", name="fixture"
                )
            finally:
                protected_source.unlink()
    assert not list(store.objects.rglob("*"))
    assert all(
        FAKE.encode() not in path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_audit_failure_before_resolution_prevents_delivery(credential_env, monkeypatch):
    gate, broker, request, backend, _ = credential_env
    append = gate.store.append_operation_audit

    def fail(db, event, evidence):
        if event == "credential.lease.issued":
            raise RuntimeError("injected durable audit failure")
        return append(db, event, evidence)

    monkeypatch.setattr(gate.store, "append_operation_audit", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        run(gate, broker, request, lambda context: pytest.fail("effect without audit"))
    assert backend.calls == 0
    with gate.store.operation_transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM governance_credential_leases").fetchone()[
                0
            ]
            == 0
        )
