"""High-level distribution operations connected to the runtime registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nous_runtime.model_distribution.importer import (
    ImportedModel,
    LocalModelImporter,
)
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
    ModelLifecycleState,
    ModelModality,
    PrivacyClass,
    ResourceRequirements,
)
from nous_runtime.model_runtime.registry import (
    ModelRecord,
    ModelRuntimeRegistry,
)


class ModelDistributionManager:
    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        *,
        importer: LocalModelImporter | None = None,
    ) -> None:
        self.registry = registry
        self.importer = importer or LocalModelImporter()

    def import_local(
        self,
        source: str | Path,
        *,
        model_id: str = "",
        display_name: str = "",
        reference: bool = True,
        destination_root: str | Path | None = None,
        capabilities: tuple[str, ...] = ("reasoning",),
        modalities: tuple[ModelModality | str, ...] = (
            ModelModality.TEXT,
        ),
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ImportedModel, ModelRecord]:
        imported = self.importer.import_model(
            source,
            destination_root=destination_root,
            reference=reference,
            metadata=metadata,
        )
        normalized_model_id = (
            model_id.strip()
            or f"local/{imported.name.lower().replace(' ', '-')}"
        )
        descriptor = ModelDescriptor(
            model_id=normalized_model_id,
            display_name=display_name.strip() or imported.name,
            provider_id="local-imported",
            endpoint_type=ModelEndpointType.LOCAL_MODEL,
            modalities=frozenset(modalities),
            capabilities=frozenset(capabilities),
            privacy_class=PrivacyClass.PRIVATE,
            resource_requirements=ResourceRequirements(
                disk_mb=max(
                    1,
                    (imported.size_bytes + (1024 * 1024 - 1))
                    // (1024 * 1024),
                )
            ),
            metadata={
                "import_id": imported.import_id,
                "format": imported.format,
                "checksum": imported.checksum,
                "referenced": imported.referenced,
                **dict(metadata or {}),
            },
        )
        record = self.registry.register(
            descriptor,
            state=ModelLifecycleState.REGISTERED,
            source="local_import",
            location=imported.location,
            metadata={"import_id": imported.import_id},
        )
        return imported, record


__all__ = ["ModelDistributionManager"]
