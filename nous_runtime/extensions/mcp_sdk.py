"""MCP 2026-07-28 execution using the official Python SDK 2.x."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from nous_runtime.extensions.async_compat import timeout
from nous_runtime.extensions.executor import AdapterResult, ExtensionInvocation

try:
    import httpx2 as _httpx2
except ImportError:  # MCP is an optional runtime dependency.
    _httpx2 = None

_AsyncTransportBase = _httpx2.AsyncBaseTransport if _httpx2 else object
_AsyncStreamBase = _httpx2.AsyncByteStream if _httpx2 else object


class McpSdkExecutionError(RuntimeError):
    pass


class McpTransportSecurityError(McpSdkExecutionError):
    """Remote MCP transport violated the governed egress profile."""


class McpSdkExecutionAdapter:
    """Official-SDK MCP adapter; Kernel permission remains local authority."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_catalog_pages: int = 100,
        max_response_bytes: int = 8 * 1024 * 1024,
        client_target_factory: Callable[[ExtensionInvocation, str], Any] | None = None,
        resolver: Callable[[str, int], Iterable[str]] | None = None,
        transport_factory: Callable[[], Any] | None = None,
        process_runner: Callable[[Any, bytes | None], Any] | None = None,
    ):
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("MCP timeout must be between 0 and 120 seconds")
        if max_catalog_pages < 1 or max_catalog_pages > 1000:
            raise ValueError("MCP catalog page limit is invalid")
        if max_response_bytes < 1 or max_response_bytes > 16 * 1024 * 1024:
            raise ValueError("MCP response limit must be between 1 byte and 16 MiB")
        self.timeout_seconds = timeout_seconds
        self.max_catalog_pages = max_catalog_pages
        self.max_response_bytes = max_response_bytes
        self.client_target_factory = client_target_factory
        self.resolver = resolver or _resolve_addresses
        self.transport_factory = transport_factory
        self.process_runner = process_runner or _run_strong_process

    async def execute(
        self, invocation: ExtensionInvocation, *, permit_id: str
    ) -> AdapterResult:
        if not permit_id:
            raise McpSdkExecutionError("Kernel permit is required")
        if invocation.protocol != "mcp":
            raise McpSdkExecutionError("invocation is not an MCP operation")
        try:
            from mcp import Client
        except ImportError as exc:
            raise McpSdkExecutionError(
                "official MCP SDK 2.x is unavailable; install nous-runtime[mcp]"
            ) from exc
        target_url, kind, configuration = _server_target(invocation.package_root)
        if kind == "process":
            return await self._execute_stdio(invocation, target_url, configuration)
        host = (urlsplit(target_url).hostname or "").rstrip(".").lower()
        allowed = {item.rstrip(".").lower() for item in invocation.scope}
        if not host or host not in allowed:
            raise McpSdkExecutionError(
                "MCP server is outside the Kernel-authorized host scope"
            )
        if urlsplit(target_url).scheme.lower() != "https":
            raise McpSdkExecutionError(
                "MCP remote execution requires HTTPS in the current security profile"
            )
        try:
            async with timeout(self.timeout_seconds):
                if self.client_target_factory:
                    target = self.client_target_factory(invocation, target_url)
                    async with Client(
                        target,
                        read_timeout_seconds=self.timeout_seconds,
                        mode="auto",
                    ) as client:
                        return await self._invoke(client, invocation)

                try:
                    import httpx2
                    from mcp.client.streamable_http import streamable_http_client
                except ImportError as exc:
                    raise McpSdkExecutionError(
                        "official MCP HTTPS dependencies are unavailable"
                    ) from exc

                transport = _PinnedHttpsTransport(
                    target_url,
                    max_response_bytes=self.max_response_bytes,
                    resolver=self.resolver,
                    inner=(self.transport_factory() if self.transport_factory else None),
                )
                async with httpx2.AsyncClient(
                    transport=transport,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as http_client:
                    target = streamable_http_client(
                        target_url,
                        http_client=http_client,
                        terminate_on_close=False,
                    )
                    async with Client(
                        target,
                        read_timeout_seconds=self.timeout_seconds,
                        mode="auto",
                    ) as client:
                        return await self._invoke(client, invocation)
        except TimeoutError:
            return AdapterResult(False, error_code="MCP_TIMEOUT")

    async def _execute_stdio(
        self,
        invocation: ExtensionInvocation,
        declared_command: str,
        configuration: dict[str, Any],
    ) -> AdapterResult:
        if declared_command not in invocation.scope:
            raise McpSdkExecutionError(
                "MCP stdio command is outside the Kernel-authorized process scope"
            )
        credential_refs = configuration.get("credential_env_refs") or []
        if credential_refs:
            return AdapterResult(False, error_code="MCP_CREDENTIALS_UNAVAILABLE")
        command = _resolve_stdio_command(declared_command, invocation.package_root)
        server_args = [str(item) for item in configuration.get("args") or ()]
        bridge = Path(__file__).with_name("mcp_stdio_bridge.py").resolve()
        read_paths = {
            str(invocation.package_root.resolve()),
            str(bridge.parent),
            str(Path(command).resolve().parent),
        }
        for argument in server_args:
            if os.path.isabs(argument):
                resolved = Path(argument).resolve()
                if not any(resolved.is_relative_to(Path(root)) for root in read_paths):
                    raise McpSdkExecutionError(
                        "MCP argument is outside package/runtime read scope; "
                        "absolute arguments cannot grant host filesystem access"
                    )

        from nous_runtime.kernel.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            executable=str(Path(sys.executable).resolve()),
            # Isolated mode prevents adjacent mcp.py and user-site packages
            # from shadowing the official SDK in the standalone bridge.
            args=["-I", str(bridge), command, *server_args],
            working_dir=str(invocation.package_root.resolve()),
            env={},
            max_memory_bytes=512 * 1024 * 1024,
            max_cpu_time_seconds=max(1, int(self.timeout_seconds)),
            max_processes=8,
            max_output_bytes=self.max_response_bytes,
            read_allowed_paths=sorted(read_paths),
            write_allowed_paths=[],
            network_allowed=False,
            timeout_seconds=self.timeout_seconds,
            isolation_level="strict",
            require_strong_isolation=True,
        )
        bridge_request = json.dumps(
            {
                "operation": invocation.operation,
                "arguments": invocation.arguments,
                "timeout_seconds": self.timeout_seconds,
                "max_catalog_pages": self.max_catalog_pages,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        result = await asyncio.to_thread(self.process_runner, policy, bridge_request)
        if result.output_truncated:
            return AdapterResult(False, error_code="MCP_STDIO_OUTPUT_LIMIT")
        if not result.success:
            code = (
                "MCP_STDIO_SANDBOX_UNAVAILABLE"
                if result.availability_state == "unavailable"
                else "MCP_STDIO_PROCESS_ERROR"
            )
            return AdapterResult(False, error_code=code)
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError):
            return AdapterResult(False, error_code="MCP_STDIO_INVALID_RESULT")
        if not isinstance(payload, dict) or type(payload.get("success")) is not bool:
            return AdapterResult(False, error_code="MCP_STDIO_INVALID_RESULT")
        output = payload.get("output")
        if not payload.get("success"):
            return AdapterResult(
                False,
                output,
                error_code=str(payload.get("error_code") or "MCP_TOOL_ERROR"),
                output_bytes=_encoded_size(output),
            )
        return AdapterResult(
            True, output, output_bytes=_encoded_size(output),
            verification_status="protocol_and_schema_validated",
        )

    async def _invoke(
        self, client: Any, invocation: ExtensionInvocation
    ) -> AdapterResult:
        if invocation.operation == "tools/list":
            output = await self._list_tools(client)
        elif invocation.operation.startswith("tools/call:"):
            name = invocation.operation.removeprefix("tools/call:")
            result = await client.call_tool(
                name,
                invocation.arguments,
                read_timeout_seconds=self.timeout_seconds,
            )
            output = _tool_result(result)
            if bool(getattr(result, "is_error", False)):
                return AdapterResult(
                    False,
                    output,
                    error_code="MCP_TOOL_ERROR",
                    output_bytes=_encoded_size(output),
                )
        else:
            raise McpSdkExecutionError(
                f"unsupported MCP operation: {invocation.operation}"
            )
        return AdapterResult(
            True, output, output_bytes=_encoded_size(output),
            verification_status="protocol_and_schema_validated",
        )

    async def _list_tools(self, client) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(self.max_catalog_pages):
            result = await client.list_tools(cursor=cursor)
            for tool in result.tools:
                tools.append(
                    {
                        "name": str(tool.name),
                        "description": str(tool.description or ""),
                        "input_schema": dict(tool.input_schema),
                        "output_schema": dict(tool.output_schema or {}),
                    }
                )
            cursor = result.next_cursor
            if _encoded_size(tools) > self.max_response_bytes:
                raise McpSdkExecutionError("MCP tool catalog exceeds size limit")
            if cursor is None:
                return {"tools": tools, "protocol_version": client.protocol_version}
        raise McpSdkExecutionError("MCP tool catalog exceeded pagination limit")


def _server_target(package_root: Path) -> tuple[str, str, dict[str, Any]]:
    """Read only the normalized, credential-redacted launch definition."""
    manifest_path = package_root.parent / "nous.extension.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise McpSdkExecutionError(
            "normalized MCP server definition is unavailable"
        ) from exc
    entries = data.get("entry_points") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) != 1:
        raise McpSdkExecutionError("MCP execution requires one normalized server")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise McpSdkExecutionError("normalized MCP server definition is invalid")
    kind = str(entry.get("kind") or "")
    value = str(entry.get("target") or "")
    configuration = entry.get("configuration") or {}
    if kind not in {"remote", "process"} or not value or not isinstance(configuration, dict):
        raise McpSdkExecutionError("normalized MCP server definition is invalid")
    return value, kind, dict(configuration)


