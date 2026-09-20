"""Import adapters that normalize established ecosystems into Extension IR."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from nous_runtime.extensions.models import (
    CapabilityRequest,
    CompatibilityLevel,
    EntryPoint,
    ExtensionManifest,
    Provenance,
    SkillSpec,
    ToolSpec,
)
from nous_runtime.extensions.sources import (
    ExtensionSource,
    file_digest,
    is_package_manifest,
    package_digest,
)
from nous_runtime.yaml_compat import yaml


class UnsupportedExtension(ValueError):
    pass


class ExtensionAdapter(Protocol):
    name: str

    def supports(self, root: Path, preferred_file: Path | None) -> bool: ...

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest: ...


class NativeAdapter:
    name = "nous-native-v1"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        return _named_file(root, preferred_file, "nous.extension.json") is not None

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        path = _named_file(root, preferred_file, "nous.extension.json")
        assert path is not None
        return ExtensionManifest.from_dict(_load_json(path)).require_valid()


class AgentSkillAdapter:
    """Agent Skills open-format adapter (SKILL.md plus optional resources)."""

    name = "agent-skill-v1"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        return _named_file(root, preferred_file, "SKILL.md") is not None

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        path = _named_file(root, preferred_file, "SKILL.md")
        assert path is not None
        metadata, instructions = _skill_markdown(path)
        name = str(metadata.get("name") or "").strip()
        if path.parent == root and root.name.lower() != name.lower():
            raise ValueError(f"SKILL.md name '{name}' must match directory '{root.name}'")
        allowed_raw = metadata.get("allowed-tools", ())
        if isinstance(allowed_raw, str):
            allowed_tools = tuple(value for value in allowed_raw.split() if value)
        elif isinstance(allowed_raw, list):
            allowed_tools = tuple(str(value) for value in allowed_raw if str(value).strip())
        else:
            raise ValueError("SKILL.md allowed-tools must be a string or array")
        resources = _skill_resources(path.parent)
        capabilities: list[CapabilityRequest] = []
        if resources:
            capabilities.append(
                CapabilityRequest(
                    "filesystem.read",
                    "read",
                    resources,
                    "Read files shipped inside this skill package",
                )
            )
        if any(resource.startswith("scripts/") for resource in resources):
            capabilities.append(
                CapabilityRequest(
                    "process.execute",
                    "execute",
                    tuple(resource for resource in resources if resource.startswith("scripts/")),
                    "The package contains scripts; import does not authorize execution",
                )
            )
        if allowed_tools:
            capabilities.append(
                CapabilityRequest(
                    "tool.invoke",
                    "use",
                    allowed_tools,
                    "Tools requested by SKILL.md allowed-tools",
                )
            )
        raw_metadata = metadata.get("metadata") or {}
        if not isinstance(raw_metadata, dict):
            raise ValueError("SKILL.md metadata must be a mapping")
        version = str(raw_metadata.get("version") or "0.0.0+imported")
        skill = SkillSpec(
            name=name,
            description=str(metadata.get("description") or "").strip(),
            instructions=instructions,
            license=str(metadata.get("license") or ""),
            compatibility=str(metadata.get("compatibility") or ""),
            allowed_tools=allowed_tools,
            resources=resources,
            metadata={str(key): str(value) for key, value in raw_metadata.items()},
        )
        return ExtensionManifest(
            extension_id=f"skills/{name}",
            version=version,
            description=skill.description,
            source_format="agent-skill",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("skill",),
            skills=(skill,),
            capabilities=tuple(capabilities),
            license=skill.license,
            metadata={"progressive_disclosure": True},
        ).require_valid()


class LegacySkillAdapter:
    name = "nous-json-skill-v1"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        path = preferred_file if preferred_file and preferred_file.suffix.lower() == ".json" else None
        if path is None:
            return False
        try:
            value = _load_json(path)
        except (OSError, ValueError):
            return False
        return isinstance(value, dict) and "instruction" in value and ("id" in value or "name" in value)

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        assert preferred_file is not None
        data = _load_json(preferred_file)
        skill_id = _slug(str(data.get("id") or data.get("name") or "skill"), hyphen=True)
        permissions = tuple(str(value) for value in data.get("permissions") or ())
        tools = tuple(str(value) for value in data.get("tools") or ())
        skill = SkillSpec(
            name=skill_id,
            description=str(data.get("description") or skill_id),
            instructions=str(data.get("instruction") or ""),
            allowed_tools=tools,
            metadata={"legacy_tool_profile": str(data.get("tool_profile") or "")},
        )
        capabilities = tuple(_permission_request(value) for value in permissions)
        if tools:
            capabilities += (CapabilityRequest("tool.invoke", "use", tools, "Legacy skill tools"),)
        return ExtensionManifest(
            extension_id=f"legacy-skills/{skill_id}",
            version="0.0.0+legacy",
            description=skill.description,
            source_format="nous-json-skill",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("skill",),
            skills=(skill,),
            capabilities=capabilities,
            metadata={"migration_required": True},
        ).require_valid()


class PluginAdapter:
    name = "nous-plugin-v0"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        return _named_file(root, preferred_file, "plugin.json") is not None

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        from nous_runtime.plugins.models import PluginManifest

        path = _named_file(root, preferred_file, "plugin.json")
        assert path is not None
        plugin = PluginManifest.from_dict(_load_json(path))
        errors = plugin.validate()
        if errors:
            raise ValueError("invalid legacy plugin: " + "; ".join(errors))
        capabilities = list(_permission_request(value) for value in plugin.permissions)
        if not any(item.capability == "process.execute" for item in capabilities):
            capabilities.append(
                CapabilityRequest(
                    "process.execute",
                    "execute",
                    (plugin.entry_point,),
                    "Invoke the imported plugin only through a governed executor",
                )
            )
        return ExtensionManifest(
            extension_id=f"plugins/{plugin.plugin_id}",
            version=plugin.version,
            description=f"Imported Nous plugin {plugin.plugin_id}",
            source_format="nous-plugin-v0",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("plugin", "tool"),
            tools=tuple(ToolSpec(name=value, protocol="python-plugin", effect="unknown") for value in plugin.capabilities),
            capabilities=tuple(capabilities),
            entry_points=(EntryPoint("python", plugin.entry_point, "nous-plugin-v0"),),
            dependencies={value: "declared" for value in plugin.dependencies},
            metadata={"runtime_compatibility": plugin.runtime_compatibility},
        ).require_valid()


class PackAdapter:
    """Bridge both historical Runtime and authoritative Kernel Pack shapes."""

    name = "nous-pack-bridge-v1"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        return _named_file(root, preferred_file, "pack.yaml") is not None

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        path = _named_file(root, preferred_file, "pack.yaml")
        assert path is not None
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("pack.yaml must contain a mapping")
        name = _slug(str(data.get("name") or ""))
        references = {
            key: tuple(str(value) for value in data.get(key) or ())
            for key in ("models", "providers", "workflows", "policies", "resources")
        }
        capabilities = tuple(
            CapabilityRequest(str(value), "use", (), "Legacy pack capability")
            for value in data.get("capabilities") or ()
        )
        dependencies = {
            _slug(str(key)): str(value)
            for key, value in (data.get("dependencies") or {}).items()
        }
        return ExtensionManifest(
            extension_id=f"packs/{name}",
            version=str(data.get("version") or ""),
            description=str(data.get("description") or name),
            source_format="nous-pack-kernel-v1" if "schema_version" in data else "nous-pack-runtime-v0",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("pack",),
            capabilities=capabilities,
            dependencies=dependencies,
            license=str(data.get("license") or ""),
            metadata={"references": references, "legacy_config": data.get("config") or {}},
        ).require_valid()


class OpenApiAdapter:
    name = "openapi-v3"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        for path in _candidate_data_files(root, preferred_file):
            try:
                data = _load_data(path)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and str(data.get("openapi") or "").startswith("3."):
                return True
        return False

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        path, data = _find_data(root, preferred_file, lambda value: str(value.get("openapi") or "").startswith("3."))
        info = data.get("info") or {}
        title = str(info.get("title") or path.stem)
        version = str(info.get("version") or "0.0.0+imported")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
            version = "0.0.0+imported"
        tools: list[ToolSpec] = []
        for route, path_item in (data.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                operation_id = str(operation.get("operationId") or f"{method}_{_slug(str(route))}")
                name = re.sub(r"[^A-Za-z0-9_.:-]+", "_", operation_id).strip("_")[:128]
                tools.append(
                    ToolSpec(
                        name=name,
                        description=str(operation.get("summary") or operation.get("description") or ""),
                        input_schema=_openapi_input_schema(path_item, operation),
                        output_schema={},
                        effect="read" if method in {"get", "head", "options"} else "write",
                        protocol="openapi",
                        operation=f"{method.upper()} {route}",
                    )
                )
        scopes = tuple(
            value
            for value in (_server_scope(item) for item in data.get("servers") or ())
            if value
        )
        return ExtensionManifest(
            extension_id=f"openapi/{_slug(title)}",
            version=version,
            description=str(info.get("description") or f"OpenAPI tools for {title}"),
            source_format="openapi-3",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("tool",),
            tools=tuple(tools),
            capabilities=(CapabilityRequest("network.connect", "connect", scopes, "Call the imported OpenAPI service"),),
            entry_points=(EntryPoint("openapi", path.name, "openapi-3"),),
            license=str((info.get("license") or {}).get("name") or ""),
            metadata={"openapi_version": str(data.get("openapi")), "tool_count": len(tools)},
        ).require_valid()


class McpConfigAdapter:
    """Import MCP server declarations; handshaking/execution stays disabled."""

    name = "mcp-config-v1"

    def supports(self, root: Path, preferred_file: Path | None) -> bool:
        try:
            _find_data(root, preferred_file, lambda value: isinstance(value.get("mcpServers"), dict))
            return True
        except (FileNotFoundError, ValueError):
            return False

    def load(self, root: Path, preferred_file: Path | None) -> ExtensionManifest:
        _, data = _find_data(root, preferred_file, lambda value: isinstance(value.get("mcpServers"), dict))
        servers = data["mcpServers"]
        entries: list[EntryPoint] = []
        capabilities: list[CapabilityRequest] = []
        for name, raw in sorted(servers.items()):
            config = raw if isinstance(raw, dict) else {}
            if config.get("command"):
                entries.append(EntryPoint("process", str(config["command"]), "mcp-stdio", _redact_mcp_config(config)))
                capabilities.append(CapabilityRequest("process.execute", "execute", (str(config["command"]),), f"Start MCP server {name}"))
            elif config.get("url"):
                entries.append(EntryPoint("remote", str(config["url"]), "mcp-http", _redact_mcp_config(config)))
                scope = _server_scope({"url": str(config["url"])})
                capabilities.append(CapabilityRequest("network.connect", "connect", (scope,) if scope else (), f"Connect to MCP server {name}"))
            else:
                raise ValueError(f"MCP server {name} requires command or url")
        bundle = next(iter(servers)) if len(servers) == 1 else "bundle"
        return ExtensionManifest(
            extension_id=f"mcp/{_slug(str(bundle))}",
            version="0.0.0+imported",
            description=f"Imported MCP configuration ({len(servers)} server(s))",
            source_format="mcp-config",
            compatibility_level=CompatibilityLevel.IMPORT,
            kinds=("plugin", "tool"),
            capabilities=tuple(capabilities),
            entry_points=tuple(entries),
            metadata={"server_names": sorted(str(value) for value in servers)},
        ).require_valid()


class ExtensionInspector:
    """Detect and normalize an extension source without activating it."""

    def __init__(self, adapters: tuple[ExtensionAdapter, ...] | None = None):
        self.adapters = adapters or (
            NativeAdapter(),
            AgentSkillAdapter(),
            PluginAdapter(),
            PackAdapter(),
            McpConfigAdapter(),
            OpenApiAdapter(),
            LegacySkillAdapter(),
        )

    def inspect(self, source: str | Path) -> ExtensionManifest:
        with ExtensionSource(source) as resolved:
            for adapter in self.adapters:
                if not adapter.supports(resolved.root, resolved.preferred_file):
                    continue
                manifest = adapter.load(resolved.root, resolved.preferred_file)
                provenance = Provenance(
                    source_type="zip" if resolved.source.suffix.lower() == ".zip" else "local",
                    source=str(resolved.source),
                    digest=(
                        package_digest(resolved.root)
                        if resolved.preferred_file is None
                        or is_package_manifest(resolved.preferred_file)
                        else file_digest(resolved.preferred_file)
                    ),
                    imported_at=datetime.now(timezone.utc).isoformat(),
                    adapter=adapter.name,
                )
                return replace(manifest, provenance=provenance).require_valid()
        raise UnsupportedExtension(f"no compatible extension format found at {source}")


def _named_file(root: Path, preferred: Path | None, name: str) -> Path | None:
    if preferred is not None and preferred.name.lower() == name.lower():
        return preferred
    candidate = root / name
    return candidate if candidate.is_file() else None


def _skill_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return metadata, "\n".join(lines[end + 1 :]).strip()


def _skill_resources(root: Path) -> tuple[str, ...]:
    resources: list[str] = []
    for directory in ("scripts", "references", "assets"):
        base = root / directory
        if not base.exists():
            continue
        if base.is_symlink() or not base.is_dir():
            raise ValueError(f"skill resource directory must be a real directory: {directory}")
        for path in base.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"skill resources may not contain symbolic links: {path}")
            if path.is_file():
                resources.append(path.relative_to(root).as_posix())
    return tuple(sorted(resources))


def _permission_request(permission: str) -> CapabilityRequest:
    mapping = {
        "network": ("network.connect", "connect"),
        "process": ("process.execute", "execute"),
        "connector": ("connector.use", "use"),
        "model": ("model.use", "use"),
    }
    capability, access = mapping.get(permission, (permission, "write" if permission.endswith(".write") else "read" if permission.endswith(".read") else "use"))
    return CapabilityRequest(capability, access, (), f"Imported permission: {permission}")


def _candidate_data_files(root: Path, preferred: Path | None) -> tuple[Path, ...]:
    if preferred is not None and preferred.suffix.lower() in {".json", ".yaml", ".yml"}:
        return (preferred,)
    names = ("openapi.json", "openapi.yaml", "openapi.yml", ".mcp.json", "mcp.json")
    return tuple(path for name in names if (path := root / name).is_file())


def _find_data(root: Path, preferred: Path | None, predicate) -> tuple[Path, dict[str, Any]]:
    for path in _candidate_data_files(root, preferred):
        data = _load_data(path)
        if isinstance(data, dict) and predicate(data):
            return path, data
    raise FileNotFoundError("compatible data manifest not found")


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain an object")
    return data


def _load_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)


def _slug(value: str, *, hyphen: bool = False) -> str:
    separator = "-" if hyphen else "_"
    result = re.sub(r"[^a-z0-9]+", separator, value.lower()).strip(separator)
    return result[:64] or "extension"


def _server_scope(server: Any) -> str:
    if not isinstance(server, dict):
        return ""
    parsed = urlparse(str(server.get("url") or ""))
    return parsed.netloc.lower()


def _openapi_input_schema(path_item: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    parameters = list(path_item.get("parameters") or ()) + list(operation.get("parameters") or ())
    for parameter in parameters:
        if not isinstance(parameter, dict) or "$ref" in parameter:
            continue
        name = str(parameter.get("name") or "")
        if not name:
            continue
        properties[name] = dict(parameter.get("schema") or {"type": "string"})
        if parameter.get("required"):
            required.append(name)
    body = operation.get("requestBody") or {}
    content = body.get("content") if isinstance(body, dict) else {}
    if isinstance(content, dict) and content:
        media = content.get("application/json") or next(iter(content.values()))
        if isinstance(media, dict):
            properties["body"] = dict(media.get("schema") or {"type": "object"})
            if body.get("required"):
                required.append("body")
    result: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        result["required"] = sorted(set(required))
    return result


def _redact_mcp_config(config: dict[str, Any]) -> dict[str, Any]:
    """Preserve launch shape while ensuring inline environment secrets never enter IR."""

    safe: dict[str, Any] = {}
    if isinstance(config.get("args"), list):
        safe["args"] = [str(value) for value in config["args"]]
    if isinstance(config.get("env"), dict):
        safe["credential_env_refs"] = sorted(str(key) for key in config["env"])
    return safe
