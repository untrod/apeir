from __future__ import annotations

from nous_runtime.provider.base import Provider


class HelloProvider(Provider):
    provider_id = "example.hello"
    provider_name = "Hello Provider"

    def list_capabilities(self) -> list[str]:
        return ["example.greet"]

    def invoke(self, capability_id: str, **params) -> dict:
        if capability_id != "example.greet":
            return {"ok": False, "error": "Capability is not declared"}
        return {"ok": True, "message": f"Hello, {params.get('name', 'World')}!"}

    def health(self) -> dict:
        return {"status": "ok"}