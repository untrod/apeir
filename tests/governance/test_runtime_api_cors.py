from __future__ import annotations

import threading
import urllib.error
import urllib.request

import pytest

from nous_runtime.api.server import create_server


@pytest.fixture
def runtime_api():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_runtime_api_accepts_tauri_preflight(runtime_api) -> None:
    request = urllib.request.Request(
        f"{runtime_api}/api/v1/health",
        method="OPTIONS",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        },
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == (
            "http://tauri.localhost"
        )
        assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_runtime_api_adds_cors_headers_for_tauri(runtime_api) -> None:
    request = urllib.request.Request(
        f"{runtime_api}/api/v1/health",
        headers={"Origin": "http://tauri.localhost"},
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers["Access-Control-Allow-Origin"] == (
            "http://tauri.localhost"
        )
        assert response.headers["Vary"] == "Origin"


def test_runtime_api_rejects_disallowed_preflight(runtime_api) -> None:
    request = urllib.request.Request(
        f"{runtime_api}/api/v1/health",
        method="OPTIONS",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )

    with pytest.raises(urllib.error.HTTPError) as denied:
        urllib.request.urlopen(request, timeout=5)
    assert denied.value.code == 403
    denied.value.close()
