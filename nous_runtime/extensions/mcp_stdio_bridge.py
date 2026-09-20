"""Official MCP stdio client executed only inside a strong process sandbox."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any


def _model_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False)
    if isinstance(value, dict):
        return dict(value)
    return str(value)


async def _run(request: dict[str, Any], command: str, args: list[str]) -> dict[str, Any]:
    from mcp import Client, StdioServerParameters

    timeout = float(request.get("timeout_seconds") or 30.0)
    server = StdioServerParameters(
        command=command, args=args,
        env={"PYTHONIOENCODING": "utf-8"}, cwd=os.getcwd(),
    )
    async with asyncio.timeout(timeout):
        async with Client(server, read_timeout_seconds=timeout, mode="auto") as client:
            operation = str(request.get("operation") or "")
            if operation == "tools/list":
                tools = []
                cursor = None
                pages = int(request.get("max_catalog_pages") or 100)
                for _ in range(pages):
                    result = await client.list_tools(cursor=cursor)
                    tools.extend(
                        {
                            "name": str(tool.name),
                            "description": str(tool.description or ""),
                            "input_schema": dict(tool.input_schema),
                            "output_schema": dict(tool.output_schema or {}),
                        }
                        for tool in result.tools
                    )
                    cursor = result.next_cursor
                    if cursor is None:
                        return {
                            "success": True,
                            "output": {
                                "tools": tools,
                                "protocol_version": client.protocol_version,
                            },
                        }
                return {"success": False, "error_code": "MCP_CATALOG_LIMIT"}
            if operation.startswith("tools/call:"):
                result = await client.call_tool(
                    operation.removeprefix("tools/call:"),
                    dict(request.get("arguments") or {}),
                    read_timeout_seconds=timeout,
                )
                output = {
                    "content": [
                        _model_value(item)
                        for item in (getattr(result, "content", None) or ())
                    ],
                    "structured_content": getattr(result, "structured_content", None),
                    "is_error": bool(getattr(result, "is_error", False)),
                }
                return {
                    "success": not output["is_error"],
                    "output": output,
                    "error_code": "MCP_TOOL_ERROR" if output["is_error"] else "",
                }
            return {"success": False, "error_code": "MCP_UNSUPPORTED_OPERATION"}


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error_code": "MCP_SERVER_MISSING"}))
        return 2
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        result = asyncio.run(_run(request, sys.argv[1], sys.argv[2:]))
    except Exception as exc:
        result = {
            "success": False,
            "error_code": type(exc).__name__,
        }
        if isinstance(exc, ModuleNotFoundError):
            result["error_detail"] = f"missing module: {exc.name or 'unknown'}"
        elif isinstance(exc, json.JSONDecodeError):
            result["error_detail"] = f"{exc.msg} at position {exc.pos}"
    # -I intentionally ignores PYTHONIOENCODING. The protocol envelope must
    # bypass Windows locale-dependent text stdout, including on zh-CN hosts.
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
