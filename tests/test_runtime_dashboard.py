from __future__ import annotations

from nous_runtime.cli.terminal_ui import render_runtime_dashboard
from nous_runtime.control_center.snapshot import RuntimeDashboard


def dashboard():
    return RuntimeDashboard(
        status_loader=lambda: {"version": "1.2.3"},
        health_loader=lambda: {"ok": True},
        inspector_loader=lambda: {
            "runtime": {"errors": []},
            "tasks": [
                {"task_id": "run-1", "status": "running"},
                {"task_id": "run-2", "status": "waiting_approval"},
            ],
            "observations": [{"observation_id": "event-1"}],
            "devices": [
                {
                    "device_id": "node-1",
                    "name": "Laptop",
                    "device_type": "desktop",
                    "online": True,
                    "capabilities": ["code"],
                    "last_seen": "now",
                    "public_key": "must-not-leak",
                    "credential_id": "must-not-leak",
                    "platform_hostname": "must-not-leak",
                }
            ],
            "findings": [],
        },
        metrics_loader=lambda: {"memory_mb": 42.0},
        event_metrics_loader=lambda: {"queue_depth": 1},
    )


def test_dashboard_is_bounded_server_authoritative_and_redacted():
    data = dashboard().snapshot()
    assert data["server_authoritative"] is True
    assert data["controls"] == {
        "execution_endpoint": "/api/runtime/run",
        "chat_endpoint": "/api/chat",
        "authenticated": True,
        "governed": True,
        "client_state_authoritative": False,
    }
    assert data["nodes"] == [
        {
            "node_id": "node-1",
            "name": "Laptop",
            "type": "desktop",
            "online": True,
            "capabilities": ["code"],
            "last_seen": "now",
        }
    ]
    assert "must-not-leak" not in str(data)
    assert len(data["missions"]) <= data["limits"]["missions"]
    assert len(data["timeline"]) <= data["limits"]["timeline"]


def test_terminal_dashboard_renders_runtime_and_devices():
    rendered = render_runtime_dashboard(dashboard().snapshot())
    assert "NOUS Runtime Dashboard" in rendered
    assert "Authority   server" in rendered
    assert "Version     1.2.3" in rendered
    assert "Nodes       1/1 online" in rendered
    assert "run-1" in rendered


def test_dashboard_degrades_without_mutating_authoritative_state():
    data = RuntimeDashboard(
        status_loader=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        health_loader=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        inspector_loader=lambda: {},
        metrics_loader=lambda: {},
        event_metrics_loader=lambda: {},
    ).snapshot()
    assert data["runtime"]["ok"] is False
    assert data["health"]["ok"] is False
    assert data["missions"] == []
    assert data["nodes"] == []


def test_dashboard_is_available_to_tui_and_authenticated_device_api(monkeypatch):
    from nous_runtime.api.routes import route
    from nous_runtime.cli.shell_v2 import COMMANDS

    monkeypatch.setenv("NOUS_API_TOKEN", "alpha-token")
    monkeypatch.setattr(
        "nous_runtime.control_center.snapshot.control_center_snapshot",
        lambda root=".": dashboard().snapshot(),
    )
    response = route(
        "GET", "/api/runtime/dashboard", auth={"token": "alpha-token"}, surface="server"
    )
    assert response["ok"] is True
    assert response["data"]["server_authoritative"] is True
    assert callable(COMMANDS["dashboard"]["fn"])
