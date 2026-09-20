"""C4 extension export, compatibility, and semantic round-trip contracts."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from nous_runtime.extensions.models import CapabilityRequest, ExtensionManifest, SkillSpec
from nous_runtime.extensions.adapters import ExtensionInspector
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.yaml_compat import yaml

ExportStatus = Literal["lossless", "lossy", "unsupported"]
EXPORT_REPORT_SCHEMA = "nous.extension-export-report/v1"


class ExtensionExportError(ValueError):
    """Raised when an extension cannot be safely exported to the target format."""


@dataclass(frozen=True)
class ExportCompatibility:
    target_format: str
    status: ExportStatus
    lossy_fields: tuple[str, ...] = ()
    unsupported_reasons: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return self.status != "unsupported"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExportLossReport:
    extension_id: str
    target_format: str
    status: ExportStatus
    lossy_fields: tuple[str, ...]
    unsupported_reasons: tuple[str, ...]
    source_authority: str
    source_granted_capabilities: tuple[str, ...]
    target_import_authority: str = "none"
    schema: str = EXPORT_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtensionExportResult:
    package_path: str
    compatibility: ExportCompatibility
    loss_report: ExportLossReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_path": self.package_path,
            "compatibility": self.compatibility.to_dict(),
            "loss_report": self.loss_report.to_dict(),
        }


class ExtensionExporter:
    """Export verified registry objects without carrying Kernel authority."""

    def __init__(self, registry: ExtensionRegistry):
        self.registry = registry

    def compatibility(self, extension_id: str, target_format: str) -> ExportCompatibility:
        manifest = self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id) or {}
        return assess_export_compatibility(manifest, target_format, record=record)

    def export(
        self,
        extension_id: str,
        *,
        target_format: str,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        manifest = self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id) or {}
        compatibility = assess_export_compatibility(
            manifest, target_format, record=record
        )
        if not compatibility.supported:
            reasons = "; ".join(compatibility.unsupported_reasons)
            raise ExtensionExportError(
                f"extension cannot be exported as {target_format}: {reasons}"
            )
        normalized = target_format.strip().lower()
        if normalized in {"openapi", "openapi-3"}:
            return self._export_openapi(
                manifest, record, compatibility, extension_id, output_root
            )
        if normalized in {"mcp", "mcp-config"}:
            return self._export_mcp(manifest, record, compatibility, output_root)
        if normalized in {"plugin", "nous-plugin-v0"}:
            return self._export_plugin(manifest, record, compatibility, output_root)
        if normalized in {"pack", "nous-pack"}:
            return self._export_pack(manifest, record, compatibility, output_root)
        skill = manifest.skills[0]
        if normalized in {"nous-json-skill", "legacy-skill"}:
            return self._export_legacy_skill(
                manifest, skill, record, compatibility, output_root
            )
        if normalized not in {"skill", "agent-skill"}:
            raise ExtensionExportError(f"unsupported export format: {target_format}")
        destination = Path(output_root).expanduser().resolve() / skill.name
        if destination.exists():
            raise ExtensionExportError(f"export destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)

        authority = str(record.get("authority") or "none")
        grants = tuple(sorted(str(value) for value in record.get("granted_capabilities") or ()))
        report = ExportLossReport(
            extension_id=manifest.extension_id,
            target_format="agent-skill",
            status=compatibility.status,
            lossy_fields=compatibility.lossy_fields,
            unsupported_reasons=compatibility.unsupported_reasons,
            source_authority=authority,
            source_granted_capabilities=grants,
        )

        temporary = Path(
            tempfile.mkdtemp(prefix=f".{skill.name}.export-", dir=str(destination.parent))
        )
        try:
            self._write_skill(temporary, skill)
            self._copy_resources(
                self.registry.package_path(extension_id), temporary, skill.resources
            )
            _write_json(temporary / "NOUS_EXPORT_REPORT.json", report.to_dict())
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

        return ExtensionExportResult(str(destination), compatibility, report)

    def _export_openapi(
        self,
        manifest: ExtensionManifest,
        record: dict[str, Any],
        compatibility: ExportCompatibility,
        extension_id: str,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        entry = manifest.entry_points[0]
        source = _safe_package_file(self.registry.package_path(extension_id), entry.target)
        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = root / source.name
        report_path = root / f"{source.name}.nous-export-report.json"
        if destination.exists() or report_path.exists():
            raise ExtensionExportError(f"export destination already exists: {destination}")
        report = _loss_report(manifest, record, compatibility, "openapi-3")
        temporary = destination.with_name(f".{destination.name}.exporting")
        try:
            shutil.copy2(source, temporary)
            round_trip = _inspect_for_round_trip(temporary, destination.name)
            if canonical_semantics(round_trip) != canonical_semantics(manifest):
                raise ExtensionExportError("OpenAPI semantic round-trip verification failed")
            temporary.replace(destination)
            _write_json(report_path, report.to_dict())
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        return ExtensionExportResult(str(destination), compatibility, report)

    @staticmethod
    def _export_mcp(
        manifest: ExtensionManifest,
        record: dict[str, Any],
        compatibility: ExportCompatibility,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        names = [str(value) for value in manifest.metadata["server_names"]]
        servers: dict[str, Any] = {}
        for name, entry in zip(names, manifest.entry_points, strict=True):
            if entry.kind == "process" and entry.protocol == "mcp-stdio":
                config: dict[str, Any] = {"command": entry.target}
                if entry.configuration.get("args"):
                    config["args"] = list(entry.configuration["args"])
                refs = entry.configuration.get("credential_env_refs") or ()
                if refs:
                    config["env"] = {str(key): "" for key in refs}
                servers[name] = config
            else:
                servers[name] = {"url": entry.target}
        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        bundle = names[0] if len(names) == 1 else "bundle"
        destination = root / f"{bundle}.mcp.json"
        report_path = root / f"{bundle}.mcp.nous-export-report.json"
        if destination.exists() or report_path.exists():
            raise ExtensionExportError(f"export destination already exists: {destination}")
        report = _loss_report(manifest, record, compatibility, "mcp-config")
        _write_json(destination, {"mcpServers": servers})
        try:
            round_trip = ExtensionInspector().inspect(destination)
            if canonical_semantics(round_trip) != canonical_semantics(manifest):
                raise ExtensionExportError("MCP semantic round-trip verification failed")
            _write_json(report_path, report.to_dict())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return ExtensionExportResult(str(destination), compatibility, report)

    @staticmethod
    def _export_plugin(
        manifest: ExtensionManifest,
        record: dict[str, Any],
        compatibility: ExportCompatibility,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        plugin_id = manifest.extension_id.removeprefix("plugins/")
        entry = manifest.entry_points[0]
        permissions = []
        for capability in manifest.capabilities:
            is_auto_process = (
                capability.capability == "process.execute"
                and capability.scope == (entry.target,)
                and capability.reason
                == "Invoke the imported plugin only through a governed executor"
            )
            if not is_auto_process:
                permissions.append(_legacy_permission(capability))
        payload = {
            "plugin_id": plugin_id,
            "version": manifest.version,
            "runtime_compatibility": manifest.metadata["runtime_compatibility"],
            "entry_point": entry.target,
            "capabilities": [tool.name for tool in manifest.tools],
            "permissions": permissions,
            "dependencies": list(manifest.dependencies),
            "configuration_schema": {},
            "health_check": "",
            "package_checksum": "",
            "signature": "",
        }
        return _export_directory_manifest(
            manifest,
            record,
            compatibility,
            output_root,
            directory_name=plugin_id,
            manifest_name="plugin.json",
            target_format="nous-plugin-v0",
            payload=payload,
            yaml_output=False,
        )

    @staticmethod
    def _export_pack(
        manifest: ExtensionManifest,
        record: dict[str, Any],
        compatibility: ExportCompatibility,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        name = manifest.extension_id.removeprefix("packs/")
        references = manifest.metadata["references"]
        payload: dict[str, Any] = {
            "name": name,
            "version": manifest.version,
            "description": manifest.description,
        }
        if manifest.source_format == "nous-pack-kernel-v1":
            payload["schema_version"] = 1
        if manifest.license:
            payload["license"] = manifest.license
        for key in ("models", "providers", "workflows", "policies", "resources"):
            values = references.get(key) or ()
            if values:
                payload[key] = list(values)
        if manifest.capabilities:
            payload["capabilities"] = [item.capability for item in manifest.capabilities]
        if manifest.dependencies:
            payload["dependencies"] = manifest.dependencies
        if manifest.metadata.get("legacy_config"):
            payload["config"] = manifest.metadata["legacy_config"]
        return _export_directory_manifest(
            manifest,
            record,
            compatibility,
            output_root,
            directory_name=name,
            manifest_name="pack.yaml",
            target_format=manifest.source_format,
            payload=payload,
            yaml_output=True,
        )

    @staticmethod
    def _export_legacy_skill(
        manifest: ExtensionManifest,
        skill: SkillSpec,
        record: dict[str, Any],
        compatibility: ExportCompatibility,
        output_root: str | Path,
    ) -> ExtensionExportResult:
        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = root / f"{skill.name}.skill.json"
        report_path = root / f"{skill.name}.skill.nous-export-report.json"
        if destination.exists() or report_path.exists():
            raise ExtensionExportError(f"export destination already exists: {destination}")
        authority = str(record.get("authority") or "none")
        grants = tuple(sorted(str(value) for value in record.get("granted_capabilities") or ()))
        report = ExportLossReport(
            extension_id=manifest.extension_id,
            target_format="nous-json-skill",
            status=compatibility.status,
            lossy_fields=compatibility.lossy_fields,
            unsupported_reasons=compatibility.unsupported_reasons,
            source_authority=authority,
            source_granted_capabilities=grants,
        )
        permissions = [
            _legacy_permission(capability)
            for capability in manifest.capabilities
            if capability.capability != "tool.invoke"
        ]
        payload = {
            "id": skill.name,
            "name": skill.name,
            "description": skill.description,
            "instruction": skill.instructions,
            "tools": list(skill.allowed_tools),
            "permissions": permissions,
            "tool_profile": skill.metadata.get("legacy_tool_profile", ""),
        }
        _write_json(destination, payload)
        try:
            _write_json(report_path, report.to_dict())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return ExtensionExportResult(str(destination), compatibility, report)

    @staticmethod
    def _write_skill(destination: Path, skill: SkillSpec) -> None:
        metadata: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
        }
        if skill.license:
            metadata["license"] = skill.license
        if skill.compatibility:
            metadata["compatibility"] = skill.compatibility
        if skill.allowed_tools:
            metadata["allowed-tools"] = list(skill.allowed_tools)
        nested = dict(skill.metadata)
        if "version" not in nested:
            nested["version"] = "0.0.0+exported"
        if nested:
            metadata["metadata"] = nested
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()
        (destination / "SKILL.md").write_text(
            f"---\n{frontmatter}\n---\n{skill.instructions.strip()}\n",
            encoding="utf-8",
        )

    @staticmethod
    def _copy_resources(source: Path, destination: Path, resources: tuple[str, ...]) -> None:
        source = source.resolve()
        for relative in resources:
            candidate = (source / relative).resolve()
            try:
                candidate.relative_to(source)
            except ValueError as exc:
                raise ExtensionExportError(f"resource escapes package: {relative}") from exc
            if candidate.is_symlink() or not candidate.is_file():
                raise ExtensionExportError(f"resource is not a regular package file: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)


def assess_export_compatibility(
    manifest: ExtensionManifest,
    target_format: str,
    *,
    record: dict[str, Any] | None = None,
) -> ExportCompatibility:
    """Classify an export without performing I/O or granting authority."""

    normalized = target_format.strip().lower()
    if normalized in {"nous-json-skill", "legacy-skill"}:
        return _assess_legacy_skill(manifest, record or {})
    if normalized in {"openapi", "openapi-3"}:
        return _assess_openapi(manifest, record or {})
    if normalized in {"mcp", "mcp-config"}:
        return _assess_mcp(manifest, record or {})
    if normalized in {"plugin", "nous-plugin-v0"}:
        return _assess_plugin(manifest, record or {})
    if normalized in {"pack", "nous-pack"}:
        return _assess_pack(manifest, record or {})
    if normalized not in {"skill", "agent-skill"}:
        return ExportCompatibility(
            normalized,
            "unsupported",
            unsupported_reasons=("target format has no registered exporter",),
        )
    if len(manifest.skills) != 1:
        return ExportCompatibility(
            "agent-skill",
            "unsupported",
            unsupported_reasons=("Agent Skills export requires exactly one skill",),
        )

    skill = manifest.skills[0]
    lossy: set[str] = set()
    if manifest.extension_id != f"skills/{skill.name}":
        lossy.add("extension_id")
    if tuple(manifest.kinds) != ("skill",):
        lossy.add("kinds")
    if manifest.tools:
        lossy.add("tools")
    if manifest.entry_points:
        lossy.add("entry_points.executor_constraints")
    if manifest.dependencies:
        lossy.add("dependencies")
    if manifest.metadata and manifest.metadata != {"progressive_disclosure": True}:
        lossy.add("extension_metadata")
    if manifest.license and manifest.license != skill.license:
        lossy.add("license")
    if tuple(manifest.capabilities) != _skill_implied_capabilities(skill):
        lossy.add("capabilities.authority_scope_policy")

    record = record or {}
    if str(record.get("authority") or "none") != "none":
        lossy.add("authority")
    if record.get("granted_capabilities"):
        lossy.add("granted_capabilities")
    return ExportCompatibility(
        "agent-skill",
        "lossy" if lossy else "lossless",
        tuple(sorted(lossy)),
    )


def _assess_legacy_skill(
    manifest: ExtensionManifest, record: dict[str, Any]
) -> ExportCompatibility:
    if len(manifest.skills) != 1:
        return ExportCompatibility(
            "nous-json-skill",
            "unsupported",
            unsupported_reasons=("legacy JSON Skill export requires exactly one skill",),
        )
    skill = manifest.skills[0]
    lossy: set[str] = set()
    if manifest.extension_id != f"legacy-skills/{skill.name}":
        lossy.add("extension_id")
    if manifest.version != "0.0.0+legacy":
        lossy.add("version")
    if tuple(manifest.kinds) != ("skill",):
        lossy.add("kinds")
    if manifest.tools:
        lossy.add("tools")
    if manifest.entry_points:
        lossy.add("entry_points.executor_constraints")
    if manifest.dependencies:
        lossy.add("dependencies")
    if manifest.license or skill.license or skill.compatibility or skill.resources:
        lossy.add("skill_portability_fields")
    if set(skill.metadata) - {"legacy_tool_profile"}:
        lossy.add("skill_metadata")
    if manifest.metadata != {"migration_required": True}:
        lossy.add("extension_metadata")
    for capability in manifest.capabilities:
        if capability.capability == "tool.invoke":
            if (
                capability.access != "use"
                or capability.scope != skill.allowed_tools
                or capability.reason != "Legacy skill tools"
            ):
                lossy.add("capabilities.authority_scope_policy")
            continue
        permission = _legacy_permission(capability)
        expected = _legacy_capability(permission)
        if capability != expected:
            lossy.add("capabilities.authority_scope_policy")
    if str(record.get("authority") or "none") != "none":
        lossy.add("authority")
    if record.get("granted_capabilities"):
        lossy.add("granted_capabilities")
    return ExportCompatibility(
        "nous-json-skill",
        "lossy" if lossy else "lossless",
        tuple(sorted(lossy)),
    )


def _legacy_permission(capability: CapabilityRequest) -> str:
    reverse = {
        "network.connect": "network",
        "process.execute": "process",
        "connector.use": "connector",
        "model.use": "model",
    }
    return reverse.get(capability.capability, capability.capability)


def _legacy_capability(permission: str) -> CapabilityRequest:
    mapping = {
        "network": ("network.connect", "connect"),
        "process": ("process.execute", "execute"),
        "connector": ("connector.use", "use"),
        "model": ("model.use", "use"),
    }
    capability, access = mapping.get(
        permission,
        (
            permission,
            "write"
            if permission.endswith(".write")
            else "read"
            if permission.endswith(".read")
            else "use",
        ),
    )
    return CapabilityRequest(capability, access, (), f"Imported permission: {permission}")


def _assess_openapi(
    manifest: ExtensionManifest, record: dict[str, Any]
) -> ExportCompatibility:
    compatible = (
        manifest.source_format == "openapi-3"
        and len(manifest.entry_points) == 1
        and manifest.entry_points[0].kind == "openapi"
        and manifest.entry_points[0].protocol == "openapi-3"
        and all(tool.protocol == "openapi" and tool.operation for tool in manifest.tools)
        and len(manifest.capabilities) == 1
        and manifest.capabilities[0].capability == "network.connect"
    )
    if not compatible:
        return ExportCompatibility(
            "openapi-3",
            "unsupported",
            unsupported_reasons=(
                "OpenAPI export requires an imported OpenAPI document; arbitrary Nous tools are not mappable",
            ),
        )
    lossy = _authority_losses(record)
    return ExportCompatibility("openapi-3", "lossy" if lossy else "lossless", lossy)


def _assess_mcp(
    manifest: ExtensionManifest, record: dict[str, Any]
) -> ExportCompatibility:
    names = manifest.metadata.get("server_names")
    compatible = (
        manifest.source_format == "mcp-config"
        and isinstance(names, list)
        and len(names) == len(manifest.entry_points)
        and bool(names)
        and all(
            (entry.kind, entry.protocol) in {
                ("process", "mcp-stdio"),
                ("remote", "mcp-http"),
            }
            for entry in manifest.entry_points
        )
    )
    if not compatible:
        return ExportCompatibility(
            "mcp-config",
            "unsupported",
            unsupported_reasons=(
                "MCP export requires a normalized MCP config; arbitrary Nous tools are not MCP servers",
            ),
        )
    lossy = set(_authority_losses(record))
    if any(entry.configuration.get("credential_env_refs") for entry in manifest.entry_points):
        lossy.add("credential_values")
    return ExportCompatibility(
        "mcp-config", "lossy" if lossy else "lossless", tuple(sorted(lossy))
    )


def _assess_plugin(
    manifest: ExtensionManifest, record: dict[str, Any]
) -> ExportCompatibility:
    entry = manifest.entry_points[0] if len(manifest.entry_points) == 1 else None
    allowed_permissions = {
        "filesystem.read",
        "filesystem.write",
        "network",
        "process",
        "connector",
        "model",
    }
    capabilities_fit = entry is not None
    if entry is not None:
        for capability in manifest.capabilities:
            auto_process = (
                capability.capability == "process.execute"
                and capability.scope == (entry.target,)
                and capability.reason
                == "Invoke the imported plugin only through a governed executor"
            )
            if auto_process:
                continue
            permission = _legacy_permission(capability)
            if permission not in allowed_permissions or capability != _legacy_capability(
                permission
            ):
                capabilities_fit = False
    compatible = (
        manifest.source_format == "nous-plugin-v0"
        and manifest.extension_id.startswith("plugins/")
        and tuple(manifest.kinds) == ("plugin", "tool")
        and entry is not None
        and entry.kind == "python"
        and entry.protocol == "nous-plugin-v0"
        and all(
            tool.protocol == "python-plugin"
            and tool.effect == "unknown"
            and not tool.operation
            for tool in manifest.tools
        )
        and bool(manifest.tools)
        and all(value == "declared" for value in manifest.dependencies.values())
        and set(manifest.metadata) == {"runtime_compatibility"}
        and capabilities_fit
        and not manifest.skills
        and not manifest.license
    )
    if not compatible:
        return ExportCompatibility(
            "nous-plugin-v0",
            "unsupported",
            unsupported_reasons=(
                "legacy Plugin export requires the exact imported plugin semantic shape",
            ),
        )
    losses = _authority_losses(record)
    return ExportCompatibility(
        "nous-plugin-v0", "lossy" if losses else "lossless", losses
    )


def _assess_pack(
    manifest: ExtensionManifest, record: dict[str, Any]
) -> ExportCompatibility:
    references = manifest.metadata.get("references")
    compatible = (
        manifest.source_format in {"nous-pack-runtime-v0", "nous-pack-kernel-v1"}
        and manifest.extension_id.startswith("packs/")
        and tuple(manifest.kinds) == ("pack",)
        and not manifest.skills
        and not manifest.tools
        and not manifest.entry_points
        and isinstance(references, dict)
        and set(manifest.metadata) == {"references", "legacy_config"}
        and all(
            item.access == "use"
            and not item.scope
            and item.reason == "Legacy pack capability"
            for item in manifest.capabilities
        )
    )
    if not compatible:
        return ExportCompatibility(
            "nous-pack",
            "unsupported",
            unsupported_reasons=(
                "Pack export requires an exact imported Runtime or Kernel Pack shape",
            ),
        )
    losses = _authority_losses(record)
    return ExportCompatibility(
        manifest.source_format, "lossy" if losses else "lossless", losses
    )


def _authority_losses(record: dict[str, Any]) -> tuple[str, ...]:
    losses: set[str] = set()
    if str(record.get("authority") or "none") != "none":
        losses.add("authority")
    if record.get("granted_capabilities"):
        losses.add("granted_capabilities")
    return tuple(sorted(losses))


def _loss_report(
    manifest: ExtensionManifest,
    record: dict[str, Any],
    compatibility: ExportCompatibility,
    target_format: str,
) -> ExportLossReport:
    return ExportLossReport(
        extension_id=manifest.extension_id,
        target_format=target_format,
        status=compatibility.status,
        lossy_fields=compatibility.lossy_fields,
        unsupported_reasons=compatibility.unsupported_reasons,
        source_authority=str(record.get("authority") or "none"),
        source_granted_capabilities=tuple(
            sorted(str(value) for value in record.get("granted_capabilities") or ())
        ),
    )


def _safe_package_file(package: Path, relative: str) -> Path:
    package = package.resolve()
    candidate = (package / relative).resolve()
    try:
        candidate.relative_to(package)
    except ValueError as exc:
        raise ExtensionExportError(f"entry point escapes package: {relative}") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise ExtensionExportError(f"entry point is not a package file: {relative}")
    return candidate


def _inspect_for_round_trip(path: Path, final_name: str) -> ExtensionManifest:
    probe = path.with_name(final_name)
    path.replace(probe)
    try:
        return ExtensionInspector().inspect(probe)
    finally:
        probe.replace(path)


def _export_directory_manifest(
    manifest: ExtensionManifest,
    record: dict[str, Any],
    compatibility: ExportCompatibility,
    output_root: str | Path,
    *,
    directory_name: str,
    manifest_name: str,
    target_format: str,
    payload: dict[str, Any],
    yaml_output: bool,
) -> ExtensionExportResult:
    destination = Path(output_root).expanduser().resolve() / directory_name
    if destination.exists():
        raise ExtensionExportError(f"export destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{directory_name}.export-", dir=str(destination.parent))
    )
    report = _loss_report(manifest, record, compatibility, target_format)
    try:
        path = temporary / manifest_name
        if yaml_output:
            path.write_text(
                yaml.safe_dump(
                    payload,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        else:
            _write_json(path, payload)
        _write_json(temporary / "NOUS_EXPORT_REPORT.json", report.to_dict())
        round_trip = ExtensionInspector().inspect(temporary)
        if canonical_semantics(round_trip) != canonical_semantics(manifest):
            raise ExtensionExportError(
                f"{target_format} semantic round-trip verification failed"
            )
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return ExtensionExportResult(str(destination), compatibility, report)


def canonical_semantics(manifest: ExtensionManifest) -> dict[str, Any]:
    """Canonical semantic representation used by C4 round-trip tests."""

    value = {
        "extension_id": manifest.extension_id,
        "version": manifest.version,
        "description": manifest.description,
        "kinds": list(manifest.kinds),
        "skills": [asdict(skill) for skill in manifest.skills],
        "tools": [asdict(tool) for tool in manifest.tools],
        "capabilities": [asdict(capability) for capability in manifest.capabilities],
        "entry_points": [asdict(entry) for entry in manifest.entry_points],
        "dependencies": dict(sorted(manifest.dependencies.items())),
        "license": manifest.license,
        "metadata": manifest.metadata,
    }
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _skill_implied_capabilities(skill: SkillSpec) -> tuple[CapabilityRequest, ...]:
    capabilities: list[CapabilityRequest] = []
    if skill.resources:
        capabilities.append(
            CapabilityRequest(
                "filesystem.read",
                "read",
                skill.resources,
                "Read files shipped inside this skill package",
            )
        )
    scripts = tuple(value for value in skill.resources if value.startswith("scripts/"))
    if scripts:
        capabilities.append(
            CapabilityRequest(
                "process.execute",
                "execute",
                scripts,
                "The package contains scripts; import does not authorize execution",
            )
        )
    if skill.allowed_tools:
        capabilities.append(
            CapabilityRequest(
                "tool.invoke",
                "use",
                skill.allowed_tools,
                "Tools requested by SKILL.md allowed-tools",
            )
        )
    return tuple(capabilities)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
