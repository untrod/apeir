"""Minimal authenticated HTTP adapter for the Runtime API route table."""

from __future__ import annotations

import ipaddress
import json
import os
import ssl
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from nous_runtime.api.routes import route_server

_READ_RATE_MULTIPLIER = 5


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, max_request_bytes: int = 1_048_576, requests_per_minute: int = 120):
        super().__init__(server_address, handler_class)
        self.max_request_bytes = max_request_bytes
        self.requests_per_minute = requests_per_minute
        self._rate_lock = threading.Lock()
        self._rate: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow_request(self, source: str, bucket: str = "interaction") -> bool:
        """Rate-limit read polling independently from interactive effects.

        The desktop uses authenticated GET polling for status and events. If
        those requests share one counter with POST/PUT/PATCH/DELETE, two open
        windows can consume the entire budget and prevent the user from
        sending a single chat request. Read traffic therefore gets a separate,
        bounded bucket while interactive operations retain the configured
        limit.
        """
        now = time.monotonic()
        normalized_bucket = "read" if bucket == "read" else "interaction"
        limit = self.requests_per_minute * (
            _READ_RATE_MULTIPLIER if normalized_bucket == "read" else 1
        )
        with self._rate_lock:
            entries = self._rate[(source, normalized_bucket)]
            while entries and now - entries[0] >= 60:
                entries.popleft()
            if len(entries) >= limit:
                return False
            entries.append(now)
            return True


class RuntimeAPIHandler(BaseHTTPRequestHandler):
    server_version = "NousRuntimeAPI/1.0"

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        from nous_runtime.control_plane.auth import add_cors_headers

        headers: dict[str, str] = {}
        add_cors_headers(headers, self.headers.get("Origin"))
        if "Access-Control-Allow-Origin" not in headers:
            self._write(
                403,
                {
                    "ok": False,
                    "error": {
                        "code": "NOUS_CORS_DENIED",
                        "message": "Origin is not allowed.",
                    },
                },
            )
            return
        self.send_response(204)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _dispatch(self, method: str) -> None:
        server: RuntimeHTTPServer = self.server  # type: ignore[assignment]
        rate_bucket = "read" if method == "GET" else "interaction"
        if not server.allow_request(self.client_address[0], rate_bucket):
            self._write(429, {"ok": False, "error": {"code": "NOUS_RATE_LIMITED", "message": "Request rate limit exceeded."}})
            return
        parsed = urlsplit(self.path)

        # WebSocket upgrade detection
        headers = {}
        for name, value in self.headers.items():
            headers[name.lower()] = value
        if headers.get("upgrade", "").lower() == "websocket":
            self._handle_websocket_upgrade(parsed.path, headers)
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        query_token = any(name.lower() in {"token", "api_key", "access_token"} for name in query)
        params = {name: values[-1] for name, values in query.items() if values and name.lower() not in {"token", "api_key", "access_token"}}
        try:
            body = self._read_body()
        except ValueError as exc:
            self._write(413 if "large" in str(exc) else 400, {"ok": False, "error": {"code": "NOUS_INVALID_REQUEST", "message": str(exc)}})
            return
        auth_headers = {name.lower(): value for name, value in self.headers.items() if name.lower() in {"authorization", "x-auth-token"}}
        try:
            loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            loopback = False
        response = route_server(
            method,
            parsed.path,
            body=body,
            params=params,
            auth={
                "headers": auth_headers,
                "query_token": query_token,
                "loopback": loopback,
            },
        )
        self._write(self._status(response), response)

    def _handle_websocket_upgrade(self, path: str, headers: dict[str, str]) -> None:
        """Attempt WebSocket upgrade for /api/v1/events."""
        try:
            from nous_runtime.control_plane.websocket import handle_websocket_upgrade
            if handle_websocket_upgrade(path, headers, self.request):
                # Upgrade handled — the WebSocket handler takes over the connection
                return
        except ImportError:
            pass
        # Not a valid WebSocket upgrade
        self._write(400, {"ok": False, "error": {"code": "NOUS_INVALID_REQUEST", "message": "WebSocket upgrade failed"}})

    def _read_body(self) -> dict[str, Any] | None:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        server: RuntimeHTTPServer = self.server  # type: ignore[assignment]
        if length < 0 or length > server.max_request_bytes:
            raise ValueError("Request body is too large.")
        if length == 0:
            return None
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise ValueError("Content-Type must be application/json.")
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Request body is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Request JSON must be an object.")
        return data

    def _write(self, status: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin:
                from nous_runtime.control_plane.auth import add_cors_headers

                headers: dict[str, str] = {}
                add_cors_headers(headers, origin)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Loopback health probes may close once readiness is known. This is
            # a normal client disconnect and must not look like a Runtime fault.
            return

    @staticmethod
    def _status(response: dict[str, Any]) -> int:
        if response.get("ok"):
            return 200
        error = response.get("error") or {}
        code = str(error.get("code") if isinstance(error, dict) else "")
        if code in {"NOUS_AUTH_REQUIRED", "NOUS_UNAUTHORIZED", "NOUS_UNAUTHENTICATED"}:
            return 401
        if code in {"NOUS_FORBIDDEN", "NOUS_GOVERNANCE_DENIED", "NOUS_APPROVAL_REQUIRED"}:
            return 403
        if code == "NOUS_INVALID_REQUEST":
            return 400
        return 500


def create_server(host: str = "127.0.0.1", port: int = 8770, *, ssl_context: ssl.SSLContext | None = None, trusted_private_transport: bool = False, max_request_bytes: int = 1_048_576, requests_per_minute: int = 120) -> RuntimeHTTPServer:
    address = ipaddress.ip_address(host)
    remote = not address.is_loopback
    if remote and not os.environ.get("NOUS_API_TOKEN"):
        raise RuntimeError("NOUS_API_TOKEN is required for remote API binding")
    if remote and ssl_context is None and not trusted_private_transport:
        raise RuntimeError("remote API binding requires TLS or an explicitly trusted private transport")
    server = RuntimeHTTPServer((host, port), RuntimeAPIHandler, max_request_bytes=max_request_bytes, requests_per_minute=requests_per_minute)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    return server
