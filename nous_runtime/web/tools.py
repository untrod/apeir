"""ToolCatalog adapter for governed Web search and fetch."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nous_runtime.web.runtime import WebRuntime


class WebToolRuntime:
    def __init__(
        self, workspace: str | Path, *, runtime: WebRuntime | None = None
    ) -> None:
        self.runtime = runtime or WebRuntime(workspace)

    def specifications(self) -> tuple[dict[str, Any], ...]:
        common = {
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
            "max_response_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5_242_880,
            },
        }
        return (
            _tool(
                "web_search",
                "Search the public Web through the governed Network Gateway.",
                {
                    "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                    **common,
                },
                required=("query",),
            ),
            _tool(
                "web_fetch",
                "Fetch one public HTTP(S) URL as untrusted evidence.",
                {
                    "url": {"type": "string", "minLength": 1},
                    "max_retries": {"type": "integer", "minimum": 0, "maximum": 2},
                    **common,
                },
                required=("url",),
            ),
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name == "web_search":
            return self.runtime.search(arguments)
        if name == "web_fetch":
            return self.runtime.fetch(arguments)
        return {"ok": False, "error": f"unknown Web tool: {name}"}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


__all__ = ["WebToolRuntime"]
