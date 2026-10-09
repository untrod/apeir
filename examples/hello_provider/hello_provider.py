from __future__ import annotations

from nous_provider.runtime import Provider, ProviderAdapter, ProviderManifest


class HelloProvider(Provider, ProviderAdapter):
    provider_id = "example.hello"
    provider_name = "Hello Provider"

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            capabilities=self.list_capabilities(),
            requires_credential=False,
            credential_type="none",
            requires_network=False,
        )

    def list_capabilities(self) -> list[str]:
        return ["example.greet"]

    def invoke(self, capability_id: str, **params) -> dict:
        if capability_id != "example.greet":
            return {"ok": False, "error": "Capability is not declared"}
        return {"ok": True, "message": f"Hello, {params.get('name', 'World')}!"}

    def health(self) -> dict:
        return {"status": "ok"}
