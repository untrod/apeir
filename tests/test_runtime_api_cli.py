from __future__ import annotations

import json

from typer.testing import CliRunner

from nous_runtime.cli.main import app


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps({"ok": True, "data": {"status": "healthy"}}).encode()


def test_runtime_api_status_reports_reachable(monkeypatch) -> None:
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api.urlopen",
        lambda request, timeout: _Response(),
    )

    result = CliRunner().invoke(app, ["runtime-api", "status"])

    assert result.exit_code == 0
    assert "reachable at http://127.0.0.1:8770" in result.stdout


def test_runtime_api_status_json_reports_failure(monkeypatch) -> None:
    def unavailable(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr("nous_runtime.cli.runtime_api.urlopen", unavailable)

    result = CliRunner().invoke(app, ["runtime-api", "status", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["url"] == "http://127.0.0.1:8770"


def test_runtime_api_start_closes_server(monkeypatch) -> None:
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api._verify_kernel_ready", lambda: None
    )
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    calls: list[str] = []

    class Server:
        server_address = ("127.0.0.1", 8770)

        def serve_forever(self):
            calls.append("serve")

        def server_close(self):
            calls.append("close")

    monkeypatch.setattr(
        "nous_runtime.api.server.create_server",
        lambda host, port: Server(),
    )

    result = CliRunner().invoke(app, ["runtime-api", "start"])

    assert result.exit_code == 0
    assert calls == ["serve", "close"]
    assert "listening on http://127.0.0.1:8770" in result.stdout


def test_runtime_api_binds_before_rotating_local_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api._verify_kernel_ready", lambda: None
    )
    monkeypatch.delenv("NOUS_API_TOKEN", raising=False)
    monkeypatch.delenv("NOUS_AUTH_TOKEN", raising=False)
    calls: list[str] = []

    class Server:
        server_address = ("127.0.0.1", 8770)

        def serve_forever(self):
            calls.append("serve")

        def server_close(self):
            calls.append("close")

    class Auth:
        def generate(self):
            calls.append("generate")

        def revoke(self):
            calls.append("revoke")

    monkeypatch.setattr(
        "nous_runtime.api.server.create_server",
        lambda host, port: calls.append("bind") or Server(),
    )
    monkeypatch.setattr(
        "nous_runtime.control_plane.auth.ControlPlaneAuth.get",
        lambda: Auth(),
    )

    result = CliRunner().invoke(app, ["runtime-api", "start"])

    assert result.exit_code == 0
    assert calls == ["bind", "generate", "serve", "close", "revoke"]


def test_runtime_liveness_route_is_public() -> None:
    from nous_runtime.api.routes import route_server

    response = route_server("GET", "/live")

    assert response["ok"] is True
    assert response["data"]["alive"] is True
    assert isinstance(response["data"]["pid"], int)
