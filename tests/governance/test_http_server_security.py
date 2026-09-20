from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from nous_runtime.api.server import RuntimeAPIHandler, create_server


def request(url, *, token="", data=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=5)


def test_http_server_authenticates_and_serves_localhost(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "test-server-token")
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with request(base + "/api/v1/health") as response:
            assert json.loads(response.read())["ok"] is True
        with pytest.raises(urllib.error.HTTPError) as denied:
            request(base + "/api/v1/status")
        assert denied.value.code == 401
        denied.value.close()
        with request(base + "/api/v1/status", token="test-server-token") as response:
            assert json.loads(response.read())["ok"] is True
        with pytest.raises(urllib.error.HTTPError) as query_denied:
            request(base + "/api/v1/status?token=test-server-token")
        assert query_denied.value.code == 401
        query_denied.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_server_enforces_request_size(monkeypatch):
    monkeypatch.setenv("NOUS_API_TOKEN", "test-server-token")
    server = create_server(port=0, max_request_bytes=16)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            request(f"http://127.0.0.1:{server.server_port}/api/runtime/run", token="test-server-token", data={"user_input": "x" * 100})
        assert denied.value.code == 413
        denied.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_read_polling_cannot_exhaust_interactive_request_budget():
    server = create_server(port=0, requests_per_minute=1)
    try:
        for _ in range(5):
            assert server.allow_request("127.0.0.1", "read") is True
        assert server.allow_request("127.0.0.1", "read") is False

        assert server.allow_request("127.0.0.1", "interaction") is True
        assert server.allow_request("127.0.0.1", "interaction") is False
    finally:
        server.server_close()


def test_remote_binding_requires_token_and_encrypted_or_trusted_transport(monkeypatch):
    monkeypatch.delenv("NOUS_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="NOUS_API_TOKEN"):
        create_server("0.0.0.0", 0)
    monkeypatch.setenv("NOUS_API_TOKEN", "configured-token")
    with pytest.raises(RuntimeError, match="TLS"):
        create_server("0.0.0.0", 0)
    server = create_server("0.0.0.0", 0, trusted_private_transport=True)
    server.server_close()


def test_response_writer_ignores_normal_client_disconnects():
    class DisconnectedWriter:
        def write(self, _payload):
            raise ConnectionAbortedError("client closed the loopback connection")

    handler = RuntimeAPIHandler.__new__(RuntimeAPIHandler)
    handler.headers = {}
    handler.wfile = DisconnectedWriter()
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None

    handler._write(200, {"ok": True})
