# -*- coding: utf-8 -*-
"""Fault-injection tests for the configured device-agent network authority."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from remote_terminal import device_transport


class _Response:
    def __init__(self, body=b"{}", *, status=200, headers=None):
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = headers or {"Content-Type": "application/json"}

    def getcode(self):
        return self.status

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Opener:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_device_request_is_bound_to_configured_authority(monkeypatch):
    opener = _Opener(_Response())
    monkeypatch.setattr(device_transport, "_OPENER", opener)

    with pytest.raises(device_transport.DeviceTransportError) as exc:
        device_transport.request(
            "http://other-device:8765/observe",
            expected_host="configured-device",
            expected_port=8765,
        )

    assert exc.value.code == "DEVICE_TARGET_MISMATCH"
    assert opener.calls == []


def test_device_json_request_disables_proxy_and_bounds_response(monkeypatch):
    body = json.dumps({"result": "ok"}).encode()
    opener = _Opener(_Response(body, headers={"Content-Length": str(len(body))}))
    monkeypatch.setattr(device_transport, "_OPENER", opener)

    result = device_transport.request_json(
        "http://phone.lan:8765/act",
        {"action": "home"},
        expected_host="phone.lan",
        expected_port=8765,
        timeout=5,
        headers={"X-Auth-Token": "secret-device-token"},
    )

    assert result == {"result": "ok"}
    request, timeout = opener.calls[0]
    assert request.get_method() == "POST"
    assert timeout == 5.0
    assert request.get_header("X-auth-token") == "secret-device-token"


def test_device_redirect_is_blocked_and_secret_is_not_disclosed(monkeypatch):
    error = urllib.error.HTTPError(
        "http://phone.lan:8765/observe",
        302,
        "secret-device-token",
        {"Location": "http://attacker.invalid/"},
        None,
    )
    monkeypatch.setattr(device_transport, "_OPENER", _Opener(error))

    with pytest.raises(device_transport.DeviceTransportError) as exc:
        device_transport.request(
            "http://phone.lan:8765/observe",
            expected_host="phone.lan",
            expected_port=8765,
            headers={"X-Auth-Token": "secret-device-token"},
        )

    assert exc.value.code == "DEVICE_REDIRECT_BLOCKED"
    assert "secret-device-token" not in str(exc.value)


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"x", headers={"Content-Length": "101"}),
        _Response(b"x" * 101),
    ],
)
def test_device_response_limit_fails_closed(monkeypatch, response):
    monkeypatch.setattr(device_transport, "_OPENER", _Opener(response))

    with pytest.raises(device_transport.DeviceTransportError) as exc:
        device_transport.request(
            "http://device:9000/data",
            expected_host="device",
            expected_port=9000,
            max_response_bytes=100,
        )

    assert exc.value.code == "DEVICE_RESPONSE_TOO_LARGE"


def test_device_wrapped_timeout_has_stable_code(monkeypatch):
    wrapped = urllib.error.URLError(TimeoutError("private timeout detail"))
    monkeypatch.setattr(device_transport, "_OPENER", _Opener(wrapped))

    with pytest.raises(device_transport.DeviceTransportError) as exc:
        device_transport.request(
            "http://device:9000/data",
            expected_host="device",
            expected_port=9000,
        )

    assert exc.value.code == "DEVICE_TIMEOUT"
    assert "private" not in str(exc.value)
