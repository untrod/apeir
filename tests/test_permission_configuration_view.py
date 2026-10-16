"""Permission configuration is not a subject-bound authorization decision."""

from types import SimpleNamespace

import pytest

from nous_runtime.api.desktop_routes import handle_security_permissions
from nous_runtime.governance.permission import PermissionEngine, PermissionRule


@pytest.mark.parametrize(
    ("engine", "state"),
    [
        (None, "unconfigured"),
        (
            PermissionEngine(
                (PermissionRule("alice", "workspace.read", "workspace:one"),)
            ),
            "configured",
        ),
        (object(), "unknown"),
    ],
)
def test_query_never_fabricates_permission_grants(monkeypatch, engine, state):
    monkeypatch.setattr(
        "nous_runtime.governance.get_gate",
        lambda: SimpleNamespace(permission_engine=engine),
    )
    response = handle_security_permissions()
    assert response["ok"] is True
    assert response["data"]["configuration_state"] == state
    assert response["data"]["permissions_evaluated"] is False
    assert response["data"]["permissions"]
    assert all(
        row["granted"] is None and row["evaluation_state"] == "UNKNOWN"
        for row in response["data"]["permissions"]
    )


def test_configuration_read_failure_cannot_return_default_success(monkeypatch):
    def unavailable():
        raise PermissionError("Configuration authority cannot be read")

    monkeypatch.setattr("nous_runtime.governance.get_gate", unavailable)
    response = handle_security_permissions()
    assert response["ok"] is False
    assert response["error"]["code"] == "SECURITY_PERMISSION_READ_ERROR"
    assert "data" not in response
