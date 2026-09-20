"""Adversarial unit regressions; not a substitute for native VM evidence."""

import asyncio
import os
import sys
from pathlib import Path

import httpx2
import pytest

from nous_runtime.extensions.mcp_sdk import (
    McpTransportSecurityError, McpSdkExecutionError, McpSdkExecutionAdapter,
    _PinnedHttpsTransport, _validated_public_addresses,
)
from nous_runtime.extensions.executor import ExtensionInvocation
from nous_runtime.extensions.async_compat import timeout
from nous_runtime.kernel.sandbox import SandboxPolicy, SandboxResult
from nous_runtime.kernel.windows_sandbox import _build_mappings, _bounded_text


@pytest.mark.parametrize("address", [
    "224.0.0.1", "ff0e::1", "fe80::1%eth0", "2002:7f00:1::",
    "2001:0000:4136:e378:8000:63bf:3fff:fdd2", "::ffff:127.0.0.1",
])
def test_special_ip_destinations_are_never_public_egress(address):
    with pytest.raises(McpTransportSecurityError):
        _validated_public_addresses([address])


@pytest.mark.parametrize("url", [
    "https://user:password@mcp.example.test/mcp",
    "https://mcp.example.test/mcp#fragment",
])
def test_credentials_and_fragments_rejected_before_dns(url):
    with pytest.raises(McpTransportSecurityError):
        _PinnedHttpsTransport(
            url, max_response_bytes=100,
            resolver=lambda *_: pytest.fail("must reject before DNS"),
        )


def test_query_change_rejected_before_network():
    async def check():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp?tenant=one", max_response_bytes=100,
            resolver=lambda *_: ["93.184.216.34"],
            inner=httpx2.MockTransport(lambda _: pytest.fail("must not send")),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(McpTransportSecurityError):
                await client.get("https://mcp.example.test/mcp?tenant=two")
    asyncio.run(check())


def test_tls_transport_ignores_environment_certificate_overrides(monkeypatch):
    observed = {}
    def factory(**kwargs):
        observed.update(kwargs)
        return object()
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", factory)
    _PinnedHttpsTransport(
        "https://mcp.example.test/mcp", max_response_bytes=100,
        resolver=lambda *_: ["93.184.216.34"],
    )
    assert observed == {"verify": True, "trust_env": False}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_narrow_write_scope_does_not_promote_workspace(tmp_path):
    work = tmp_path / "work"
    write = work / "output"
    control = tmp_path / "control"
    write.mkdir(parents=True)
    control.mkdir()
    policy = SandboxPolicy(
        executable=str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
        working_dir=str(work), write_allowed_paths=[str(write)],
    )
    mappings, _ = _build_mappings(policy, control)
    assert next(ro for root, _, ro in mappings if root == work) is True
    assert next(ro for root, _, ro in mappings if root == write) is False


def test_utf8_truncation_does_not_exceed_byte_budget():
    value, cut = _bounded_text("中文", 2)
    assert cut and len(value.encode("utf-8")) <= 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_file_grant_never_widens_to_parent(tmp_path):
    target = tmp_path / "allowed.txt"
    target.touch()
    control = tmp_path / "control"
    control.mkdir()
    policy = SandboxPolicy(
        executable=str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
        working_dir=str(tmp_path), read_allowed_paths=[str(target)],
    )
    with pytest.raises(ValueError, match="directory-scoped"):
        _build_mappings(policy, control)


def test_sse_first_event_arrives_before_response_eof():
    closed = []
    class Events(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: first\n\n"
            await asyncio.Event().wait()
        async def aclose(self):
            closed.append(True)
    async def check():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp", max_response_bytes=100,
            resolver=lambda *_: ["93.184.216.34"],
            inner=httpx2.MockTransport(
                lambda _: httpx2.Response(
                    200, stream=Events(), headers={"content-type": "text/event-stream"}
                )
            ),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            async with timeout(2):
                async with client.stream("GET", "https://mcp.example.test/mcp") as response:
                    assert await anext(response.aiter_raw()) == b"data: first\n\n"
    asyncio.run(check())
    assert closed


def test_chunked_response_cannot_exceed_budget_and_is_closed():
    closed = []
    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"1234"
            yield b"5678"
        async def aclose(self):
            closed.append(True)
    async def check():
        transport = _PinnedHttpsTransport(
            "https://mcp.example.test/mcp", max_response_bytes=5,
            resolver=lambda *_: ["93.184.216.34"],
            inner=httpx2.MockTransport(lambda _: httpx2.Response(200, stream=Chunks())),
        )
        async with httpx2.AsyncClient(transport=transport) as client:
            with pytest.raises(McpTransportSecurityError, match="size limit"):
                await client.get("https://mcp.example.test/mcp")
    asyncio.run(check())
    assert closed


def _stdio_invocation(tmp_path):
    return ExtensionInvocation(
        extension_id="fixture", content_digest="sha256:fixture",
        operation="tools/list", protocol="mcp", capability="process.execute",
        scope=(sys.executable,), arguments={}, package_root=tmp_path,
    )


def test_absolute_stdio_argument_cannot_grant_extra_directory(tmp_path, monkeypatch):
    private = tmp_path.parent / "private" / "file.txt"
    monkeypatch.setattr(
        "nous_runtime.extensions.mcp_sdk._server_target",
        lambda _: (sys.executable, "process", {"args": [str(private)]}),
    )
    adapter = McpSdkExecutionAdapter(
        process_runner=lambda *_: pytest.fail("unauthorized scope must not run")
    )
    with pytest.raises(McpSdkExecutionError, match="outside package/runtime"):
        asyncio.run(adapter.execute(_stdio_invocation(tmp_path), permit_id="local"))


@pytest.mark.parametrize("output,truncated,code", [
    ("[]", False, "MCP_STDIO_INVALID_RESULT"),
    ('{"success":"yes"}', False, "MCP_STDIO_INVALID_RESULT"),
    ('{"success":true}', True, "MCP_STDIO_OUTPUT_LIMIT"),
])
def test_invalid_stdio_result_fails_closed(tmp_path, monkeypatch, output, truncated, code):
    monkeypatch.setattr(
        "nous_runtime.extensions.mcp_sdk._server_target",
        lambda _: (sys.executable, "process", {"args": []}),
    )
    adapter = McpSdkExecutionAdapter(process_runner=lambda *_: SandboxResult(
        exit_code=0, stdout=output, output_truncated=truncated,
    ))
    result = asyncio.run(adapter.execute(_stdio_invocation(tmp_path), permit_id="local"))
    assert not result.success and result.error_code == code


def test_bridge_output_is_utf8_even_when_text_stdout_uses_windows_codepage(monkeypatch):
    import io
    import json
    from nous_runtime.extensions import mcp_stdio_bridge as bridge

    wire = io.BytesIO()
    text_stdout = io.TextIOWrapper(wire, encoding="cp936")
    text_stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
    expected = {"success": True, "output": {"echo": "隔离环境 UTF-8"}}
    async def call(*_):
        return expected
    with monkeypatch.context() as scoped:
        scoped.setattr(bridge, "_run", call)
        scoped.setattr(sys, "argv", ["bridge", "fixture"])
        scoped.setattr(sys, "stdin", text_stdin)
        scoped.setattr(sys, "stdout", text_stdout)
        status = bridge.main()
    assert status == 0
    assert json.loads(wire.getvalue().decode("utf-8")) == expected
