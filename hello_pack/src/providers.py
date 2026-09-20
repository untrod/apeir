# -*- coding: utf-8 -*-
"""hello_pack providers."""

from __future__ import annotations

from remote_terminal.nous_core.provider import Provider


class HelloProvider(Provider):
    """Example provider for hello_pack."""

    name = "hello_pack_hello"
    version = "0.1.0"

    def list_capabilities(self) -> list[str]:
        return ["hello_pack.hello"]

    def invoke(self, capability_id: str, **params) -> dict:
        greeting = params.get("greeting", "Hello from hello_pack!")
        return {"ok": True, "message": greeting}

    def health(self) -> dict:
        return {"status": "ok"}
