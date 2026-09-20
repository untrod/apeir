"""Plugin ecosystem contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    runtime_compatibility: str
    entry_point: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    health_check: str = ""
    package_checksum: str = ""
    signature: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", self.plugin_id):
            errors.append("invalid plugin_id")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", self.version):
            errors.append("invalid plugin version")
        if not self.runtime_compatibility:
            errors.append("runtime_compatibility is required")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*", self.entry_point):
            errors.append("entry_point must use module:function")
        if not self.capabilities:
            errors.append("at least one capability is required")
        if len(set(self.capabilities)) != len(self.capabilities):
            errors.append("duplicate capability")
        for capability in self.capabilities:
            if not re.fullmatch(r"[a-z][a-z0-9_.]*", capability):
                errors.append(f"invalid capability: {capability}")
        allowed_permissions = {"filesystem.read", "filesystem.write", "network", "process", "connector", "model"}
        unknown = set(self.permissions) - allowed_permissions
        if unknown:
            errors.append("unknown permissions: " + ", ".join(sorted(unknown)))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {"plugin_id": self.plugin_id, "version": self.version, "runtime_compatibility": self.runtime_compatibility, "entry_point": self.entry_point, "capabilities": list(self.capabilities), "permissions": list(self.permissions), "dependencies": list(self.dependencies), "configuration_schema": self.configuration_schema, "health_check": self.health_check, "package_checksum": self.package_checksum, "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        return cls(plugin_id=str(data.get("plugin_id") or ""), version=str(data.get("version") or ""), runtime_compatibility=str(data.get("runtime_compatibility") or ""), entry_point=str(data.get("entry_point") or ""), capabilities=tuple(str(item) for item in data.get("capabilities") or ()), permissions=tuple(str(item) for item in data.get("permissions") or ()), dependencies=tuple(str(item) for item in data.get("dependencies") or ()), configuration_schema=dict(data.get("configuration_schema") or {}), health_check=str(data.get("health_check") or ""), package_checksum=str(data.get("package_checksum") or ""), signature=str(data.get("signature") or ""))

    @classmethod
    def load(cls, root: str | Path) -> "PluginManifest":
        path = Path(root) / "plugin.json"
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))