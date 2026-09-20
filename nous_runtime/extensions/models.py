"""Canonical, vendor-neutral Nous Extension IR v1.

This module contains data only. ``CapabilityRequest`` is an untrusted request
made by an imported package, not an authorization decision.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any

from nous_runtime.schema_registry import EXTENSION_SCHEMA_VERSION as SCHEMA_VERSION

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._/-]{0,126}[a-z0-9])?$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$")
_TOOL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,127})$")


class CompatibilityLevel(IntEnum):
    """Observable compatibility, never a trust rating."""

    DISCOVER = 0
    VALIDATE = 1
    IMPORT = 2
    GOVERNED_EXECUTION = 3
    ROUND_TRIP = 4
    CERTIFIED = 5


@dataclass(frozen=True)
class CapabilityRequest:
    capability: str
    access: str = "use"
    scope: tuple[str, ...] = ()
    reason: str = ""
    required: bool = True

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not _CAPABILITY.fullmatch(self.capability):
            errors.append(f"invalid capability: {self.capability}")
        if self.access not in {"read", "write", "execute", "connect", "use"}:
            errors.append(f"invalid capability access: {self.access}")
        for value in self.scope:
            if not value or "\x00" in value:
                errors.append(f"invalid scope for {self.capability}")
        return errors


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = field(default_factory=dict)
    effect: str = "unknown"
    protocol: str = "native"
    operation: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not _TOOL.fullmatch(self.name):
            errors.append(f"invalid tool name: {self.name}")
        if self.effect not in {"none", "read", "write", "execute", "network", "unknown"}:
            errors.append(f"invalid effect for tool {self.name}: {self.effect}")
        if not isinstance(self.input_schema, dict):
            errors.append(f"input_schema for {self.name} must be an object")
        return errors


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    instructions: str
    license: str = ""
    compatibility: str = ""
    allowed_tools: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.name) or len(self.name) > 64:
            errors.append("skill name must be 1-64 lowercase letters, digits, or hyphens")
        if not self.description or len(self.description) > 1024:
            errors.append("skill description must be 1-1024 characters")
        if not self.instructions.strip():
            errors.append("skill instructions must not be empty")
        for resource in self.resources:
            if unsafe_relative_path(resource):
                errors.append(f"unsafe skill resource: {resource}")
        return errors


@dataclass(frozen=True)
class EntryPoint:
    kind: str
    target: str
    protocol: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Provenance:
    source_type: str
    source: str
    digest: str
    imported_at: str
    adapter: str


@dataclass(frozen=True)
class ExtensionManifest:
    """The one normalized contract consumed by Nous policy/UI components."""

    extension_id: str
    version: str
    description: str
    source_format: str
    compatibility_level: CompatibilityLevel
    kinds: tuple[str, ...]
    skills: tuple[SkillSpec, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    capabilities: tuple[CapabilityRequest, ...] = ()
    entry_points: tuple[EntryPoint, ...] = ()
    dependencies: dict[str, str] = field(default_factory=dict)
    license: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    schema: str = SCHEMA_VERSION

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.schema != SCHEMA_VERSION:
            errors.append(f"unsupported extension schema: {self.schema}")
        if not _ID.fullmatch(self.extension_id):
            errors.append(f"invalid extension id: {self.extension_id}")
        if not _SEMVER.fullmatch(self.version):
            errors.append(f"invalid extension version: {self.version}")
        allowed_kinds = {"skill", "tool", "plugin", "provider", "agent", "template", "pack"}
        invalid_kinds = set(self.kinds) - allowed_kinds
        if not self.kinds or invalid_kinds:
            errors.append("invalid extension kinds: " + ", ".join(sorted(invalid_kinds)))
        if len(set(self.kinds)) != len(self.kinds):
            errors.append("duplicate extension kind")
        for skill in self.skills:
            errors.extend(skill.validate())
        for tool in self.tools:
            errors.extend(tool.validate())
        for capability in self.capabilities:
            errors.extend(capability.validate())
        for dependency, constraint in self.dependencies.items():
            if not _ID.fullmatch(dependency) or not str(constraint).strip():
                errors.append(f"invalid dependency: {dependency}")
        if self.provenance and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.provenance.digest):
            errors.append("provenance digest must be lowercase sha256")
        return errors

    def require_valid(self) -> "ExtensionManifest":
        errors = self.validate()
        if errors:
            raise ValueError("invalid extension manifest:\n" + "\n".join(f"  - {error}" for error in errors))
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["compatibility_level"] = int(self.compatibility_level)
        return _json_compatible(data)

    def kernel_projection(self, executor: str | None = None) -> dict[str, Any]:
        """Build a data-only request for the independent Rust Kernel."""
        if self.provenance is None:
            raise ValueError("extension provenance is required for Kernel admission")
        selected = executor
        if selected is None:
            selected = self.entry_points[0].kind if self.entry_points else ""
        if not selected and any(
            item.capability == "process.execute" for item in self.capabilities
        ):
            selected = "process"
        return {
            "schema_version": 1,
            "extension_id": self.extension_id,
            "version": self.version,
            "content_digest": self.provenance.digest,
            "source_format": self.source_format,
            "compatibility_level": int(self.compatibility_level),
            "kinds": list(self.kinds),
            "capability_requests": [
                {
                    "capability": item.capability,
                    "access": item.access,
                    "scope": list(item.scope),
                    "reason": item.reason,
                    "required": item.required,
                }
                for item in self.capabilities
            ],
            "executor": selected,
            "metadata": {"authority": "none"},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtensionManifest":
        provenance = data.get("provenance")
        return cls(
            schema=str(data.get("schema") or SCHEMA_VERSION),
            extension_id=str(data.get("extension_id") or ""),
            version=str(data.get("version") or ""),
            description=str(data.get("description") or ""),
            source_format=str(data.get("source_format") or "nous-native"),
            compatibility_level=CompatibilityLevel(int(data.get("compatibility_level", 0))),
            kinds=tuple(str(item) for item in data.get("kinds") or ()),
            skills=tuple(
                SkillSpec(
                    name=str(item.get("name") or ""),
                    description=str(item.get("description") or ""),
                    instructions=str(item.get("instructions") or ""),
                    license=str(item.get("license") or ""),
                    compatibility=str(item.get("compatibility") or ""),
                    allowed_tools=tuple(str(value) for value in item.get("allowed_tools") or ()),
                    resources=tuple(str(value) for value in item.get("resources") or ()),
                    metadata={str(key): str(value) for key, value in (item.get("metadata") or {}).items()},
                )
                for item in data.get("skills") or ()
            ),
            tools=tuple(ToolSpec(**item) for item in data.get("tools") or ()),
            capabilities=tuple(
                CapabilityRequest(
                    capability=str(item.get("capability") or ""),
                    access=str(item.get("access") or "use"),
                    scope=tuple(str(value) for value in item.get("scope") or ()),
                    reason=str(item.get("reason") or ""),
                    required=bool(item.get("required", True)),
                )
                for item in data.get("capabilities") or ()
            ),
            entry_points=tuple(EntryPoint(**item) for item in data.get("entry_points") or ()),
            dependencies={str(key): str(value) for key, value in (data.get("dependencies") or {}).items()},
            license=str(data.get("license") or ""),
            metadata=dict(data.get("metadata") or {}),
            provenance=Provenance(**provenance) if provenance else None,
        )


def unsafe_relative_path(value: str) -> bool:
    """Return true for paths that could escape an imported package."""

    normalized = value.replace("\\", "/")
    return (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized) is not None
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or "\x00" in normalized
    )


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value
