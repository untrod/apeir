from __future__ import annotations

import asyncio
import gzip
import json
import ssl
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mcp.server import MCPServer

from nous_runtime.extensions.admission import ExtensionAdmissionService
from nous_runtime.extensions.executor import (
    ExtensionExecutionError,
    ExtensionInvocation,
    UnifiedExtensionExecutor,
)
from nous_runtime.extensions.mcp_sdk import (
    McpSdkExecutionAdapter,
    McpTransportSecurityError,
    _PinnedHttpsTransport,
)
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.kernel.sandbox import SandboxResult as ProcessSandboxResult


def make_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fixture": {"url": "https://mcp.example.test/mcp"}
                }
            }
        ),
        encoding="utf-8",
    )


def make_process_config(path: Path, *, with_credentials: bool = False) -> None:
    server = {"command": sys.executable, "args": ["-m", "fixture_server"]}
    if with_credentials:
        server["env"] = {"API_TOKEN": "env:API_TOKEN"}
    path.write_text(
        json.dumps({"mcpServers": {"fixture": server}}), encoding="utf-8"
    )


def decision(request, grants=(), receipt="mcp-admission"):
    requested = [item["capability"] for item in request["capability_requests"]]
    return {
        "admitted": True,
        "extension_id": request["extension_id"],
        "normalized_digest": request["content_digest"],
        "requested_capabilities": requested,
        "granted_capabilities": list(grants),
        "denied_capabilities": [],
        "approval_required": len(grants) != len(requested),
        "executor_constraints": {"executor": request["executor"]},
        "scope_constraints": {
            item["capability"]: item["scope"]
            for item in request["capability_requests"]
        },
        "policy_version": "fixture",
        "decision_reason": "fixture",
        "receipt_id": receipt,
    }


class FakeKernel:
    async def admit_extension(self, request, idempotency_key=""):
        return decision(request)

    async def authorize_extension(self, authorization, idempotency_key=""):
        return decision(
            authorization["admission"],
            authorization["approved_capabilities"],
            "mcp-authorization",
        )

    async def authorize_extension_execution(self, request, idempotency_key=""):
        return {
            "allowed": True,
            **{
                key: request[key]
                for key in (
                    "operation_id",
                    "extension_id",
                    "content_digest",
                    "authorization_receipt_id",
                    "capability",
                    "operation",
                    "parameter_hash",
                    "executor",
                )
            },
            "actor": "test-principal",
            "policy_version": "extension-execution-v1",
            "issued_at_us": 1,
            "permit_id": "extension-permit-mcp",
        }


def setup(tmp_path: Path):
    server = MCPServer("Nous governed MCP fixture")

    @server.tool()
    def echo(value: str) -> dict[str, str]:
        """Echo a value."""
        return {"echo": value}

    source = tmp_path / ".mcp.json"
    make_config(source)
    registry = ExtensionRegistry(tmp_path / "registry")
    extension_id = registry.install(source).extension_id
    kernel = FakeKernel()
    admission = ExtensionAdmissionService(registry, kernel)
    asyncio.run(admission.admit(extension_id))
    permissions = ExtensionPermissionService(
        registry,
        admission,
        ApprovalBroker(GovernanceStore(tmp_path / "governance")),
    )
    context = AuthorizationContext(
        subject_type="user",
        subject_id="local-user",
        authn_method="cli_os_user",
        authn_confidence=1.0,
    )
    _, request = permissions.request(extension_id, context)
    asyncio.run(permissions.approve(extension_id, request.request_id, "admin"))
    adapter = McpSdkExecutionAdapter(
        client_target_factory=lambda invocation, url: server
    )
    executor = UnifiedExtensionExecutor(registry, kernel, {"mcp": adapter})
    return registry, extension_id, executor


def test_official_sdk_discovery_and_tool_call_use_unified_kernel_path(tmp_path: Path):
    registry, extension_id, executor = setup(tmp_path)
    tools = asyncio.run(
        executor.discover_mcp_tools(extension_id, idempotency_key="discover-1")
    )
    assert [(tool.name, tool.protocol) for tool in tools] == [("echo", "mcp")]

    result = asyncio.run(
        executor.execute_tool(
            extension_id, "echo", {"value": "governed"}, idempotency_key="mcp-call-1"
        )
    )
    assert result.output["structured_content"] == {"echo": "governed"}
    assert result.receipt.permit_id == "extension-permit-mcp"
    assert registry.get_record(extension_id)["mcp_discovery_receipt"].startswith(
        "extension-execution-"
    )


