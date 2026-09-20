from __future__ import annotations

import hashlib
import hmac
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from nous_runtime.connectors.adapters import LocalFileConnector, MockEnterpriseConnector, WebhookConnector
from nous_runtime.connectors.models import AuthenticationType, ConnectorAction, ConnectorManifest, ConnectorRequest, ConnectorRisk
from nous_runtime.connectors.runtime import ConnectorRuntime
from nous_runtime.connectors.store import ConnectorStore
from nous_runtime.connectors.vault import ConnectorCredential, MemoryTokenVault
from nous_runtime.governance import AuthorizationContext


class FakeGate:
    def __init__(self, mode: str = "EXECUTE"):
        self.mode = mode
        self.proposals = []

    def evaluate(self, proposal, context):
        self.proposals.append((proposal, context))
        return SimpleNamespace(action_mode=self.mode, reason_message="approval required", reason_code="TEST")


def manifest(*, scopes=("records.read",), rate=60):
    return ConnectorManifest(
        "mock.enterprise", "1.0.0",
        (
            ConnectorAction("list", ConnectorRisk.READ, ("records.read",)),
            ConnectorAction("create", ConnectorRisk.WRITE, ("records.write",)),
        ),
        AuthenticationType.API_TOKEN,
        scopes,
        rate_limit_per_minute=rate,
        max_retries=2,
    )


def context():
    return AuthorizationContext(subject_type="user", subject_id="tester", authn_method="test", authn_confidence=1.0)


def runtime(tmp_path, item, *, gate=None, credential=None):
    store = ConnectorStore(tmp_path)
    store.register(item, credential_ref="test:connector")
    vault = MemoryTokenVault()
    vault.put("test:connector", credential or ConnectorCredential("not-a-real-token", scopes=item.granted_scopes))
    service = ConnectorRuntime(store, vault, gate=gate or FakeGate())
    adapter = MockEnterpriseConnector({"": ({"id": "1"},), "next": ({"id": "2"},)})
    service.bind(item.connector_id, adapter)
    return service, store, adapter


def test_read_only_connector_paginates_and_persists_cursor(tmp_path):
    service, store, _ = runtime(tmp_path, manifest())
    result = service.execute(ConnectorRequest("mock.enterprise", "list", "workspace", cursor=""), context=context())
    assert result.ok and result.items[0]["id"] == "1"
    assert result.next_cursor == "next"
    assert store.cursor("mock.enterprise") == "next"


def test_write_connector_requires_governance_execute(tmp_path):
    gate = FakeGate("ASK_APPROVAL")
    service, _, adapter = runtime(tmp_path, manifest(scopes=("records.read", "records.write")), gate=gate)
    result = service.execute(ConnectorRequest("mock.enterprise", "create", "workspace", {"name": "x"}), context=context())
    assert not result.ok and result.error_code == "AUTHORIZATION_REQUIRED"
    assert adapter.calls == 0
    assert gate.proposals[0][0].side_effect_class == "external_write"


def test_invalid_scope_revocation_and_rate_limit_fail_closed(tmp_path):
    service, store, _ = runtime(tmp_path, manifest(rate=1))
    denied = service.execute(ConnectorRequest("mock.enterprise", "create", "workspace"), context=context())
    assert denied.error_code == "SCOPE_DENIED"
    assert service.execute(ConnectorRequest("mock.enterprise", "list", "workspace"), context=context()).ok
    assert service.execute(ConnectorRequest("mock.enterprise", "list", "workspace"), context=context()).error_code == "RATE_LIMITED"
    assert store.revoke("mock.enterprise")
    assert service.execute(ConnectorRequest("mock.enterprise", "list", "workspace"), context=context()).error_code == "CONNECTOR_REVOKED"


def test_expired_credential_is_rejected(tmp_path):
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    service, _, adapter = runtime(tmp_path, manifest(), credential=ConnectorCredential("expired", ("records.read",), expired))
    result = service.execute(ConnectorRequest("mock.enterprise", "list", "workspace"), context=context())
    assert result.error_code == "CREDENTIAL_EXPIRED"
    assert adapter.calls == 0


