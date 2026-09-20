from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import shutil
import sys
import time
from pathlib import Path

import pytest

from compat.nki_client import NKIClient
from nous_runtime.extensions.admission import ExtensionAdmissionService
from nous_runtime.extensions.executor import (
    AdapterResult,
    ExtensionExecutionError,
    UnifiedExtensionExecutor,
)
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.mcp_sdk import McpSdkExecutionAdapter
from nous_runtime.kernel.windows_sandbox import executable_path as sandbox_executable
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore


class IntegrationAdapter:
    def __init__(self):
        self.permit_id = ""

    async def execute(self, invocation, *, permit_id):
        self.permit_id = permit_id
        return AdapterResult(True, {"id": invocation.arguments["id"]})


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_listener(process: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"nousd exited before READY: {output}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("nousd did not open its NKI listener")


def stop_process(process: subprocess.Popen) -> None:
    """Stop the test daemon and close every pipe owned by the parent."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def kernel_binaries() -> tuple[Path, Path, Path] | None:
    """Locate binaries from an explicitly selected independent Kernel checkout."""
    roots: list[Path] = []
    configured = os.environ.get("APEIR_KERNEL_ROOT")
    if configured:
        roots.append(Path(configured).expanduser().resolve())
    roots.append(Path(__file__).parents[3] / "kernel")

    for root in roots:
        for profile in ("debug", "release"):
            nousd = root / "target" / profile / "nousd.exe"
            worker = root / "target" / profile / "nous-provider-worker.exe"
            if nousd.is_file() and worker.is_file():
                return root, nousd, worker
    return None


def test_real_nousd_admission_approval_and_execution_permit(tmp_path: Path):
    binaries = kernel_binaries()
    if binaries is None:
        pytest.skip("set APEIR_KERNEL_ROOT to a built independent Kernel checkout")
    kernel, nousd, worker = binaries

    source = tmp_path / "openapi.json"
    source.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Native Integration", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.test"}],
                "paths": {
                    "/items/{id}": {
                        "get": {"operationId": "getItem"},
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    port = free_port()
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            str(nousd),
            "serve",
            str(tmp_path / "kernel.journal"),
            str(worker),
            f"127.0.0.1:{port}",
        ],
        cwd=kernel,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    try:
        wait_for_listener(process, port)

        async def scenario():
            registry = ExtensionRegistry(tmp_path / "registry")
            extension_id = registry.install(source).extension_id
            client = await NKIClient.connect(
                f"tcp://127.0.0.1:{port}", principal_id="integration-user"
            )
            try:
                admission = ExtensionAdmissionService(registry, client)
                initial = await admission.admit(extension_id)
                assert initial.approval_required
                permissions = ExtensionPermissionService(
                    registry,
                    admission,
                    ApprovalBroker(GovernanceStore(tmp_path / "governance")),
                )
                context = AuthorizationContext(
                    subject_type="user",
                    subject_id="integration-user",
                    authn_method="cli_os_user",
                    authn_confidence=1.0,
                )
                _, request = permissions.request(extension_id, context)
                authorized = await permissions.approve(
                    extension_id, request.request_id, "integration-admin"
                )
                assert authorized.granted_capabilities == ("network.connect",)

                adapter = IntegrationAdapter()
                executor = UnifiedExtensionExecutor(
                    registry, client, {"openapi": adapter}
                )
                result = await executor.execute_tool(
                    extension_id,
                    "getItem",
                    {"id": "native"},
                    idempotency_key="native-integration-1",
                )
                assert result.output == {"id": "native"}
                assert adapter.permit_id.startswith("extension-permit-")
                assert result.receipt.actor == "integration-user"
                revoked = await permissions.revoke(
                    extension_id, reason="native_integration"
                )
                assert revoked.granted_capabilities == ()
                with pytest.raises(
                    ExtensionExecutionError, match="no Kernel-granted authority"
                ):
                    await executor.execute_tool(
                        extension_id,
                        "getItem",
                        {"id": "revoked"},
                        idempotency_key="native-integration-after-revoke",
                    )
                return registry, extension_id
            finally:
                await client.close()

        registry, extension_id = asyncio.run(scenario())
        record = registry.get_record(extension_id)
        assert record["authority"] == "none"
        assert record["state"] == "revoked"
    finally:
        stop_process(process)


@pytest.mark.skipif(
    sys.platform != "win32" or sandbox_executable() is None,
    reason="real Kernel-to-VM test requires Windows Sandbox",
)
def test_real_nousd_permit_drives_real_mcp_sandbox_execution(tmp_path: Path):
    binaries = kernel_binaries()
    if binaries is None:
        pytest.skip("set APEIR_KERNEL_ROOT to a built independent Kernel checkout")
    kernel, nousd, worker = binaries

    package = tmp_path / "mcp-package"
    package.mkdir()
    fixture = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    shutil.copy2(fixture, package / fixture.name)
    (package / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "kernel-vm": {
                        "command": sys.executable,
                        "args": ["-I", fixture.name],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    port = free_port()
    process = subprocess.Popen(
        [
            str(nousd), "serve", str(tmp_path / "kernel-mcp.journal"),
            str(worker), f"127.0.0.1:{port}",
        ],
        cwd=kernel,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        wait_for_listener(process, port)

        async def scenario():
            registry = ExtensionRegistry(tmp_path / "registry-mcp")
            extension_id = registry.install(package).extension_id
            client = await NKIClient.connect(
                f"tcp://127.0.0.1:{port}", principal_id="kernel-vm-user"
            )
            try:
                admission = ExtensionAdmissionService(registry, client)
                initial = await admission.admit(extension_id)
                assert initial.approval_required
                permissions = ExtensionPermissionService(
                    registry,
                    admission,
                    ApprovalBroker(GovernanceStore(tmp_path / "governance-mcp")),
                )
                context = AuthorizationContext(
                    subject_type="user",
                    subject_id="kernel-vm-user",
                    authn_method="cli_os_user",
                    authn_confidence=1.0,
                )
                _, request = permissions.request(extension_id, context)
                authorized = await permissions.approve(
                    extension_id, request.request_id, "kernel-vm-admin"
                )
                assert authorized.granted_capabilities == ("process.execute",)
                executor = UnifiedExtensionExecutor(
                    registry,
                    client,
                    {"mcp": McpSdkExecutionAdapter(timeout_seconds=30)},
                )
                tools = await executor.discover_mcp_tools(
                    extension_id, idempotency_key="kernel-vm-discovery"
                )
                assert [tool.name for tool in tools] == ["echo"]
                result = await executor.execute_tool(
                    extension_id,
                    "echo",
                    {"value": "真实内核到隔离虚拟机"},
                    idempotency_key="kernel-vm-call",
                )
                assert result.output["structured_content"] == {
                    "echo": "真实内核到隔离虚拟机"
                }
                assert result.receipt.permit_id.startswith("extension-permit-")
                assert result.receipt.actor == "kernel-vm-user"
                assert (
                    result.receipt.verification_status
                    == "protocol_and_schema_validated"
                )
            finally:
                await client.close()

        asyncio.run(scenario())
    finally:
        stop_process(process)