def test_mcp_catalog_tamper_blocks_tool_before_execution(tmp_path: Path):
    registry, extension_id, executor = setup(tmp_path)
    asyncio.run(executor.discover_mcp_tools(extension_id, idempotency_key="discover-2"))
    manifest = registry.get(extension_id)
    catalog = (
        registry.objects
        / manifest.provenance.digest.removeprefix("sha256:")
        / "mcp-tool-catalog.json"
    )
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["tools"][0]["name"] = "tampered"
    catalog.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ExtensionExecutionError, match="integrity"):
        asyncio.run(
            executor.execute_tool(
                extension_id, "tampered", {}, idempotency_key="mcp-call-2"
            )
        )


def test_remote_transport_pins_public_ip_and_preserves_tls_identity():
    observed = {}

    async def handler(request):
        observed["host"] = request.url.host
        observed["host_header"] = request.headers["host"]
        observed["sni"] = request.extensions["sni_hostname"]
        observed["encoding"] = request.headers["accept-encoding"]
        return httpx2.Response(200, json={"ok": True})

    async def run():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp",
            max_response_bytes=1024,
            resolver=lambda host, port: ["93.184.216.34"],
            inner=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            response = await client.post(
                "https://mcp.example.test/mcp", json={"method": "tools/list"}
            )
            assert response.json() == {"ok": True}

    asyncio.run(run())
    assert observed == {
        "host": "93.184.216.34",
        "host_header": "mcp.example.test",
        "sni": "mcp.example.test",
        "encoding": "identity",
    }


def test_remote_transport_rejects_private_or_mixed_dns_before_network():
    contacted = False

    async def handler(request):
        nonlocal contacted
        contacted = True
        return httpx2.Response(200)

    async def run():
        with pytest.raises(McpTransportSecurityError, match="not a public IP"):
            transport = _PinnedHttpsTransport(
                "https://mcp.example.test/mcp",
                max_response_bytes=1024,
                resolver=lambda host, port: ["93.184.216.34", "127.0.0.1"],
                inner=httpx2.MockTransport(handler),
            )
            async with httpx2.AsyncClient(transport=transport) as client:
                await client.post("https://mcp.example.test/mcp")

    asyncio.run(run())
    assert contacted is False


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_remote_transport_rejects_redirects(status: int):
    async def handler(request):
        return httpx2.Response(status, headers={"location": "https://elsewhere.test"})

    async def run():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp",
            max_response_bytes=1024,
            resolver=lambda host, port: ["93.184.216.34"],
            inner=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(
            transport=transport, follow_redirects=False
        ) as client:
            with pytest.raises(McpTransportSecurityError, match="redirects"):
                await client.post("https://mcp.example.test/mcp")

    asyncio.run(run())


def test_remote_transport_rejects_oversized_response():
    async def handler(request):
        return httpx2.Response(200, content=b"x" * 17)

    async def run():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp",
            max_response_bytes=16,
            resolver=lambda host, port: ["93.184.216.34"],
            inner=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(McpTransportSecurityError, match="size limit"):
                await client.post("https://mcp.example.test/mcp")

    asyncio.run(run())


def test_remote_transport_rejects_compressed_response():
    async def handler(request):
        return httpx2.Response(
            200,
            content=gzip.compress(b"compressed"),
            headers={"content-encoding": "gzip"},
        )

    async def run():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp",
            max_response_bytes=1024,
            resolver=lambda host, port: ["93.184.216.34"],
            inner=httpx2.MockTransport(handler),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(McpTransportSecurityError, match="compressed"):
                await client.post("https://mcp.example.test/mcp")

    asyncio.run(run())


def test_remote_transport_rejects_path_escape():
    async def run():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp",
            max_response_bytes=1024,
            resolver=lambda host, port: ["93.184.216.34"],
            inner=httpx2.MockTransport(lambda request: httpx2.Response(200)),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(McpTransportSecurityError, match="authorized HTTPS origin"):
                await client.get("https://mcp.example.test/admin")
            with pytest.raises(McpTransportSecurityError, match="authorized HTTPS origin"):
                await client.get("https://mcp.example.test/mcp-evil")

    asyncio.run(run())


