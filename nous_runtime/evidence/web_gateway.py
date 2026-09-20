# -*- coding: utf-8 -*-
"""Governed, SSRF-resistant HTTP gateway for research evidence."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from nous_runtime.artifact import ArtifactManager, ArtifactType
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.evidence.injection_guard import InjectionGuard
from nous_runtime.evidence.source_registry import SourceRecord, SourceRegistry, SourceType, TrustTier
from nous_runtime.evidence.snapshots import SnapshotStore

_ALLOWED_METHODS = {"GET", "HEAD", "POST"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}
_FORBIDDEN_REQUEST_HEADERS = _SENSITIVE_HEADERS | {"host", "content-length", "connection", "transfer-encoding", "upgrade"}
_SAFE_RESPONSE_HEADERS = {"content-type", "content-length", "content-encoding", "etag", "last-modified", "cache-control", "location"}
_SENSITIVE_QUERY = re.compile(r"(?i)(token|key|secret|password|signature|authorization|credential|^(?:q|p|query|search)$)")
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata.azure.internal", "instance-data", "kubernetes.default"}
_TEXT_MIME = ("text/", "application/json", "application/ld+json", "application/xml", "application/xhtml+xml", "application/javascript")


class _EgressRateLimiter:
    """Process-wide fixed-window limiter keyed by destination host."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, limit: int, now: float) -> bool:
        if limit <= 0:
            return True
        with self._lock:
            if len(self._windows) > 1_024:
                self._windows = {
                    host: window
                    for host, window in self._windows.items()
                    if now - window[0] < 60
                }
            if key not in self._windows and len(self._windows) >= 4_096:
                return False
            started, count = self._windows.get(key, (now, 0))
            if now - started >= 60:
                started, count = now, 0
            if count >= limit:
                self._windows[key] = (started, count)
                return False
            self._windows[key] = (started, count + 1)
            return True


_EGRESS_RATE_LIMITER = _EgressRateLimiter()


