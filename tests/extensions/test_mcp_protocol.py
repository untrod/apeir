from __future__ import annotations

import asyncio

import pytest

from nous_runtime.extensions.mcp import McpClient, McpProtocolError


class FakeGovernedTransport:
    def __init__(self):
        self.calls = []

    async def exchange(self, message, *, authorization_id):
        assert authorization_id == "auth_kernel_1"
        self.calls.append(message)
        if "id" not in message:
            return {}
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list" and not message["params"].get("cursor"):
            result = {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": True},
                    }
                ],
                "nextCursor": "page-2",
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "write_file",
                        "inputSchema": {"type": "object"},
                        "outputSchema": {"type": "object"},
                    }
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            }
        else:
            raise AssertionError(method)
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def test_mcp_requires_kernel_authorization_identifier():
    with pytest.raises(ValueError, match="authorization_id"):
        McpClient(FakeGovernedTransport(), authorization_id="")


def test_mcp_initialize_discovery_and_call_use_governed_transport():
    async def scenario():
        transport = FakeGovernedTransport()
        client = McpClient(transport, authorization_id="auth_kernel_1")
        await client.initialize()
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["read_file", "write_file"]
        assert tools[0].to_tool_spec().effect == "unknown"
        assert tools[0].annotations == {"readOnlyHint": True}
        result = await client.call_tool("read_file", {"path": "README.md"})
        assert result["content"][0]["text"] == "ok"
        assert all(call.get("method") for call in transport.calls)

    asyncio.run(scenario())


class WrongIdTransport:
    async def exchange(self, message, *, authorization_id):
        return {"jsonrpc": "2.0", "id": 999, "result": {}}


def test_mcp_rejects_mismatched_json_rpc_response():
    async def scenario():
        client = McpClient(WrongIdTransport(), authorization_id="auth_kernel_1")
        with pytest.raises(McpProtocolError, match="does not match"):
            await client.list_tools()

    asyncio.run(scenario())


class ErrorTransport:
    async def exchange(self, message, *, authorization_id):
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32001, "message": "denied"},
        }


def test_mcp_surfaces_protocol_errors_without_fallback():
    async def scenario():
        client = McpClient(ErrorTransport(), authorization_id="auth_kernel_1")
        with pytest.raises(McpProtocolError, match="denied"):
            await client.call_tool("dangerous", {})

    asyncio.run(scenario())