def test_stdio_bridge_runs_only_through_strong_policy_without_permit_egress(
    tmp_path: Path,
):
    source = tmp_path / ".mcp.json"
    make_process_config(source)
    registry = ExtensionRegistry(tmp_path / "registry-stdio")
    manifest = registry.install(source)
    assert manifest.provenance is not None
    observed = {}

    def runner(policy, input_bytes):
        observed["policy"] = policy
        observed["request"] = json.loads(input_bytes)
        return ProcessSandboxResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "success": True,
                    "output": {"tools": [], "protocol_version": "2026-07-28"},
                }
            ),
            availability_state="available",
            security_grade="strong_vm",
        )

    adapter = McpSdkExecutionAdapter(process_runner=runner)
    invocation = ExtensionInvocation(
        extension_id=manifest.extension_id,
        content_digest=manifest.provenance.digest,
        operation="tools/list",
        protocol="mcp",
        capability="process.execute",
        scope=(sys.executable,),
        arguments={},
        package_root=(
            registry.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "package"
        ),
    )

    result = asyncio.run(adapter.execute(invocation, permit_id="local-only-permit"))

    assert result.success
    assert observed["request"] == {
        "operation": "tools/list",
        "arguments": {},
        "timeout_seconds": 30.0,
        "max_catalog_pages": 100,
    }
    assert "permit" not in json.dumps(observed["request"]).lower()
    policy = observed["policy"]
    assert policy.require_strong_isolation is True
    assert policy.network_allowed is False
    assert policy.write_allowed_paths == []
    assert policy.args[0] == "-I"
    assert Path(policy.args[1]).name == "mcp_stdio_bridge.py"
    assert Path(policy.args[2]).samefile(sys.executable)
    assert policy.args[3:] == ["-m", "fixture_server"]


def test_stdio_credentials_fail_closed_without_local_provider(tmp_path: Path):
    source = tmp_path / ".mcp.json"
    make_process_config(source, with_credentials=True)
    registry = ExtensionRegistry(tmp_path / "registry-credentials")
    manifest = registry.install(source)
    assert manifest.provenance is not None
    invocation = ExtensionInvocation(
        extension_id=manifest.extension_id,
        content_digest=manifest.provenance.digest,
        operation="tools/list",
        protocol="mcp",
        capability="process.execute",
        scope=(sys.executable,),
        arguments={},
        package_root=(
            registry.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "package"
        ),
    )
    adapter = McpSdkExecutionAdapter(
        process_runner=lambda policy, data: pytest.fail("must not start process")
    )

    result = asyncio.run(adapter.execute(invocation, permit_id="local-only-permit"))

    assert result.success is False
    assert result.error_code == "MCP_CREDENTIALS_UNAVAILABLE"


def test_full_official_streamable_http_protocol_through_pinned_transport(tmp_path: Path):
    server = MCPServer("Nous pinned remote MCP fixture")

    @server.tool()
    def remote_echo(value: str) -> dict[str, str]:
        """Echo through the complete Streamable HTTP protocol."""
        return {"echo": value}

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="mcp.example.test",
    )
    source = tmp_path / ".mcp.json"
    make_config(source)
    registry = ExtensionRegistry(tmp_path / "registry-http")
    manifest = registry.install(source)
    assert manifest.provenance is not None
    package_root = (
        registry.objects
        / manifest.provenance.digest.removeprefix("sha256:")
        / "package"
    )

    def invocation(operation, arguments):
        return ExtensionInvocation(
            extension_id=manifest.extension_id,
            content_digest=manifest.provenance.digest,
            operation=operation,
            protocol="mcp",
            capability="network.connect",
            scope=("mcp.example.test",),
            arguments=arguments,
            package_root=package_root,
        )

    async def scenario():
        async with app.router.lifespan_context(app):
            adapter = McpSdkExecutionAdapter(
                resolver=lambda *_: ["93.184.216.34"],
                transport_factory=lambda: httpx2.ASGITransport(app=app),
            )
            listed = await adapter.execute(
                invocation("tools/list", {}), permit_id="local-only-permit"
            )
            assert listed.success, listed.error_code
            assert [tool["name"] for tool in listed.output["tools"]] == [
                "remote_echo"
            ]
            called = await adapter.execute(
                invocation("tools/call:remote_echo", {"value": "固定地址 HTTPS"}),
                permit_id="local-only-permit",
            )
            assert called.success, called.error_code
            assert called.output["structured_content"] == {
                "echo": "固定地址 HTTPS"
            }
            assert called.verification_status == "protocol_and_schema_validated"

    asyncio.run(scenario())


def test_pinned_transport_rejects_real_self_signed_tls_certificate(tmp_path: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mcp.example.test")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("mcp.example.test")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "self-signed.pem"
    key_path = tmp_path / "self-signed.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LoopbackConnector(httpx2.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx2.AsyncHTTPTransport(verify=True, trust_env=False)

        async def handle_async_request(self, request):
            forwarded = httpx2.Request(
                request.method,
                request.url.copy_with(host="127.0.0.1"),
                headers=request.headers,
                content=request.content,
                extensions=request.extensions,
            )
            return await self.inner.handle_async_request(forwarded)

        async def aclose(self):
            await self.inner.aclose()

    port = server.server_address[1]

    async def scenario():
        transport = _PinnedHttpsTransport(
            f"https://mcp.example.test:{port}/mcp",
            max_response_bytes=1024,
            resolver=lambda *_: ["93.184.216.34"],
            inner=LoopbackConnector(),
        )
        async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
            with pytest.raises(httpx2.ConnectError):
                await client.get(f"https://mcp.example.test:{port}/mcp")

    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
