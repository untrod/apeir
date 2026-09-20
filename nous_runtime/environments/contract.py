"""Environment Provider contract and startup compatibility handshake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from nous_runtime._version import API_SERVER_VERSION, __version__
from nous_runtime.schema_registry import ENVIRONMENT_PROVIDER_SCHEMA_VERSION, ENVIRONMENT_SCHEMA_VERSION, EVENT_SCHEMA_VERSION

NKI_PROTOCOL_VERSION = 2
KERNEL_VERSION = "0.1.0"


class EnvironmentCompatibilityError(RuntimeError):
    """A provider cannot safely participate in this Runtime contract."""


@runtime_checkable
class EnvironmentProvider(Protocol):
    provider_id: str
    contract_version: str

    def probe(self) -> dict[str, Any]: ...
    def prepare(self, environment, workspace_root): ...
    def start(self, environment, handle: str): ...
    def execute(self, environment, handle: str, command): ...
    def stop(self, environment, handle: str): ...
    def destroy(self, environment, handle: str): ...
    def logs(self, environment, handle: str) -> str: ...


@dataclass(frozen=True)
class CompatibilityHandshake:
    product_version: str
    kernel_version: str
    nki_version: int
    runtime_api_version: str
    event_schema_version: str
    environment_contract_version: str
    provider_contract_version: str
    provider_id: str
    compatible: bool
    issues: tuple[str, ...]

    @classmethod
    def for_provider(cls, provider: EnvironmentProvider) -> "CompatibilityHandshake":
        issues: list[str] = []
        provider_id = str(getattr(provider, "provider_id", "") or "")
        provider_version = str(getattr(provider, "contract_version", "") or "")
        if not provider_id:
            issues.append("provider_id is missing")
        if provider_version != ENVIRONMENT_PROVIDER_SCHEMA_VERSION:
            issues.append(
                f"provider contract {provider_version or '<missing>'} is incompatible with {ENVIRONMENT_PROVIDER_SCHEMA_VERSION}"
            )
        if not isinstance(provider, EnvironmentProvider):
            issues.append("provider does not implement the Environment Provider Contract")
        return cls(
            product_version=__version__,
            kernel_version=KERNEL_VERSION,
            nki_version=NKI_PROTOCOL_VERSION,
            runtime_api_version=API_SERVER_VERSION,
            event_schema_version=EVENT_SCHEMA_VERSION,
            environment_contract_version=ENVIRONMENT_SCHEMA_VERSION,
            provider_contract_version=provider_version,
            provider_id=provider_id,
            compatible=not issues,
            issues=tuple(issues),
        )

    def require_compatible(self) -> None:
        if not self.compatible:
            raise EnvironmentCompatibilityError("; ".join(self.issues))

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_version": self.product_version,
            "kernel_version": self.kernel_version,
            "nki_version": self.nki_version,
            "runtime_api_version": self.runtime_api_version,
            "event_schema_version": self.event_schema_version,
            "environment_contract_version": self.environment_contract_version,
            "provider_contract_version": self.provider_contract_version,
            "provider_id": self.provider_id,
            "compatible": self.compatible,
            "issues": list(self.issues),
            "verification_scope": "environment-provider-contract",
            "kernel_verified_live": False,
            "kernel_version_semantics": "declared compatibility target, not a live NKI handshake",
            "execution_authority": "Python EnvironmentRuntime",
        }


__all__ = [
    "CompatibilityHandshake",
    "EnvironmentCompatibilityError",
    "EnvironmentProvider",
    "KERNEL_VERSION",
    "NKI_PROTOCOL_VERSION",
]
