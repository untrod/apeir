from __future__ import annotations

import asyncio
import json
import sys
import shutil
from pathlib import Path

import pytest

from nous_runtime.extensions.executor import ExtensionInvocation
from nous_runtime.extensions.mcp_sdk import McpSdkExecutionAdapter
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.kernel.windows_sandbox import executable_path
from nous_runtime.kernel.sandbox import ProcessSandbox


pytestmark = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox is unavailable",
)


def _invocation(
    registry: ExtensionRegistry,
    manifest,
    operation: str,
    arguments: dict,
) -> ExtensionInvocation:
    assert manifest.provenance is not None
    return ExtensionInvocation(
        extension_id=manifest.extension_id,
        content_digest=manifest.provenance.digest,
        operation=operation,
        protocol="mcp",
        capability="process.execute",
        scope=(sys.executable,),
        arguments=arguments,
        package_root=(
            registry.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "package"
        ),
    )


def test_official_mcp_stdio_list_and_call_inside_real_windows_sandbox(tmp_path: Path):
    fixture = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    package = tmp_path / "source"
    package.mkdir()
    shutil.copy2(fixture, package / fixture.name)
    source = package / ".mcp.json"
    source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sandbox-fixture": {
                        "command": sys.executable,
                        "args": ["-I", fixture.name],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(package)
    def checked_runner(policy, data):
        result = ProcessSandbox(policy).run(data)
        assert result.success, (
            result.exit_code, result.timed_out, result.stdout, result.stderr
        )
        return result
    adapter = McpSdkExecutionAdapter(timeout_seconds=30, process_runner=checked_runner)

    listed = asyncio.run(
        adapter.execute(
            _invocation(registry, manifest, "tools/list", {}),
            permit_id="local-gate-permit",
        )
    )
    assert listed.success, listed.error_code
    assert [tool["name"] for tool in listed.output["tools"]] == ["echo"]

    called = asyncio.run(
        adapter.execute(
            _invocation(
                registry,
                manifest,
                "tools/call:echo",
                {"value": "隔离环境 UTF-8"},
            ),
            permit_id="local-gate-permit",
        )
    )
    assert called.success, called.error_code
    assert called.output["structured_content"] == {"echo": "隔离环境 UTF-8"}
