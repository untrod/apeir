# -*- coding: utf-8 -*-
"""Web Provider -tool.web_search, tool.web_fetch."""

from __future__ import annotations

import logging
from nous_runtime.compat.provider import Provider

log = logging.getLogger("nous.provider.web")


class WebProvider(Provider):
    """Provider for web search and content fetching."""

    name = "web"
    version = "1.0.0"

    def list_capabilities(self) -> list[str]:
        return ["tool.web_search", "tool.web_fetch"]

    def invoke(self, capability_id: str, **params) -> dict:
        try:
            import remote_terminal.tools as tools_module

            if "search" in capability_id:
                result = tools_module.handle_web_search(
                    {"query": params.get("query", "")}, {}, lambda cmd: ("", -1)
                )
            else:
                result = tools_module.handle_web_fetch(
                    {"url": params.get("url", "")}, {}, lambda cmd: ("", -1)
                )
            output = result.output if hasattr(result, "output") else str(result)
            status = getattr(result, "status", "done")
            return {
                "ok": status == "done",
                "status": status,
                "requires_approval": status == "awaiting_confirmation",
                "results": output,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        return {"status": "ok"}
