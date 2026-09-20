from __future__ import annotations

from mcp.server import MCPServer


server = MCPServer("Nous Windows Sandbox MCP fixture")


@server.tool()
def echo(value: str) -> dict[str, str]:
    """Echo a value from the disposable VM."""
    return {"echo": value}


if __name__ == "__main__":
    server.run("stdio")
