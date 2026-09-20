"""Thin creation facade over the artifact registry."""

from __future__ import annotations

from typing import Any, Mapping

from nous_runtime.artifact.models import Artifact, ArtifactType
from nous_runtime.artifact.registry import ArtifactRegistry


class ArtifactManager:
    """Create and register artifacts through one foundation entry point."""

    def __init__(self, registry: ArtifactRegistry | None = None) -> None:
        self.registry = registry or ArtifactRegistry()

    def create(
        self,
        artifact_type: str | ArtifactType,
        name: str,
        *,
        location: str = "",
        creator: str = "runtime",
        metadata: Mapping[str, Any] | None = None,
        artifact_id: str = "",
    ) -> Artifact:
        values: dict[str, Any] = {
            "type": artifact_type.value if isinstance(artifact_type, ArtifactType) else artifact_type,
            "name": name,
            "location": location,
            "creator": creator,
            "metadata": dict(metadata or {}),
        }
        if artifact_id:
            values["id"] = artifact_id
        return self.registry.register(Artifact(**values))

    def register(self, artifact: Artifact) -> Artifact:
        return self.registry.register(artifact)

    def get(self, artifact_id: str) -> Artifact | None:
        return self.registry.get(artifact_id)

    def list(self, artifact_type: str | ArtifactType | None = None) -> list[Artifact]:
        return self.registry.list(artifact_type)


__all__ = ["ArtifactManager"]
