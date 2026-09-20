"""Product installation planning shared by future GUI and setup builders."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from nous_runtime.core.errors import ConfigurationError
from nous_runtime.model_runtime.scheduling import (
    HardwareSnapshot,
    detect_hardware_snapshot,
)


class InstallMode(str, Enum):
    RECOMMENDED = "recommended"
    DEVELOPER = "developer"
    RUNTIME_ONLY = "runtime_only"
    PORTABLE = "portable"


@dataclass(frozen=True)
class SystemProfile:
    os_name: str
    os_version: str
    architecture: str
    hardware: HardwareSnapshot

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["hardware"] = asdict(self.hardware)
        return data


@dataclass(frozen=True)
class ProductInstallPlan:
    mode: InstallMode
    install_root: str
    components: tuple[str, ...]
    directories: tuple[str, ...]
    launchers: tuple[str, ...]
    profile: SystemProfile
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["profile"] = self.profile.to_dict()
        return data


def detect_system_profile(path: str | Path = ".") -> SystemProfile:
    return SystemProfile(
        os_name=platform.system(),
        os_version=platform.version(),
        architecture=platform.machine(),
        hardware=detect_hardware_snapshot(path),
    )


class ProductInstaller:
    """Create a reversible on-disk Nous product layout.

    OS-level shortcuts and signed executable packaging remain responsibilities
    of platform builders; this service owns the install layout they invoke.
    """

    def __init__(
        self,
        install_root: str | Path,
        *,
        profile: SystemProfile | None = None,
    ) -> None:
        self.install_root = Path(install_root).expanduser().resolve()
        self.profile = profile or detect_system_profile(
            self.install_root.parent
        )

    def plan(
        self, mode: InstallMode | str = InstallMode.RECOMMENDED
    ) -> ProductInstallPlan:
        normalized = (
            mode if isinstance(mode, InstallMode) else InstallMode(str(mode))
        )
        components = ["runtime", "cli", "model_runtime"]
        if normalized in {InstallMode.RECOMMENDED, InstallMode.DEVELOPER}:
            components.extend(["desktop", "model_center"])
        if normalized is InstallMode.DEVELOPER:
            components.extend(["sdk", "examples", "developer_tools"])
        directories = (
            "bin",
            "config",
            "data",
            "logs",
            "models",
            "runtime",
        )
        warnings: list[str] = []
        if self.profile.hardware.ram_available_mb and (
            self.profile.hardware.ram_available_mb < 4096
        ):
            warnings.append("low available memory; remote models recommended")
        if not self.profile.hardware.gpu_available:
            warnings.append("no local GPU detected; CPU or remote models used")
        return ProductInstallPlan(
            mode=normalized,
            install_root=str(self.install_root),
            components=tuple(components),
            directories=directories,
            launchers=("Nous.cmd", "Nous-CLI.cmd"),
            profile=self.profile,
            warnings=tuple(warnings),
        )

    def apply(
        self,
        mode: InstallMode | str = InstallMode.RECOMMENDED,
        *,
        dry_run: bool = False,
    ) -> ProductInstallPlan:
        plan = self.plan(mode)
        if dry_run:
            return plan
        if self.install_root == Path(self.install_root.anchor):
            raise ConfigurationError("install_root cannot be a drive root")
        self.install_root.mkdir(parents=True, exist_ok=True)
        for relative in plan.directories:
            (self.install_root / relative).mkdir(parents=True, exist_ok=True)
        python = str(Path(sys.executable).resolve())
        launcher = (
            "@echo off\r\n"
            f'"{python}" -m nous_runtime %*\r\n'
        )
        (self.install_root / "bin" / "Nous.cmd").write_text(
            launcher, encoding="utf-8"
        )
        (self.install_root / "bin" / "Nous-CLI.cmd").write_text(
            launcher, encoding="utf-8"
        )
        manifest = {
            "schema_version": 1,
            "product": "Nous Runtime",
            "mode": plan.mode.value,
            "components": list(plan.components),
            "profile": plan.profile.to_dict(),
            "python": python,
            "portable": plan.mode is InstallMode.PORTABLE,
        }
        target = self.install_root / "config" / "installation.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return plan


__all__ = [
    "InstallMode",
    "ProductInstallPlan",
    "ProductInstaller",
    "SystemProfile",
    "detect_system_profile",
]
