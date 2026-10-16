"""Connector writes require the existing explicit Governance decision."""

from types import SimpleNamespace

import pytest

from nous_runtime.connectors.models import ConnectorRequest
from tests.test_connector_runtime import context, manifest, runtime


@pytest.mark.parametrize(
    "decision",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(action_mode="EXECUTE"),
        SimpleNamespace(action_mode="EXECUTE", allowed=False),
        SimpleNamespace(action_mode="EXECUTE", allowed=None),
        SimpleNamespace(action_mode="EXECUTE", allowed="true"),
        SimpleNamespace(action_mode="EXECUTE", allowed=1),
        SimpleNamespace(action_mode="UNKNOWN", allowed=True),
        SimpleNamespace(action_mode="ASK_APPROVAL", allowed=True),
    ],
    ids=[
        "absent",
        "empty",
        "missing-allow",
        "denied",
        "unknown",
        "text",
        "integer",
        "unknown-mode",
        "approval-mode",
    ],
)
def test_connector_write_requires_explicit_boolean_execution_admission(
    tmp_path, decision
):
    gate = SimpleNamespace(evaluate=lambda *_: decision)
    service, store, adapter = runtime(
        tmp_path, manifest(scopes=("records.read", "records.write")), gate=gate
    )
    result = service.execute(
        ConnectorRequest(
            "mock.enterprise",
            "create",
            "workspace",
            {"name": "reviewed"},
            idempotency_key="original",
        ),
        context=context(),
    )
    assert not result.ok and result.error_code == "AUTHORIZATION_REQUIRED"
    assert adapter.calls == 0
    assert store.get_idempotent("mock.enterprise", "original") is None


def test_connector_write_accepts_the_existing_explicit_gate_contract(tmp_path):
    from nous_runtime.governance.contracts import AuthorizationDecision

    gate = SimpleNamespace(
        evaluate=lambda *_: AuthorizationDecision(action_mode="EXECUTE", allowed=True)
    )
    service, _, adapter = runtime(
        tmp_path, manifest(scopes=("records.read", "records.write")), gate=gate
    )
    result = service.execute(
        ConnectorRequest(
            "mock.enterprise", "create", "workspace", {"name": "reviewed"}
        ),
        context=context(),
    )
    assert result.ok and adapter.calls == 1
