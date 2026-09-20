# -*- coding: utf-8 -*-
"""Bounded HTTP authority for configured Nous device-agent protocols.

This boundary intentionally permits private/LAN targets. It is not a public
web-fetch fallback: every request must be bound to the configured host/port,
redirects are disabled, credentials stay in headers, and response bytes are
bounded before decoding.
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 5_242_880
MAX_REQUEST_BYTES = 1_048_576
_ALLOWED_METHODS = {"GET", "POST"}
_FORBIDDEN_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


class DeviceTransportError(RuntimeError):
    """A stable, credential-safe device protocol failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeviceResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DeviceTransportError(
                "DEVICE_RESPONSE_INVALID_JSON",
                "The device agent returned an invalid JSON response.",
            ) from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirect(),
)


def request(
    url: str,
    *,
    expected_host: str,
    expected_port: int,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10,
    max_response_bytes: int = 1_048_576,
) -> DeviceResponse:
    """Call one configured device endpoint with redirects and proxies disabled."""
    normalized_method = str(method or "GET").upper()
    if normalized_method not in _ALLOWED_METHODS:
        raise DeviceTransportError("DEVICE_METHOD_BLOCKED", "Only GET and POST are supported.")
    if timeout < 1 or timeout > 120:
        raise DeviceTransportError("DEVICE_TIMEOUT_INVALID", "Timeout must be between 1 and 120 seconds.")
    if body is not None and len(body) > MAX_REQUEST_BYTES:
        raise DeviceTransportError("DEVICE_REQUEST_TOO_LARGE", "The device request exceeds 1 MiB.")
    limit = max(1, min(int(max_response_bytes), MAX_RESPONSE_BYTES))
    parts = urlsplit(str(url or ""))
    scheme = parts.scheme.lower()
    actual_port = parts.port or (443 if scheme == "https" else 80)
    configured_host = str(expected_host or "").rstrip(".").lower()
    actual_host = (parts.hostname or "").rstrip(".").lower()
    if (
        scheme not in {"http", "https"}
        or not actual_host
        or parts.username
        or parts.password
        or actual_host != configured_host
        or actual_port != int(expected_port)
    ):
        raise DeviceTransportError(
            "DEVICE_TARGET_MISMATCH",
            "The device endpoint does not match the configured device authority.",
        )
    safe_headers: dict[str, str] = {}
    for name, value in (headers or {}).items():
        normalized = str(name).strip()
        if not normalized or normalized.lower() in _FORBIDDEN_HEADERS:
            raise DeviceTransportError("DEVICE_HEADER_BLOCKED", "A transport-controlled header was rejected.")
        if any(char in normalized or char in str(value) for char in "\r\n"):
            raise DeviceTransportError("DEVICE_HEADER_INVALID", "A device header contains invalid characters.")
        safe_headers[normalized] = str(value)[:4096]
    payload = body if normalized_method == "POST" else None
    req = urllib.request.Request(url, data=payload, headers=safe_headers, method=normalized_method)
    try:
        with _OPENER.open(req, timeout=float(timeout)) as response:
            status = int(getattr(response, "status", response.getcode()))
            response_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
            declared = response_headers.get("content-length", "")
            if declared:
                try:
                    if int(declared) > limit:
                        raise DeviceTransportError(
                            "DEVICE_RESPONSE_TOO_LARGE",
                            "The device response exceeds the configured byte limit.",
                        )
                except ValueError as exc:
                    raise DeviceTransportError(
                        "DEVICE_RESPONSE_HEADER_INVALID",
                        "The device response has an invalid Content-Length header.",
                    ) from exc
            data = response.read(limit + 1)
            if len(data) > limit:
                raise DeviceTransportError(
                    "DEVICE_RESPONSE_TOO_LARGE",
                    "The device response exceeds the configured byte limit.",
                )
            if status < 200 or status >= 300:
                raise DeviceTransportError("DEVICE_HTTP_STATUS", f"The device agent returned HTTP {status}.")
            return DeviceResponse(status, response_headers, data)
    except DeviceTransportError:
        raise
    except urllib.error.HTTPError as exc:
        try:
            if 300 <= exc.code < 400:
                raise DeviceTransportError("DEVICE_REDIRECT_BLOCKED", "Device redirects are not allowed.") from exc
            raise DeviceTransportError("DEVICE_HTTP_STATUS", f"The device agent returned HTTP {exc.code}.") from exc
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise DeviceTransportError("DEVICE_TIMEOUT", "The device request timed out.") from exc
        if isinstance(reason, ssl.SSLError):
            raise DeviceTransportError("DEVICE_TLS_FAILED", "Device TLS verification failed.") from exc
        raise DeviceTransportError("DEVICE_CONNECT_FAILED", "The configured device agent could not be reached.") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise DeviceTransportError("DEVICE_TIMEOUT", "The device request timed out.") from exc
    except OSError as exc:
        raise DeviceTransportError("DEVICE_CONNECT_FAILED", "The configured device agent could not be reached.") from exc


def request_json(
    url: str,
    payload: Any | None,
    *,
    expected_host: str,
    expected_port: int,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    method: str = "POST",
    max_response_bytes: int = 1_048_576,
) -> Any:
    body = None
    request_headers = dict(headers or {})
    if method.upper() == "POST":
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    response = request(
        url,
        expected_host=expected_host,
        expected_port=expected_port,
        method=method,
        body=body,
        headers=request_headers,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    return response.json()


__all__ = [
    "DeviceResponse",
    "DeviceTransportError",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "request",
    "request_json",
]