class WebGatewayError(RuntimeError):
    """Safe network failure whose message contains no credential material."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class WebRequest:
    url: str = ""
    method: str = "GET"
    request_id: str = field(default_factory=lambda: f"netreq_{uuid.uuid4().hex[:12]}")
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    headers_ref: str = ""
    body_ref: str = ""
    timeout_seconds: int = 30
    max_size_bytes: int = 1_048_576
    max_response_bytes: int = 0
    credential_ref: str = ""
    network_scope: str = "public_internet"
    task_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    approval_requirement: str = "required"
    max_redirects: int = 5
    max_retries: int = 0
    retry_backoff_ms: int = 100
    cancel_check: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    @property
    def response_limit(self) -> int:
        requested = self.max_response_bytes or self.max_size_bytes
        return max(1, min(int(requested), WebGateway.MAX_CONTENT_SIZE))


@dataclass
class WebResponse:
    ok: bool = False
    url: str = ""
    final_url: str = ""
    status_code: int = 0
    content: str = ""
    content_hash: str = ""
    content_type: str = ""
    size_bytes: int = 0
    snapshot_id: str = ""
    snapshot_artifact_id: str = ""
    source_id: str = ""
    injection_scan_result: Any = None
    retrieved_at: str = ""
    response_headers: dict[str, str] = field(default_factory=dict)
    redirect_chain: list[str] = field(default_factory=list)
    run_id: str = ""
    request_id: str = ""
    error_code: str = ""
    error_message: str = ""
    attempt_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        scan = self.injection_scan_result
        if scan is not None:
            values["injection_scan_result"] = asdict(scan) if is_dataclass(scan) else scan
        return values


@dataclass
class _TransportResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, resolved_ip: str, timeout: float) -> None:
        self._resolved_ip = resolved_ip
        super().__init__(host, port=port, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection((self._resolved_ip, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, resolved_ip: str, timeout: float) -> None:
        self._resolved_ip = resolved_ip
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())

    def connect(self) -> None:
        raw = socket.create_connection((self._resolved_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class WebGateway:
    """Single Runtime HTTP boundary for public-internet research requests."""
    ALLOWED_DOMAINS: list[str] = []
    BLOCKED_DOMAINS: list[str] = []
    MAX_CONTENT_SIZE: int = 5_242_880
    MAX_REQUEST_BODY: int = 1_048_576

    def __init__(
        self,
        injection_guard: InjectionGuard | None = None,
        snapshot_store: SnapshotStore | None = None,
        source_registry: SourceRegistry | None = None,
        *,
        artifact_manager: ArtifactManager | None = None,
        event_stream: EventStream | None = None,
        resolver: Callable[[str, int], list[str]] | None = None,
        transport: Callable[..., _TransportResponse] | None = None,
        rate_limit_per_minute: int = 120,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._guard = injection_guard or InjectionGuard()
        self._snapshots = snapshot_store
        self._sources = source_registry
        self._artifacts = artifact_manager
        self._events = event_stream
        self._resolver = resolver or self._resolve_public_addresses
        self._transport = transport
        self._rate_limit = max(0, int(rate_limit_per_minute))
        self._clock = clock
        self._sleeper = sleeper

    def fetch(self, request: WebRequest) -> WebResponse:
        if not isinstance(request, WebRequest):
            raise TypeError("request must be a WebRequest")
        request.method = str(request.method or "GET").upper()
        request.run_id = request.run_id or f"network-fetch-{hashlib.sha256(request.request_id.encode()).hexdigest()[:16]}"
        safe_original = _safe_url(request.url)
        started = self._clock()
        self._ensure_run(request)
        try:
            self._validate_request(request)
            deadline = started + float(request.timeout_seconds)
            body = self._encode_body(request)
            headers = self._request_headers(request)
            transport = self._follow_redirects(request, headers, body, deadline)
            elapsed_ms = round((self._clock() - started) * 1000, 3)
            return self._record_success(request, safe_original, transport, elapsed_ms)
        except WebGatewayError as exc:
            self._emit(request, "network.failed", {"request_id": request.request_id, "code": exc.code, "message": str(exc)})
            self._finish_run(request, RunState.FAILED, error_code=exc.code)
            return WebResponse(ok=False, url=safe_original, final_url=safe_original, run_id=request.run_id, request_id=request.request_id, error_code=exc.code, error_message=str(exc), retrieved_at=_utc_now())
        except Exception:
            message = "The network request failed before a verified response was received."
            self._emit(request, "network.failed", {"request_id": request.request_id, "code": "NETWORK_TRANSPORT_FAILED", "message": message})
            self._finish_run(request, RunState.FAILED, error_code="NETWORK_TRANSPORT_FAILED")
            return WebResponse(ok=False, url=safe_original, final_url=safe_original, run_id=request.run_id, request_id=request.request_id, error_code="NETWORK_TRANSPORT_FAILED", error_message=message, retrieved_at=_utc_now())

    def _validate_request(self, request: WebRequest) -> None:
        if request.method not in _ALLOWED_METHODS:
            raise WebGatewayError("NETWORK_METHOD_BLOCKED", "Only GET, HEAD, and POST are supported.")
        if request.network_scope != "public_internet":
            raise WebGatewayError("NETWORK_SCOPE_BLOCKED", "Only the public_internet network scope is supported.")
        if request.timeout_seconds < 1 or request.timeout_seconds > 120:
            raise WebGatewayError("NETWORK_TIMEOUT_INVALID", "Timeout must be between 1 and 120 seconds.")
        if request.max_redirects < 0 or request.max_redirects > 10:
            raise WebGatewayError("NETWORK_REDIRECT_LIMIT_INVALID", "Redirect limit must be between 0 and 10.")
        if request.max_retries < 0 or request.max_retries > 2:
            raise WebGatewayError("NETWORK_RETRY_LIMIT_INVALID", "Retry limit must be between 0 and 2.")
        if request.retry_backoff_ms < 0 or request.retry_backoff_ms > 2_000:
            raise WebGatewayError("NETWORK_RETRY_BACKOFF_INVALID", "Retry backoff must be between 0 and 2000 milliseconds.")
        if request.method == "POST" and request.max_retries:
            raise WebGatewayError("NETWORK_RETRY_UNSAFE", "POST requests are not retried without an idempotency contract.")
        self._check_cancelled(request)
        self._validate_target(request.url)

    def _request_headers(self, request: WebRequest) -> dict[str, str]:
        headers = {
            "User-Agent": "Nous-Runtime/2.0 ResearchGateway",
            "Accept": "text/html,application/json,text/plain,application/xml,application/pdf,*/*;q=0.5",
            "Accept-Encoding": "identity",
        }
        for name, value in request.headers.items():
            normalized = str(name).strip()
            if not normalized or normalized.lower() in _FORBIDDEN_REQUEST_HEADERS:
                raise WebGatewayError("NETWORK_HEADER_BLOCKED", "Sensitive and connection-controlled headers must use the credential boundary.")
            if "\r" in normalized or "\n" in normalized or "\r" in str(value) or "\n" in str(value):
                raise WebGatewayError("NETWORK_HEADER_INVALID", "Request headers contain invalid characters.")
            headers[normalized] = str(value)[:4096]
        if request.credential_ref:
            from nous_runtime.provider.credentials import resolve_credential
            try:
                credential = resolve_credential(request.credential_ref)
            except Exception as exc:
                raise WebGatewayError("NETWORK_CREDENTIAL_UNAVAILABLE", "The configured credential reference could not be resolved.") from exc
            if not credential:
                raise WebGatewayError("NETWORK_CREDENTIAL_UNAVAILABLE", "The configured credential reference is unavailable.")
            headers["Authorization"] = f"Bearer {credential}"
        return headers

    def _encode_body(self, request: WebRequest) -> bytes:
        if request.body is None:
            return b""
        if request.method != "POST":
            raise WebGatewayError("NETWORK_BODY_BLOCKED", "Only POST requests may contain a body.")
        if isinstance(request.body, bytes):
            body = request.body
        elif isinstance(request.body, (dict, list)):
            body = json.dumps(request.body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request.headers.setdefault("Content-Type", "application/json")
        else:
            body = str(request.body).encode("utf-8")
        if len(body) > self.MAX_REQUEST_BODY:
            raise WebGatewayError("NETWORK_REQUEST_TOO_LARGE", "The request body exceeds 1 MiB.")
        return body

    def _follow_redirects(
        self,
        request: WebRequest,
        headers: dict[str, str],
        body: bytes,
        deadline: float,
    ) -> tuple[str, _TransportResponse, list[str], str, int]:
        current, method, current_body = request.url, request.method, body
        redirects: list[str] = []
        visited: set[str] = set()
        original_origin = _origin(request.url)
        attempt_count = 0
        for redirect_count in range(request.max_redirects + 1):
            self._check_cancelled(request)
            if current in visited:
                raise WebGatewayError("NETWORK_REDIRECT_LOOP", "A redirect loop was detected.")
            visited.add(current)
            parts, addresses = self._validate_target(current)
            response = None
            connected_ip = ""
            last_error: BaseException | None = None
            for retry_index in range(request.max_retries + 1):
                for address in addresses:
                    self._check_cancelled(request)
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise WebGatewayError("NETWORK_TIMEOUT", "The total network request time budget was exhausted.")
                    host = (parts.hostname or "").lower()
                    if not _EGRESS_RATE_LIMITER.allow(host, self._rate_limit, self._clock()):
                        raise WebGatewayError("NETWORK_RATE_LIMITED", "The destination request rate limit was exceeded.")
                    attempt_count += 1
                    try:
                        response = self._open_once(
                            method,
                            current,
                            headers,
                            current_body,
                            remaining,
                            request.response_limit,
                            address,
                        )
                        connected_ip = address
                        break
                    except WebGatewayError:
                        raise
                    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
                        last_error = exc
                if response is not None:
                    break
                code, message = self._classify_transport_error(last_error)
                retryable = code in {
                    "NETWORK_TIMEOUT",
                    "NETWORK_CONNECTION_RESET",
                    "NETWORK_CONNECT_FAILED",
                }
                if retry_index >= request.max_retries or not retryable:
                    raise WebGatewayError(code, message) from last_error
                delay = min(request.retry_backoff_ms * (2 ** retry_index) / 1000.0, 2.0)
                if self._clock() + delay >= deadline:
                    raise WebGatewayError("NETWORK_TIMEOUT", "The total network request time budget was exhausted.")
                self._emit(request, "network.retry_scheduled", {
                    "request_id": request.request_id,
                    "retry_index": retry_index + 1,
                    "delay_ms": round(delay * 1000),
                    "error_code": self._classify_transport_error(last_error)[0],
                })
                if delay:
                    self._sleeper(delay)
            if response is None:
                code, message = self._classify_transport_error(last_error)
                raise WebGatewayError(code, message) from last_error
            self._emit(request, "network.connected", {
                "request_id": request.request_id,
                "host": parts.hostname or "",
                "resolved_ip": connected_ip,
                "redirect_index": redirect_count,
                "attempt_count": attempt_count,
            })
            if response.status_code not in _REDIRECT_STATUSES:
                return current, response, redirects, connected_ip, attempt_count
            location = response.headers.get("location", "").strip()
            if not location:
                raise WebGatewayError("NETWORK_REDIRECT_INVALID", "Redirect response did not include a Location header.")
            if redirect_count >= request.max_redirects:
                raise WebGatewayError("NETWORK_REDIRECT_LIMIT", "The redirect limit was exceeded.")
            target = urljoin(current, location)
            self._validate_target(target)
            if request.credential_ref and _origin(target) != original_origin:
                raise WebGatewayError("NETWORK_CREDENTIAL_REDIRECT_BLOCKED", "Credentialed requests cannot redirect to a different origin.")
            redirects.append(_safe_url(target))
            current = target
            if response.status_code == 303 or (response.status_code in {301, 302} and method == "POST"):
                method, current_body = "GET", b""
        raise WebGatewayError("NETWORK_REDIRECT_LIMIT", "The redirect limit was exceeded.")

    @staticmethod
    def _classify_transport_error(error: BaseException | None) -> tuple[str, str]:
        if isinstance(error, ssl.SSLError):
            return "NETWORK_TLS_FAILED", "TLS negotiation or certificate verification failed."
        if isinstance(error, (TimeoutError, socket.timeout)):
            return "NETWORK_TIMEOUT", "The network request timed out."
        if isinstance(error, ConnectionResetError):
            return "NETWORK_CONNECTION_RESET", "The remote peer reset the connection."
        if isinstance(error, http.client.HTTPException):
            return "NETWORK_PROTOCOL_FAILED", "The remote endpoint returned an invalid HTTP response."
        return "NETWORK_CONNECT_FAILED", "No validated public address returned a response."

    @staticmethod
    def _check_cancelled(request: WebRequest) -> None:
        if request.cancel_check is None:
            return
        try:
            cancelled = bool(request.cancel_check())
        except Exception as exc:
            raise WebGatewayError("NETWORK_CANCELLATION_CHECK_FAILED", "The cancellation state could not be verified.") from exc
        if cancelled:
            raise WebGatewayError("NETWORK_CANCELLED", "The network request was cancelled.")

    def _validate_target(self, url: str):
        try:
            parts = urlsplit(str(url or ""))
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise WebGatewayError("NETWORK_URL_INVALID", "The URL is malformed.") from exc
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"}:
            raise WebGatewayError("NETWORK_SCHEME_BLOCKED", "Only HTTP and HTTPS URLs are allowed.")
        if not parts.hostname or parts.username or parts.password:
            raise WebGatewayError("NETWORK_URL_INVALID", "URLs must contain a hostname and cannot contain credentials.")
        host = parts.hostname.rstrip(".").lower()
        if host in _BLOCKED_HOSTS or host.endswith((".localhost", ".local", ".internal")):
            raise WebGatewayError("NETWORK_SSRF_BLOCKED", "Local and metadata hostnames are blocked.")
        if any(host == item or host.endswith("." + item) for item in self.BLOCKED_DOMAINS):
            raise WebGatewayError("NETWORK_DOMAIN_BLOCKED", "The destination domain is blocked.")
        if self.ALLOWED_DOMAINS and not any(host == item or host.endswith("." + item) for item in self.ALLOWED_DOMAINS):
            raise WebGatewayError("NETWORK_DOMAIN_NOT_ALLOWED", "The destination is outside the configured allowlist.")
        try:
            addresses = self._resolver(host, port)
        except Exception as exc:
            raise WebGatewayError("NETWORK_DNS_FAILED", "The destination hostname could not be resolved.") from exc
        if not addresses:
            raise WebGatewayError("NETWORK_DNS_FAILED", "The destination hostname resolved to no addresses.")
        validated = []
        for value in addresses:
            try:
                address = ipaddress.ip_address(str(value).split("%", 1)[0])
            except ValueError as exc:
                raise WebGatewayError("NETWORK_DNS_INVALID", "DNS returned an invalid address.") from exc
            if not address.is_global:
                raise WebGatewayError("NETWORK_SSRF_BLOCKED", "The destination resolved to a non-public address.")
            validated.append(str(address))
        return parts, sorted(set(validated))

    @staticmethod
    def _resolve_public_addresses(host: str, port: int) -> list[str]:
        return sorted({result[4][0] for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})

    def _open_once(self, method: str, url: str, headers: dict[str, str], body: bytes, timeout: float, max_bytes: int, resolved_ip: str) -> _TransportResponse:
        if self._transport is not None:
            return self._transport(method=method, url=url, headers=dict(headers), body=body, timeout=timeout, max_bytes=max_bytes, resolved_ip=resolved_ip)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        connection_cls = _PinnedHTTPSConnection if parts.scheme.lower() == "https" else _PinnedHTTPConnection
        connection = connection_cls(parts.hostname or "", port, resolved_ip, timeout)
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        request_headers = dict(headers)
        request_headers["Host"] = _host_header(parts.hostname or "", port, parts.scheme.lower())
        try:
            connection.request(method, path, body=body or None, headers=request_headers)
            response = connection.getresponse()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            content_length = response_headers.get("content-length", "")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise WebGatewayError("NETWORK_RESPONSE_TOO_LARGE", "The response Content-Length exceeds the configured limit.")
                except ValueError as exc:
                    raise WebGatewayError("NETWORK_HEADER_INVALID", "Response Content-Length is invalid.") from exc
            encoding = response_headers.get("content-encoding", "").strip().lower()
            if encoding not in {"", "identity"}:
                raise WebGatewayError("NETWORK_ENCODING_BLOCKED", "Compressed responses are blocked to prevent decompression bombs.")
            chunks, total = [], 0
            if method != "HEAD":
                while True:
                    chunk = response.read(min(65_536, max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise WebGatewayError("NETWORK_RESPONSE_TOO_LARGE", "The response exceeded the configured byte limit.")
                    chunks.append(chunk)
            return _TransportResponse(response.status, response_headers, b"".join(chunks))
        finally:
            connection.close()

    def _record_success(self, request: WebRequest, safe_original: str, result: tuple[str, _TransportResponse, list[str], str, int], elapsed_ms: float) -> WebResponse:
        final_url, transport, redirects, connected_ip, attempt_count = result
        content_encoding = transport.headers.get("content-encoding", "identity").strip().lower()
        if content_encoding not in {"", "identity"}:
            raise WebGatewayError(
                "NETWORK_CONTENT_ENCODING_UNSUPPORTED",
                "Compressed network responses are not accepted.",
            )
        content_length = transport.headers.get("content-length", "").strip()
        if content_length:
            try:
                if int(content_length) > request.response_limit:
                    raise WebGatewayError(
                        "NETWORK_RESPONSE_TOO_LARGE",
                        "The remote response exceeds the configured size limit.",
                    )
            except ValueError as exc:
                raise WebGatewayError(
                    "NETWORK_INVALID_RESPONSE",
                    "The remote response has an invalid Content-Length header.",
                ) from exc
        if len(transport.body) > request.response_limit:
            raise WebGatewayError(
                "NETWORK_RESPONSE_TOO_LARGE",
                "The remote response exceeds the configured size limit.",
            )
        content_type = transport.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
        safe_headers = {key: (_safe_url(value) if key == "location" else value[:4096]) for key, value in transport.headers.items() if key in _SAFE_RESPONSE_HEADERS}
        self._emit(request, "network.response_received", {"request_id": request.request_id, "status_code": transport.status_code, "content_type": content_type, "size_bytes": len(transport.body), "elapsed_ms": elapsed_ms})
        if transport.status_code < 200 or transport.status_code >= 300:
            raise WebGatewayError("NETWORK_HTTP_STATUS", f"The remote server returned HTTP {transport.status_code}.")
        self._validate_mime(content_type, transport.body, final_url)
        text = _decode_text(transport.body, transport.headers.get("content-type", ""))
        scan = self._guard.scan(text, source=_safe_url(final_url)) if text else None
        cleaned = scan.sanitized_content if scan is not None else ""
        digest, retrieved_at = hashlib.sha256(transport.body).hexdigest(), _utc_now()
        source_id = snapshot_id = artifact_id = ""
        if self._sources is not None and self._snapshots is not None:
            source = SourceRecord(
                url=_safe_url(final_url), title=_extract_title(cleaned),
                publisher=(urlsplit(final_url).hostname or "").lower(), retrieved_at=retrieved_at,
                content_hash=digest, mime_type=content_type, source_type=_source_type(content_type),
                trust_tier=TrustTier.UNTRUSTED, extraction_method="nous.network.gateway.v1",
                injection_risk=getattr(scan, "risk_level", "low"),
                metadata={"request_id": request.request_id, "trace_id": request.trace_id, "resolved_ip": connected_ip, "redirect_count": len(redirects)},
            )
            source_id = self._sources.register(source)
            snapshot = self._snapshots.store(
                source_id, transport.body, cleaned_content=cleaned, content_type=content_type,
                retrieval_headers=safe_headers, limitations=["external_content_untrusted"],
                metadata={"request_id": request.request_id, "url": _safe_url(final_url)},
            )
            snapshot_id = snapshot.snapshot_id
            if self._artifacts is not None:
                artifact = self._artifacts.create(
                    ArtifactType.FILE, f"Web snapshot {source_id}", location=snapshot.storage_path,
                    creator="network.gateway",
                    metadata={"source_id": source_id, "snapshot_id": snapshot_id, "content_hash": digest, "mime_type": content_type, "size_bytes": len(transport.body)},
                )
                artifact_id = artifact.id
                self._snapshots.update_artifact(snapshot_id, artifact_id)
            source.snapshot_location, source.snapshot_artifact_id = snapshot.storage_path, artifact_id
            self._sources.register(source)
            self._emit(request, "network.snapshot_created", {"request_id": request.request_id, "source_id": source_id, "snapshot_id": snapshot_id, "snapshot_artifact_id": artifact_id, "content_hash": digest})
            if artifact_id:
                self._emit(request, "artifact.created", {"artifact_id": artifact_id, "artifact_type": ArtifactType.FILE.value, "source_id": source_id})
        self._emit(request, "network.completed", {"request_id": request.request_id, "source_id": source_id, "snapshot_artifact_id": artifact_id, "status_code": transport.status_code})
        self._finish_run(request, RunState.COMPLETED, source_id=source_id)
        return WebResponse(
            ok=True, url=safe_original, final_url=_safe_url(final_url), status_code=transport.status_code,
            content=cleaned, content_hash=digest, content_type=content_type, size_bytes=len(transport.body),
            snapshot_id=snapshot_id, snapshot_artifact_id=artifact_id, source_id=source_id,
            injection_scan_result=scan, retrieved_at=retrieved_at, response_headers=safe_headers,
            redirect_chain=redirects, run_id=request.run_id, request_id=request.request_id, attempt_count=attempt_count,
        )

    def _ensure_run(self, request: WebRequest) -> None:
        if self._events is None:
            return
        if self._events.get_run(request.run_id) is None:
            self._events.create_run(
                request.run_id, task_id=request.task_id or f"network.fetch:{request.request_id}",
                total_steps=1, metadata={"authority": "EventStream", "operation": "network.fetch"},
            )
            self._events.emit_state_change(request.run_id, RunState.CREATED, task_id=request.task_id, request_id=request.request_id)
        existing = {event.event_type for event in self._events.load_events(request.run_id)}
        if "network.requested" not in existing:
            self._emit(request, "network.requested", {
                "request_id": request.request_id, "method": request.method, "url": _safe_url(request.url),
                "credential_ref": request.credential_ref, "network_scope": request.network_scope,
                "max_response_bytes": request.response_limit, "body_sha256": _body_hash(request.body),
                "max_retries": request.max_retries, "retry_backoff_ms": request.retry_backoff_ms,
                "body_ref": request.body_ref, "headers_ref": request.headers_ref,
            })
        self._events.emit_state_change(request.run_id, RunState.RUNNING, task_id=request.task_id, operation="network.fetch")

    def _emit(self, request: WebRequest, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            self._events.emit(RunEvent(
                run_id=request.run_id, task_id=request.task_id or f"network.fetch:{request.request_id}",
                event_type=event_type, actor="network.gateway", payload=payload,
            ))

    def _finish_run(self, request: WebRequest, state: RunState, **payload: Any) -> None:
        if self._events is not None:
            self._events.emit_state_change(request.run_id, state, task_id=request.task_id or f"network.fetch:{request.request_id}", **payload)

    @staticmethod
    def _validate_mime(content_type: str, body: bytes, url: str) -> None:
        stripped, path = body.lstrip(), urlsplit(url).path.lower()
        if content_type in {"application/json", "application/ld+json"}:
            try:
                json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise WebGatewayError("NETWORK_MIME_MISMATCH", "The response declared JSON but was not valid JSON.") from exc
        if content_type == "application/pdf" and body and not body.startswith(b"%PDF-"):
            raise WebGatewayError("NETWORK_MIME_MISMATCH", "The response declared PDF but did not contain a PDF signature.")
        if content_type.startswith("image/") and stripped[:20].lower().startswith((b"<html", b"<!doctype")):
            raise WebGatewayError("NETWORK_MIME_MISMATCH", "The response declared an image but contained HTML.")
        if path.endswith(".json") and body and content_type not in {"application/json", "application/ld+json"}:
            raise WebGatewayError("NETWORK_MIME_MISMATCH", "A JSON resource returned a non-JSON MIME type.")


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80)


def _host_header(host: str, port: int, scheme: str) -> str:
    default = 443 if scheme == "https" else 80
    formatted = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return formatted if port == default else f"{formatted}:{port}"


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(str(url or ""))
        host = (parts.hostname or "").lower()
        port = parts.port
        netloc = _host_header(host, port or (443 if parts.scheme.lower() == "https" else 80), parts.scheme.lower())
        query = urlencode([(key, "<redacted>" if _SENSITIVE_QUERY.search(key) else value) for key, value in parse_qsl(parts.query, keep_blank_values=True)])
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", query, ""))
    except ValueError:
        return "<invalid-url>"


def _body_hash(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        encoded = body
    elif isinstance(body, (dict, list)):
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        encoded = str(body).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decode_text(body: bytes, content_type_header: str) -> str:
    content_type = content_type_header.split(";", 1)[0].strip().lower()
    if not any(content_type.startswith(prefix) for prefix in _TEXT_MIME):
        return ""
    match = re.search(r"(?i)charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type_header)
    charset = match.group(1) if match else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _extract_title(content: str) -> str:
    if not content:
        return ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", content)
    if not match:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(1))).strip()[:300]


def _source_type(content_type: str) -> SourceType:
    if content_type in {"application/json", "application/ld+json"}:
        return SourceType.API_RESPONSE
    if content_type == "application/pdf":
        return SourceType.DOCUMENTATION
    return SourceType.WEB_PAGE


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


__all__ = ["WebGateway", "WebGatewayError", "WebRequest", "WebResponse"]
