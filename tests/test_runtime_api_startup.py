from __future__ import annotations

import pytest
import typer


def test_runtime_api_initializes_runtime_services_before_serving(monkeypatch, tmp_path):
    from nous_runtime.cli.runtime_api import start_runtime_api

    calls: list[str] = []

    class FakeServer:
        server_address = ("127.0.0.1", 8770)

        def serve_forever(self):
            calls.append("serve")
            raise KeyboardInterrupt

        def server_close(self):
            calls.append("close")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.api.server.create_server", lambda **_: FakeServer()
    )
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api._verify_kernel_ready",
        lambda: calls.append("kernel"),
    )
    monkeypatch.setattr(
        "nous_runtime.services.lifecycle.run_migrations",
        lambda: calls.append("migrate"),
    )
    monkeypatch.setattr(
        "nous_runtime.services.lifecycle.seed_capabilities",
        lambda: calls.append("seed"),
    )
    monkeypatch.setattr(
        "nous_runtime.workspace.auto_create.ensure_workspace",
        lambda _root: calls.append("workspace") or {"ok": True},
    )

    def load_providers():
        calls.append("providers")
        return 1

    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config",
        load_providers,
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.clear",
        lambda: calls.append("gateway-clear"),
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.configure_from_providers",
        lambda: calls.append("gateway-configure"),
    )

    start_runtime_api(host="127.0.0.1", port=8770)

    assert calls == [
        "kernel",
        "workspace",
        "migrate",
        "seed",
        "providers",
        "gateway-clear",
        "gateway-configure",
        "serve",
        "close",
    ]
    assert __import__("os").environ["NOUS_WORKSPACE_ROOT"] == str(tmp_path)


def test_runtime_api_does_not_build_empty_gateway(monkeypatch, tmp_path):
    from nous_runtime.cli.runtime_api import start_runtime_api

    calls: list[str] = []

    class FakeServer:
        server_address = ("127.0.0.1", 8770)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.api.server.create_server", lambda **_: FakeServer()
    )
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api._verify_kernel_ready", lambda: None
    )
    monkeypatch.setattr("nous_runtime.services.lifecycle.run_migrations", lambda: 0)
    monkeypatch.setattr("nous_runtime.services.lifecycle.seed_capabilities", lambda: 0)
    monkeypatch.setattr(
        "nous_runtime.workspace.auto_create.ensure_workspace",
        lambda _root: {"ok": True},
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config",
        lambda: 0,
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.clear",
        lambda: calls.append("clear"),
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.configure_from_providers",
        lambda: calls.append("configure"),
    )

    start_runtime_api(host="127.0.0.1", port=8770)

    assert calls == ["clear"]


def test_runtime_api_fails_closed_when_workspace_initialization_fails(
    monkeypatch,
    tmp_path,
):
    from nous_runtime.cli.runtime_api import start_runtime_api

    calls: list[str] = []

    class FakeServer:
        server_address = ("127.0.0.1", 8770)

        def server_close(self):
            calls.append("close")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOUS_API_TOKEN", "test-token")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.api.server.create_server",
        lambda **_: FakeServer(),
    )
    monkeypatch.setattr(
        "nous_runtime.cli.runtime_api._verify_kernel_ready",
        lambda: None,
    )
    monkeypatch.setattr(
        "nous_runtime.workspace.auto_create.ensure_workspace",
        lambda _root: {"ok": False, "message": "workspace rejected"},
    )

    with pytest.raises(typer.Exit) as raised:
        start_runtime_api(host="127.0.0.1", port=8770)

    assert raised.value.exit_code == 1
    assert calls == ["close"]


def test_kernel_readiness_is_required_in_production(monkeypatch):
    from nous_runtime.cli.runtime_api import _verify_kernel_ready

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.delenv("NOUS_KERNEL_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError, match="NOUS_KERNEL_ENDPOINT"):
        _verify_kernel_ready()


def test_kernel_readiness_can_be_omitted_in_development(monkeypatch):
    from nous_runtime.cli.runtime_api import _verify_kernel_ready

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "development")
    monkeypatch.delenv("NOUS_KERNEL_ENDPOINT", raising=False)

    _verify_kernel_ready()


def test_unhealthy_kernel_fails_closed_in_production(monkeypatch):
    import nous_runtime.cli.runtime_api as runtime_api

    async def unhealthy(_endpoint):
        return {
            "state": "READY",
            "node": {"connection": "DISCONNECTED"},
        }

    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    monkeypatch.setattr(runtime_api, "_probe_kernel", unhealthy)

    with pytest.raises(RuntimeError, match="unhealthy Runtime"):
        runtime_api._verify_kernel_ready()


@pytest.mark.integration
def test_public_model_free_api_starts_strict_without_kernel(tmp_path):
    import json
    import os
    from pathlib import Path
    import socket
    import subprocess
    import sys
    import tempfile
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    workspace = tmp_path / "workspace"
    config = workspace / ".nous" / "providers.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "never-load": {
                    "kind": "openai-compatible",
                    "model": "not-invoked",
                    "endpoint": "https://provider.example.test/v1/chat/completions",
                    "credential_ref": "env:APEIR_FAKE_ONLY_NEVER_RESOLVE",
                }
            }
        )
    )
    original = config.read_bytes()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = dict(os.environ)
    environment.pop("NOUS_KERNEL_ENDPOINT", None)
    environment.pop("NOUS_NO_INTELLIGENCE", None)
    environment.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "NOUS_WORKSPACE_ROOT": str(workspace),
            "NOUS_DATA_DIR": str(tmp_path / "capabilities"),
            "APEIR_STATE_DIR": str(tmp_path / "state"),
            "NOUS_RUNTIME_MODE": "production",
            "NOUS_API_TOKEN": "APEIR_FAKE_ONLY_STARTUP_SESSION",
        }
    )

    def call(path, body=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + environment["NOUS_API_TOKEN"]
        request = Request(
            f"http://127.0.0.1:{port}" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nous_runtime.cli.main",
                "--no-intelligence",
                "runtime-api",
                "start",
                "--port",
                str(port),
            ],
            cwd=workspace,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail("Public model-free API exited: " + log.read())
                try:
                    health = call("/api/v1/health/detailed")["data"]
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        pytest.fail("Public model-free API did not become reachable")
                    time.sleep(0.02)
            assert health["intelligence_mode"] == "disabled"
            assert health["provider_count"] == 0
            assert health["kernel"]["ready"] is False
            assert call("/api/v1/workspace/status")["data"]["path"] == str(workspace)
            with pytest.raises(HTTPError) as denied:
                call("/api/v1/providers", authenticated=False)
            assert denied.value.code == 401
            denied.value.close()
            result = call(
                "/api/v1/models/test", {"model_id": "never-load/not-invoked"}
            )["data"]
            assert result["healthy"] is False
            assert result["tokens_used"] is None and result["cost_usd"] is None
            assert config.read_bytes() == original
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
