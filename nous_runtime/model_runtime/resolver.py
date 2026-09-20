"""Capability-to-model-package resolution without model training."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from nous_runtime.model_runtime.errors import ModelResolutionError
from nous_runtime.model_runtime.models import (
    CapabilityResolution,
    ModelModality,
    ModelPackage,
)


@dataclass(frozen=True)
class HardwareBudget:
    disk_mb: int = 0
    memory_mb: int = 0
    vram_mb: int = 0
    allow_gpu_packages: bool = True

    def __post_init__(self) -> None:
        if self.disk_mb < 0 or self.memory_mb < 0 or self.vram_mb < 0:
            raise ModelResolutionError(
                "hardware budget values must be non-negative"
            )


def detect_hardware_budget(
    path: str | Path = ".",
) -> HardwareBudget:
    """Return conservative currently available host capacity."""
    disk_mb = int(shutil.disk_usage(Path(path)).free / (1024 * 1024))
    memory_mb = 0
    try:
        import psutil

        memory_mb = int(psutil.virtual_memory().available / (1024 * 1024))
    except ImportError:
        try:
            from nous_runtime.cli.doctor import _get_memory_fallback

            memory_mb = int(_get_memory_fallback() / (1024 * 1024))
        except (OSError, NotImplementedError):
            memory_mb = 0
    vram_mb = max(0, int(os.environ.get("NOUS_GPU_VRAM_MB") or 0))
    return HardwareBudget(
        disk_mb=disk_mb,
        memory_mb=memory_mb,
        vram_mb=vram_mb,
        allow_gpu_packages=vram_mb > 0,
    )


class ModelCapabilityResolver:
    """Build a minimal approved package set for requested capabilities."""

    def __init__(self, packages: Iterable[ModelPackage] = ()) -> None:
        self._packages: dict[str, ModelPackage] = {}
        for package in packages:
            self.register(package)

    def register(self, package: ModelPackage) -> ModelPackage:
        if package.package_id in self._packages:
            raise ModelResolutionError(
                f"model package already registered: {package.package_id}"
            )
        self._packages[package.package_id] = package
        return package

    def resolve(
        self,
        *,
        capabilities: Iterable[str],
        modalities: Iterable[ModelModality | str] = (ModelModality.TEXT,),
        hardware: HardwareBudget | None = None,
        installed_packages: Iterable[str] = (),
        allow_unapproved_licenses: bool = False,
    ) -> CapabilityResolution:
        required_capabilities = frozenset(
            str(item).strip()
            for item in capabilities
            if str(item).strip()
        )
        try:
            required_modalities = frozenset(
                item
                if isinstance(item, ModelModality)
                else ModelModality(str(item))
                for item in modalities
            )
        except ValueError as exc:
            raise ModelResolutionError(
                f"unsupported modality: {exc}"
            ) from exc
        budget = hardware or HardwareBudget()
        installed = frozenset(str(item) for item in installed_packages)
        eligible = [
            item
            for item in self._packages.values()
            if allow_unapproved_licenses or item.license_approved
        ]
        warnings: list[str] = []
        excluded = [
            item.package_id
            for item in self._packages.values()
            if not item.license_approved
        ]
        if excluded and not allow_unapproved_licenses:
            warnings.append(
                "unapproved packages excluded: " + ", ".join(sorted(excluded))
            )

        selected: list[ModelPackage] = []
        covered_capabilities: set[str] = set()
        covered_modalities: set[ModelModality] = set()
        disk_used = 0
        vram_peak = 0
        remaining = list(eligible)
        while (
            required_capabilities - covered_capabilities
            or required_modalities - covered_modalities
        ):
            candidates = []
            for package in remaining:
                new_capabilities = len(
                    package.capabilities
                    & (required_capabilities - covered_capabilities)
                )
                new_modalities = len(
                    package.modalities
                    & (required_modalities - covered_modalities)
                )
                coverage = new_capabilities + new_modalities
                if coverage == 0:
                    continue
                incremental_disk = (
                    0 if package.package_id in installed else package.disk_mb
                )
                if (
                    budget.disk_mb
                    and disk_used + incremental_disk > budget.disk_mb
                ):
                    continue
                if budget.vram_mb and package.vram_mb > budget.vram_mb:
                    continue
                package_memory_mb = int(
                    package.metadata.get("memory_mb") or 0
                )
                if (
                    budget.memory_mb
                    and package_memory_mb > budget.memory_mb
                ):
                    continue
                if not budget.allow_gpu_packages and package.vram_mb > 0:
                    continue
                candidates.append(
                    (
                        -coverage,
                        0 if package.package_id in installed else 1,
                        incremental_disk,
                        package.vram_mb,
                        package.package_id,
                        package,
                    )
                )
            if not candidates:
                break
            candidates.sort()
            package = candidates[0][-1]
            selected.append(package)
            remaining.remove(package)
            covered_capabilities.update(
                package.capabilities & required_capabilities
            )
            covered_modalities.update(
                package.modalities & required_modalities
            )
            if package.package_id not in installed:
                disk_used += package.disk_mb
            vram_peak = max(vram_peak, package.vram_mb)

        alternatives = self._alternative_plans(
            eligible,
            required_capabilities,
            required_modalities,
            selected,
        )
        uncovered_capabilities = (
            required_capabilities - covered_capabilities
        )
        uncovered_modalities = required_modalities - covered_modalities
        if uncovered_capabilities:
            warnings.append(
                "uncovered capabilities: "
                + ", ".join(sorted(uncovered_capabilities))
            )
        if uncovered_modalities:
            warnings.append(
                "uncovered modalities: "
                + ", ".join(
                    sorted(item.value for item in uncovered_modalities)
                )
            )
        return CapabilityResolution(
            selected_packages=tuple(selected),
            covered_capabilities=frozenset(covered_capabilities),
            uncovered_capabilities=frozenset(uncovered_capabilities),
            covered_modalities=frozenset(covered_modalities),
            uncovered_modalities=frozenset(uncovered_modalities),
            estimated_disk_mb=disk_used,
            estimated_vram_mb=vram_peak,
            alternative_plans=alternatives,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _alternative_plans(
        packages: list[ModelPackage],
        capabilities: frozenset[str],
        modalities: frozenset[ModelModality],
        selected: list[ModelPackage],
    ) -> tuple[tuple[str, ...], ...]:
        selected_ids = tuple(item.package_id for item in selected)
        alternatives = []
        for package in sorted(
            packages,
            key=lambda item: (item.disk_mb, item.package_id),
        ):
            if (
                capabilities.issubset(package.capabilities)
                and modalities.issubset(package.modalities)
                and (package.package_id,) != selected_ids
            ):
                alternatives.append((package.package_id,))
        return tuple(alternatives[:3])


__all__ = [
    "HardwareBudget",
    "ModelCapabilityResolver",
    "detect_hardware_budget",
]
