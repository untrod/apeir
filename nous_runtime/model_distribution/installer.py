"""Recoverable installer workflow built on the distribution foundation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.model_distribution.catalog import ModelCatalog
from nous_runtime.model_distribution.downloader import (
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_distribution.manager import ModelDistributionManager
from nous_runtime.model_runtime.errors import ModelResolutionError
from nous_runtime.model_runtime.models import (
    CapabilityResolution,
    ModelModality,
    utc_now,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.model_runtime.resolver import (
    HardwareBudget,
    ModelCapabilityResolver,
    detect_hardware_budget,
)


class InstallerStep(IntEnum):
    WELCOME = 0
    ENVIRONMENT = 1
    INSTALL_LOCATION = 2
    CAPABILITIES = 3
    MODEL_PLAN = 4
    LICENSES = 5
    DOWNLOAD = 6
    IMPORT = 7
    PROVIDERS = 8
    VERIFICATION = 9
    COMPLETE = 10


@dataclass
class InstallerState:
    install_root: str
    current_step: InstallerStep = InstallerStep.WELCOME
    capabilities: list[str] = field(default_factory=list)
    modalities: list[str] = field(
        default_factory=lambda: [ModelModality.TEXT.value]
    )
    catalog_path: str = ""
    catalog_version: str = ""
    selected_packages: list[str] = field(default_factory=list)
    accepted_licenses: list[str] = field(default_factory=list)
    downloaded_files: dict[str, str] = field(default_factory=dict)
    imported_models: list[str] = field(default_factory=list)
    provider_references: dict[str, str] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "install_root": self.install_root,
            "current_step": int(self.current_step),
            "capabilities": list(self.capabilities),
            "modalities": list(self.modalities),
            "catalog_path": self.catalog_path,
            "catalog_version": self.catalog_version,
            "selected_packages": list(self.selected_packages),
            "accepted_licenses": list(self.accepted_licenses),
            "downloaded_files": dict(self.downloaded_files),
            "imported_models": list(self.imported_models),
            "provider_references": dict(self.provider_references),
            "hardware": dict(self.hardware),
            "verification": dict(self.verification),
            "warnings": list(self.warnings),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InstallerState":
        return cls(
            install_root=str(data.get("install_root") or ""),
            current_step=InstallerStep(
                int(data.get("current_step") or 0)
            ),
            capabilities=list(data.get("capabilities") or ()),
            modalities=list(data.get("modalities") or ("text",)),
            catalog_path=str(data.get("catalog_path") or ""),
            catalog_version=str(data.get("catalog_version") or ""),
            selected_packages=list(
                data.get("selected_packages") or ()
            ),
            accepted_licenses=list(
                data.get("accepted_licenses") or ()
            ),
            downloaded_files=dict(
                data.get("downloaded_files") or {}
            ),
            imported_models=list(data.get("imported_models") or ()),
            provider_references=dict(
                data.get("provider_references") or {}
            ),
            hardware=dict(data.get("hardware") or {}),
            verification=dict(data.get("verification") or {}),
            warnings=list(data.get("warnings") or ()),
            updated_at=str(data.get("updated_at") or utc_now()),
        )


class ModelInstallerController:
    """Headless installer state machine shared by CLI and GUI clients."""

    def __init__(self, install_root: str | Path) -> None:
        self.install_root = Path(install_root).expanduser().resolve()
        self.models_root = self.install_root / "models"
        self.state_path = self.models_root / "installer-state.json"
        self.registry = ModelRuntimeRegistry(
            self.models_root / "registry.json"
        )
        self.journal = TransactionJournal(
            self.models_root / "transactions.json"
        )
        self.downloader = ResumableModelDownloader(
            self.models_root / "downloads",
            journal=self.journal,
        )
        self.distribution = ModelDistributionManager(self.registry)
        self.state = self._load_state()

    def prepare(self) -> InstallerState:
        for path in (
            self.models_root,
            self.models_root / "downloads",
            self.models_root / "imported",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.registry.flush()
        self._save()
        return self.state

    def inspect_environment(self) -> HardwareBudget:
        hardware = detect_hardware_budget(self.install_root)
        self.state.hardware = {
            "disk_mb": hardware.disk_mb,
            "memory_mb": hardware.memory_mb,
            "vram_mb": hardware.vram_mb,
            "allow_gpu_packages": hardware.allow_gpu_packages,
        }
        self._save()
        return hardware

    def select_capabilities(
        self,
        capabilities: list[str] | tuple[str, ...],
        modalities: list[str] | tuple[str, ...] = ("text",),
    ) -> None:
        self.state.capabilities = sorted(
            {
                str(item).strip()
                for item in capabilities
                if str(item).strip()
            }
        )
        try:
            self.state.modalities = sorted(
                {
                    ModelModality(str(item)).value
                    for item in modalities
                }
            )
        except ValueError as exc:
            raise ModelResolutionError(
                f"unsupported installer modality: {exc}"
            ) from exc
        self._save()

    def plan(
        self,
        catalog: ModelCatalog,
        *,
        hardware: HardwareBudget | None = None,
    ) -> CapabilityResolution:
        packages = [
            package
            for model in catalog.models
            for package in model.packages
        ]
        active_hardware = hardware or self.inspect_environment()
        resolution = ModelCapabilityResolver(packages).resolve(
            capabilities=self.state.capabilities,
            modalities=self.state.modalities,
            hardware=active_hardware,
            installed_packages=self._installed_package_ids(),
        )
        self.state.catalog_version = catalog.catalog_version
        self.state.selected_packages = [
            item.package_id for item in resolution.selected_packages
        ]
        self.state.warnings = list(resolution.warnings)
        self._save()
        return resolution

    def accept_licenses(self, package_ids: list[str]) -> None:
        selected = set(self.state.selected_packages)
        accepted = {str(item) for item in package_ids}
        unknown = accepted - selected
        if unknown:
            raise ModelResolutionError(
                "cannot accept licenses for unselected packages: "
                + ", ".join(sorted(unknown))
            )
        self.state.accepted_licenses = sorted(accepted)
        self._save()

    def download_selected(self, catalog: ModelCatalog) -> dict[str, str]:
        selected = set(self.state.selected_packages)
        if selected - set(self.state.accepted_licenses):
            raise ModelResolutionError(
                "all selected package licenses must be accepted"
            )
        downloaded = dict(self.state.downloaded_files)
        for model in catalog.models:
            package_ids = {item.package_id for item in model.packages}
            if not package_ids.intersection(selected):
                continue
            for artifact in model.artifacts:
                path = self.downloader.download(artifact)
                downloaded[artifact.artifact_id] = str(path)
        self.state.downloaded_files = downloaded
        self._save()
        return downloaded

    def import_local(
        self,
        source: str | Path,
        *,
        model_id: str = "",
        reference: bool = True,
    ) -> str:
        _, record = self.distribution.import_local(
            source,
            model_id=model_id,
            reference=reference,
            destination_root=(
                None
                if reference
                else self.models_root / "imported"
            ),
        )
        if record.descriptor.model_id not in self.state.imported_models:
            self.state.imported_models.append(record.descriptor.model_id)
            self.state.imported_models.sort()
        self._save()
        return record.descriptor.model_id

    def set_provider_reference(
        self,
        provider_id: str,
        credential_ref: str,
    ) -> None:
        provider = str(provider_id or "").strip()
        reference = str(credential_ref or "").strip()
        if not provider or not reference:
            raise ModelResolutionError(
                "provider_id and credential reference are required"
            )
        lowered = reference.lower()
        if any(
            marker in lowered
            for marker in ("sk-", "bearer ", "api_key=", "token=")
        ):
            raise ModelResolutionError(
                "installer stores credential references, not raw secrets"
            )
        self.state.provider_references[provider] = reference
        self._save()

    def verify(self) -> dict[str, Any]:
        errors = []
        for artifact_id, raw_path in self.state.downloaded_files.items():
            path = Path(raw_path)
            if not path.is_file():
                errors.append(f"download missing: {artifact_id}")
        for model_id in self.state.imported_models:
            record = self.registry.get(model_id)
            if record is None:
                errors.append(f"imported model missing from registry: {model_id}")
            elif not Path(record.location).exists():
                errors.append(f"imported model location missing: {model_id}")
        incomplete = self.journal.incomplete()
        if incomplete:
            errors.append(
                f"{len(incomplete)} distribution transactions need recovery"
            )
        result = {
            "ok": not errors,
            "errors": errors,
            "model_count": len(self.registry.list(include_removed=True)),
            "download_count": len(self.state.downloaded_files),
            "import_count": len(self.state.imported_models),
        }
        self.state.verification = result
        self._save()
        return result

    def advance(self, target: InstallerStep | int) -> InstallerStep:
        normalized = InstallerStep(int(target))
        current = self.state.current_step
        if normalized > current + 1:
            raise ModelResolutionError(
                "installer steps cannot be skipped"
            )
        if (
            normalized is InstallerStep.COMPLETE
            and not self.state.verification.get("ok", False)
        ):
            raise ModelResolutionError(
                "installer cannot complete before verification passes"
            )
        self.state.current_step = normalized
        self._save()
        return normalized

    def reset_progress(self) -> None:
        root = self.state.install_root
        self.state = InstallerState(install_root=root)
        self._save()

    def _installed_package_ids(self) -> set[str]:
        installed = set()
        for record in self.registry.list(include_removed=True):
            package_id = record.metadata.get("package_id")
            if package_id:
                installed.add(str(package_id))
        return installed

    def _load_state(self) -> InstallerState:
        if not self.state_path.is_file():
            return InstallerState(install_root=str(self.install_root))
        try:
            payload = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
            state = InstallerState.from_dict(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelResolutionError(
                f"failed to recover installer state: {exc}"
            ) from exc
        if Path(state.install_root).resolve() != self.install_root:
            raise ModelResolutionError(
                "installer state belongs to a different install root"
            )
        return state

    def _save(self) -> None:
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = utc_now()
        temporary = self.state_path.with_suffix(
            self.state_path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                self.state.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)


__all__ = [
    "InstallerState",
    "InstallerStep",
    "ModelInstallerController",
]
