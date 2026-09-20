"""MCP client over an injected, Kernel-governed transport.

There is deliberately no HTTP client or subprocess launcher here. A caller
must provide a transport which validates an NKI authorization identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nous_runtime.extensions.models import ToolSpec


class McpProtocolError(RuntimeError):
    pass


class GovernedMcpTransport(Protocol):
    async def exchange(
        self, message: dict[str, Any], *, authorization_id: str
    ) -> dict[str, Any] | None:
        """Exchange JSON-RPC only after validating Kernel authority."""


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]

    def to_tool_spec(self) -> ToolSpec:
        # Server annotations are untrusted display metadata, not authority.
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            effect="unknown",
            protocol="mcp",
            operation=f"tools/call:{self.name}",
        )


class McpClient:
    def __init__(
        self,
        transport: GovernedMcpTransport,
        *,
        authorization_id: str,
        protocol_version: str = "2025-06-18",
        client_name: str = "nous-runtime",
        client_version: str = "1",
    ):
        if not authorization_id.strip():
            raise ValueError("Kernel authorization_id is required for MCP transport")
        self.transport = transport
        self.authorization_id = authorization_id
        self.protocol_version = protocol_version
        self.client_name = client_name
        self.client_version = client_version
        self._request_id = 0
        self.server_capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}

    async def initialize(self) -> dict[str, Any]:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
        )
        version = result.get("protocolVersion")
        if not isinstance(version, str) or not version:
            raise McpProtocolError("initialize response is missing protocolVersion")
        self.protocol_version = version
        self.server_capabilities = _mapping(
            result.get("capabilities"), "server capabilities"
        )
        self.server_info = _mapping(result.get("serverInfo"), "server info")
        await self._notification("notifications/initialized", {})
        return result

    async def list_tools(self, *, max_pages: int = 100) -> tuple[McpTool, ...]:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        tools: list[McpTool] = []
        names: set[str] = set()
        cursor: str | None = None
        for _ in range(max_pages):
            result = await self._request(
                "tools/list", {"cursor": cursor} if cursor else {}
            )
            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise McpProtocolError("tools/list response must contain a tools array")
            for raw in raw_tools:
                if not isinstance(raw, dict):
                    raise McpProtocolError("MCP tool must be an object")
                name = str(raw.get("name") or "")
                input_schema = raw.get("inputSchema")
                if not name or not isinstance(input_schema, dict):
                    raise McpProtocolError("MCP tool requires name and inputSchema")
                if name in names:
                    raise McpProtocolError(f"duplicate MCP tool: {name}")
                names.add(name)
                tools.append(
                    McpTool(
                        name=name,
                        description=str(raw.get("description") or ""),
                        input_schema=input_schema,
                        output_schema=_mapping(
                            raw.get("outputSchema") or {}, f"outputSchema for {name}"
                        ),
                        annotations=_mapping(
                            raw.get("annotations") or {}, f"annotations for {name}"
                        ),
                    )
                )
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tuple(tools)
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise McpProtocolError("invalid or repeated MCP pagination cursor")
            cursor = next_cursor
        raise McpProtocolError("MCP tools/list exceeded pagination limit")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not name or not isinstance(arguments, dict):
            raise ValueError("tool name and object arguments are required")
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if result.get("content") is not None and not isinstance(result["content"], list):
            raise McpProtocolError("tools/call content must be an array")
        if result.get("structuredContent") is not None and not isinstance(
            result["structuredContent"], dict
        ):
            raise McpProtocolError("tools/call structuredContent must be an object")
        return result

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        response = await self.transport.exchange(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            authorization_id=self.authorization_id,
        )
        if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
            raise McpProtocolError("invalid JSON-RPC response")
        if response.get("id") != request_id:
            raise McpProtocolError("MCP response id does not match request")
        if "error" in response:
            error = response.get("error")
            if not isinstance(error, dict):
                raise McpProtocolError("malformed MCP error response")
            raise McpProtocolError(
                f"MCP error {error.get('code', 'unknown')}: {error.get('message', '')}"
            )
        return _mapping(response.get("result"), "JSON-RPC result")

    async def _notification(self, method: str, params: dict[str, Any]) -> None:
        response = await self.transport.exchange(
            {"jsonrpc": "2.0", "method": method, "params": params},
            authorization_id=self.authorization_id,
        )
        if response not in ({}, None):
            raise McpProtocolError(
                "MCP notification transport returned unexpected data"
            )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise McpProtocolError(f"{field} must be an object")
    return value