def _resolve_stdio_command(declared: str, package_root: Path) -> str:
    candidate = Path(declared)
    if candidate.is_absolute() and candidate.is_file():
        return str(candidate.resolve())
    packaged = (package_root / candidate).resolve()
    if packaged.is_file():
        return str(packaged)
    found = shutil.which(declared)
    if found:
        return str(Path(found).resolve())
    raise McpSdkExecutionError(f"MCP stdio executable is unavailable: {declared}")


def _run_strong_process(policy: Any, input_bytes: bytes | None):
    from nous_runtime.kernel.sandbox import ProcessSandbox

    return ProcessSandbox(policy).run(input_bytes)


def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise McpTransportSecurityError(
            f"MCP host resolution failed: {host}"
        ) from exc
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _validated_public_addresses(addresses: Iterable[str]) -> tuple[str, ...]:
    parsed = []
    for raw in addresses:
        try:
            if "%" in str(raw):
                raise ValueError("scoped IPv6 is forbidden")
            address = ipaddress.ip_address(str(raw))
        except ValueError as exc:
            raise McpTransportSecurityError("MCP resolver returned an invalid IP") from exc
        if (not address.is_global or address.is_multicast
                or (isinstance(address, ipaddress.IPv6Address)
                    and (address.sixtofour is not None or address.teredo is not None))):
            raise McpTransportSecurityError(
                f"MCP destination is not a public IP: {address}"
            )
        parsed.append(address)
    if not parsed:
        raise McpTransportSecurityError("MCP host resolved to no addresses")
    return tuple(str(item) for item in parsed)


