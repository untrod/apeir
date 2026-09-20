"""Retrieval backend registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from nous_runtime.retrieval.errors import RetrievalBackendNotFoundError
from nous_runtime.retrieval.protocol import (
    BackendHealth,
    RetrievalBackend,
    RetrievalBackendManifest,
)


@dataclass
class RetrievalBackendRegistry:
    _backends: dict[str, RetrievalBackend] = field(default_factory=dict)

    def register(self, backend: RetrievalBackend, name: str | None = None) -> None:
        manifest = backend.manifest()
        self._backends[name or manifest.name] = backend

    def unregister(self, name: str) -> None:
        self._backends.pop(name, None)

    def resolve(self, name: str) -> RetrievalBackend:
        try:
            return self._backends[name]
        except KeyError as exc:
            raise RetrievalBackendNotFoundError(f"retrieval backend is not registered: {name}") from exc

    def list(self) -> list[str]:
        return sorted(self._backends)

    def manifests(self) -> list[RetrievalBackendManifest]:
        return [self._backends[name].manifest() for name in self.list()]

    def health_all(self) -> dict[str, BackendHealth]:
        return {name: backend.health() for name, backend in sorted(self._backends.items())}


registry = RetrievalBackendRegistry()
