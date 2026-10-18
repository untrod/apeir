"""Model Center application service shared by CLI, API and desktop clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nous_runtime.model_distribution.catalog import (
    Ed25519CatalogVerifier,
    ModelCatalog,
)
from nous_runtime.model_distribution.downloader import (
    ProgressCallback,
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_distribution.manager import ModelDistributionManager
from nous_runtime.model_runtime.evaluation import ModelEvaluationStore
from nous_runtime.model_runtime.errors import ModelRegistryError
from nous_runtime.model_runtime.models import (
    CapabilityLevel,
    ModelLifecycleState,
)
from nous_runtime.model_runtime.registry import ModelRecord, ModelRuntimeRegistry
from nous_runtime.model_runtime.scheduling import detect_hardware_snapshot


_LEVEL_SCORE = {
    CapabilityLevel.NONE: 0,
    CapabilityLevel.LOW: 3,
    CapabilityLevel.MEDIUM: 7,
    CapabilityLevel.HIGH: 10,
}


@dataclass(frozen=True)
class ModelCenterModel:
    model_id: str
    display_name: str
    provider_id: str
    endpoint_type: str
    state: str
    health: str
    capabilities: tuple[str, ...]
    capability_scores: dict[str, int]
    evaluation: dict[str, Any] | None
    location: str
    recoverable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelCenterService:
    """High-level model control without duplicating registry/install logic."""

    def __init__(self, workspace_root: str | Path = ".nous") -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.models_root = self.workspace_root / "models"
        self.registry = ModelRuntimeRegistry(
            self.models_root / "registry.json"
        )
        self.evaluations = ModelEvaluationStore(
            self.models_root / "evaluations.json"
        )
        self.distribution = ModelDistributionManager(self.registry)
        self.journal = TransactionJournal(
            self.models_root / "transactions.json"
        )

    def snapshot(self) -> dict[str, Any]:
        models = [
            self._view(record)
            for record in self.registry.list(include_removed=True)
        ]
        hardware = detect_hardware_snapshot(self.workspace_root)
        return {
            "schema_version": "1.0",
            "models": [item.to_dict() for item in models],
            "summary": {
                "total": len(models),
                "enabled": sum(
                    item.state == ModelLifecycleState.ENABLED.value
                    for item in models
                ),
                "healthy": sum(item.health == "healthy" for item in models),
                "recoverable_operations": len(self.journal.incomplete()),
            },
            "hardware": asdict(hardware),
        }

    def show(self, model_id: str) -> dict[str, Any]:
        return self._view(self.registry.require(model_id)).to_dict()

    def install(
        self,
        catalog_path: str | Path,
        model_id: str,
        *,
        public_key: str = "",
        allow_unsigned: bool = False,
        accept_license: bool = False,
        progress: ProgressCallback | None = None,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        """Install one signed catalog model through the secure downloader."""
        verifier = Ed25519CatalogVerifier(public_key) if public_key else None
        catalog = ModelCatalog.load(
            catalog_path,
            verifier=verifier,
            require_signature=not allow_unsigned,
        )
        model = catalog.model(model_id)
        if model is None:
            raise ModelRegistryError(f"catalog model not found: {model_id}")
        if any(not item.license_approved for item in model.packages):
            if not accept_license:
                raise ModelRegistryError(
                    "explicit license acceptance is required"
                )
        downloader = ResumableModelDownloader(
            self.models_root / "downloads" / model_id.replace("/", "_"),
            journal=self.journal,
        )
        downloaded = [
            str(downloader.download(artifact, progress=progress))
            for artifact in model.artifacts
        ]
        location = downloaded[0] if downloaded else ""
        record = self.registry.register(
            model.descriptor,
            state=ModelLifecycleState.REGISTERED,
            source="signed_catalog",
            location=location,
            metadata={
                "catalog_version": catalog.catalog_version,
                "package_ids": [
                    item.package_id for item in model.packages
                ],
                "artifact_paths": downloaded,
            },
            replace_existing=replace_existing,
        )
        return {
            **self._view(record).to_dict(),
            "downloaded_files": downloaded,
            "catalog_version": catalog.catalog_version,
        }

    def update(
        self,
        catalog_path: str | Path,
        model_id: str,
        **options: Any,
    ) -> dict[str, Any]:
        self.registry.require(model_id)
        return self.install(
            catalog_path,
            model_id,
            replace_existing=True,
            **options,
        )

    def enable(self, model_id: str) -> dict[str, Any]:
        return self._view(self.registry.enable(model_id)).to_dict()

    def disable(self, model_id: str) -> dict[str, Any]:
        return self._view(self.registry.disable(model_id)).to_dict()

    def remove(self, model_id: str) -> dict[str, Any]:
        record = self.registry.require(model_id)
        if record.state is ModelLifecycleState.ENABLED:
            record = self.registry.disable(model_id)
        if record.state is not ModelLifecycleState.REMOVED:
            record = self.registry.transition(
                model_id, ModelLifecycleState.REMOVED
            )
        return {
            **self._view(record).to_dict(),
            "files_preserved": True,
        }

    def verify(self, model_id: str) -> dict[str, Any]:
        record = self.registry.require(model_id)
        errors: list[str] = []
        if record.location and not Path(record.location).exists():
            errors.append("model location does not exist")
        if not record.descriptor.availability:
            errors.append("model descriptor is unavailable")
        if record.state is ModelLifecycleState.REMOVED:
            errors.append("model is removed")
        health = {
            "status": "healthy" if not errors else "unhealthy",
            "errors": errors,
        }
        if record.state is not ModelLifecycleState.REMOVED:
            self.registry.update_health(model_id, health)
        return {
            "model_id": model_id,
            "ok": not errors,
            "state": record.state.value,
            "errors": errors,
        }

    def repair(self, model_id: str) -> dict[str, Any]:
        record = self.registry.require(model_id)
        if record.location and not Path(record.location).exists():
            raise ModelRegistryError(
                "cannot repair: model location does not exist"
            )
        if record.state is ModelLifecycleState.BROKEN:
            record = self.registry.transition(
                model_id, ModelLifecycleState.REGISTERED
            )
        result = self.verify(model_id)
        result["state"] = record.state.value
        result["repaired"] = result["ok"]
        return result

    def _view(self, record: ModelRecord) -> ModelCenterModel:
        descriptor = record.descriptor
        evaluation = self.evaluations.summary(descriptor.model_id)
        health = str(record.health.get("status") or "").lower()
        if not health:
            health = (
                "unhealthy"
                if record.state is ModelLifecycleState.BROKEN
                else "healthy"
            )
        scores = {
            "reasoning": _LEVEL_SCORE[descriptor.reasoning_level],
            "coding": _LEVEL_SCORE[descriptor.coding_level],
            "vision": _LEVEL_SCORE[descriptor.vision_level],
            "speed": _LEVEL_SCORE[descriptor.latency_level],
            "cost": _LEVEL_SCORE[descriptor.cost_level],
        }
        return ModelCenterModel(
            model_id=descriptor.model_id,
            display_name=descriptor.display_name,
            provider_id=descriptor.provider_id,
            endpoint_type=descriptor.endpoint_type.value,
            state=record.state.value,
            health=health,
            capabilities=tuple(sorted(descriptor.capabilities)),
            capability_scores=scores,
            evaluation=evaluation.to_dict() if evaluation else None,
            location=record.location,
            recoverable=record.state in {
                ModelLifecycleState.BROKEN,
                ModelLifecycleState.PARTIAL,
            },
        )


__all__ = ["ModelCenterModel", "ModelCenterService"]