class _PinnedHttpsTransport(_AsyncTransportBase):
    """HTTPS transport that pins every request to a validated public IP."""

    def __init__(
        self,
        target_url: str,
        *,
        max_response_bytes: int,
        resolver: Callable[[str, int], Iterable[str]],
        inner: Any | None = None,
    ):
        if _httpx2 is None:
            raise McpSdkExecutionError("httpx2 is unavailable")
        parsed = urlsplit(target_url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise McpTransportSecurityError("MCP transport requires an HTTPS origin")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise McpTransportSecurityError("MCP URL credentials and fragments are forbidden")
        self._host = parsed.hostname.rstrip(".").lower()
        self._port = parsed.port or 443
        self._origin_path = parsed.path or "/"
        self._origin_query = _httpx2.URL(target_url).query
        self._max_response_bytes = max_response_bytes
        self._pinned_addresses = _validated_public_addresses(
            resolver(self._host, self._port)
        )
        self._inner = inner or _httpx2.AsyncHTTPTransport(verify=True, trust_env=False)

    async def handle_async_request(self, request):
        request_host = (request.url.host or "").rstrip(".").lower()
        request_port = request.url.port or 443
        if (
            request.url.scheme.lower() != "https"
            or request_host != self._host
            or request_port != self._port
            or request.url.path != self._origin_path
            or request.url.query != self._origin_query
            or request.url.userinfo
            or request.url.fragment
        ):
            raise McpTransportSecurityError(
                "MCP request attempted to leave its authorized HTTPS origin"
            )

        pinned_url = request.url.copy_with(host=self._pinned_addresses[0])
        headers = request.headers.copy()
        headers["host"] = (
            self._host if self._port == 443 else f"{self._host}:{self._port}"
        )
        headers["accept-encoding"] = "identity"
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self._host
        pinned_request = _httpx2.Request(
            request.method,
            pinned_url,
            headers=headers,
            content=request.content,
            extensions=extensions,
        )
        response = await self._inner.handle_async_request(pinned_request)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise McpTransportSecurityError("MCP redirects are forbidden")
        content_encoding = response.headers.get("content-encoding", "identity").lower()
        if content_encoding not in {"", "identity"}:
            await response.aclose()
            raise McpTransportSecurityError(
                "compressed MCP responses are forbidden by the size-limited profile"
            )
        declared = response.headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                await response.aclose()
                raise McpTransportSecurityError(
                    "MCP response has an invalid Content-Length"
                ) from exc
            if declared_size < 0:
                await response.aclose()
                raise McpTransportSecurityError("MCP response has an invalid Content-Length")
            if declared_size > self._max_response_bytes:
                await response.aclose()
                raise McpTransportSecurityError("MCP response exceeds size limit")

        return _httpx2.Response(
            response.status_code,
            headers=response.headers,
            stream=_LimitedResponseStream(response, self._max_response_bytes),
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class _LimitedResponseStream(_AsyncStreamBase):
    """Bound decoded-free bytes without waiting for a long-lived SSE EOF."""

    def __init__(self, response, limit: int):
        self.response = response
        self.limit = limit

    async def __aiter__(self):
        used = 0
        try:
            if self.response.is_stream_consumed:
                chunk = self.response.content
                if len(chunk) > self.limit:
                    raise McpTransportSecurityError("MCP response exceeds size limit")
                yield chunk
            else:
                async for chunk in self.response.aiter_raw():
                    used += len(chunk)
                    if used > self.limit:
                        raise McpTransportSecurityError("MCP response exceeds size limit")
                    yield chunk
        finally:
            await self.response.aclose()

    async def aclose(self):
        await self.response.aclose()


def _tool_result(result: Any) -> dict[str, Any]:
    return {
        "content": [_model_value(item) for item in (getattr(result, "content", None) or ())],
        "structured_content": getattr(result, "structured_content", None),
        "is_error": bool(getattr(result, "is_error", False)),
    }


def _model_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False)
    if isinstance(value, dict):
        return dict(value)
    return str(value)


def _encoded_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    )