def test_retry_and_idempotency_are_bounded(tmp_path):
    store = ConnectorStore(tmp_path)
    item = manifest()
    store.register(item, credential_ref="test:connector")
    vault = MemoryTokenVault()
    vault.put("test:connector", ConnectorCredential("token", item.granted_scopes))
    service = ConnectorRuntime(store, vault, gate=FakeGate())
    adapter = MockEnterpriseConnector(fail_times=2)
    service.bind(item.connector_id, adapter)
    request = ConnectorRequest(item.connector_id, "list", "workspace", idempotency_key="same")
    first = service.execute(request, context=context())
    second = service.execute(request, context=context())
    assert first.ok and first.attempts == 3
    assert second.ok and adapter.calls == 3


def test_local_file_connector_blocks_workspace_escape(tmp_path):
    adapter = LocalFileConnector(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    denied = adapter.execute(ConnectorRequest("local", "read", "workspace", {"path": "../private.txt"}), None)
    assert denied.error_code == "WORKSPACE_ESCAPE"
    written = adapter.execute(ConnectorRequest("local", "write", "workspace", {"path": "safe/data.txt", "content": "ok"}), None)
    assert written.ok
    assert adapter.execute(ConnectorRequest("local", "read", "workspace", {"path": "safe/data.txt"}), None).items[0]["content"] == "ok"


def test_webhook_signature_and_store_do_not_persist_token(tmp_path):
    body = '{"event":"updated"}'
    secret = "test-secret-value"
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    adapter = WebhookConnector()
    valid = adapter.execute(ConnectorRequest("hook", "receive", "workspace", {"body": body, "signature": signature}), ConnectorCredential(secret))
    invalid = adapter.execute(ConnectorRequest("hook", "receive", "workspace", {"body": body, "signature": "invalid"}), ConnectorCredential(secret))
    assert valid.ok and not invalid.ok
    store = ConnectorStore(tmp_path)
    store.register(manifest(), credential_ref="env:CONNECTOR_TOKEN")
    assert secret.encode() not in store.path.read_bytes()

def test_connector_timeout_returns_terminal_error_without_waiting_for_late_result(tmp_path):
    release = threading.Event()

    class SlowAdapter:
        def execute(self, request, credential):
            release.wait(timeout=1.0)
            return SimpleNamespace(ok=True, items=(), next_cursor="", error_code="", message="late")

        def health(self):
            return {"status": "degraded"}

    store = ConnectorStore(tmp_path)
    item = manifest()
    store.register(item, credential_ref="test:connector")
    vault = MemoryTokenVault()
    vault.put("test:connector", ConnectorCredential("token", item.granted_scopes))
    service = ConnectorRuntime(store, vault, gate=FakeGate(), timeout_seconds=0.02)
    service.bind(item.connector_id, SlowAdapter())

    started = time.perf_counter()
    try:
        result = service.execute(
            ConnectorRequest(item.connector_id, "list", "workspace"),
            context=context(),
        )
    finally:
        release.set()
    elapsed = time.perf_counter() - started

    assert result.error_code == "CONNECTOR_TIMEOUT"
    assert elapsed < 0.5


def test_connector_unexpected_failure_is_isolated_as_result(tmp_path):
    class FailingAdapter:
        def execute(self, request, credential):
            raise RuntimeError("private adapter detail")

        def health(self):
            return {"status": "error"}

    store = ConnectorStore(tmp_path)
    item = manifest()
    store.register(item, credential_ref="test:connector")
    vault = MemoryTokenVault()
    vault.put("test:connector", ConnectorCredential("token", item.granted_scopes))
    service = ConnectorRuntime(store, vault, gate=FakeGate())
    service.bind(item.connector_id, FailingAdapter())

    result = service.execute(ConnectorRequest(item.connector_id, "list", "workspace"), context=context())

    assert result.error_code == "CONNECTOR_FAILURE"
    assert "private adapter detail" not in result.message