from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate
from typer.testing import CliRunner

from nous_runtime.extensions import (
    CapabilityRequest,
    CompatibilityLevel,
    ExtensionExporter,
    ExtensionInspector,
    ExtensionManifest,
    ExtensionRegistry,
    SkillSpec,
    assess_export_compatibility,
    canonical_semantics,
)
from nous_runtime.extensions.cli import extension_app
from nous_runtime.extensions.models import EntryPoint
from nous_runtime.extensions.models import ToolSpec


def _skill_package(root: Path) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\n"
        "name: portable-skill\n"
        "description: 可移植的测试技能。\n"
        "license: Apache-2.0\n"
        "compatibility: Agent Skills hosts\n"
        "allowed-tools: [Read, Search]\n"
        "metadata:\n"
        "  version: 1.2.3\n"
        "  category: testing\n"
        "---\n"
        "先读取上下文，再给出答案。\n",
        encoding="utf-8",
    )
    (root / "references").mkdir()
    (root / "references" / "指南.md").write_text("参考资料", encoding="utf-8")
    return root


def test_agent_skill_export_is_lossless_and_round_trips_without_authority(tmp_path: Path):
    registry = ExtensionRegistry(tmp_path / "registry")
    source_manifest = registry.install(_skill_package(tmp_path / "portable-skill"))

    result = ExtensionExporter(registry).export(
        source_manifest.extension_id,
        target_format="skill",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossless"
    exported = Path(result.package_path)
    assert (exported / "references" / "指南.md").read_text(encoding="utf-8") == "参考资料"
    report = json.loads((exported / "NOUS_EXPORT_REPORT.json").read_text(encoding="utf-8"))
    report_schema = json.loads(
        (Path(__file__).parents[2] / "spec/extensions/v1/extension-export-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate(report, report_schema)
    assert report["lossy_fields"] == []
    assert report["target_import_authority"] == "none"

    imported_again = ExtensionInspector().inspect(exported)
    assert canonical_semantics(imported_again) == canonical_semantics(source_manifest)
    second_registry = ExtensionRegistry(tmp_path / "second-registry")
    second_registry.install(exported)
    assert second_registry.get_record(source_manifest.extension_id)["authority"] == "none"
    assert second_registry.get_record(source_manifest.extension_id)["granted_capabilities"] == []


def test_lossy_security_and_executor_fields_are_reported_not_embedded(tmp_path: Path):
    source = _skill_package(tmp_path / "portable-skill")
    imported = ExtensionInspector().inspect(source)
    native_manifest = ExtensionManifest(
        extension_id="custom/portable-skill",
        version=imported.version,
        description=imported.description,
        source_format="nous-native",
        compatibility_level=CompatibilityLevel.IMPORT,
        kinds=("skill", "tool"),
        skills=imported.skills,
        capabilities=imported.capabilities
        + (CapabilityRequest("network.connect", "connect", ("api.example.test",)),),
        entry_points=(EntryPoint("process", "scripts/run.py"),),
        metadata={"policy": "local-only"},
    ).require_valid()
    native = tmp_path / "native"
    native.mkdir()
    (native / "nous.extension.json").write_text(
        json.dumps(native_manifest.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    (native / "references").mkdir()
    (native / "references" / "指南.md").write_text("参考资料", encoding="utf-8")
    registry = ExtensionRegistry(tmp_path / "registry")
    installed = registry.install(native)
    record = registry.get_record(installed.extension_id)
    assert record is not None
    record["authority"] = "kernel_grant"
    record["granted_capabilities"] = ["network.connect"]
    index = json.loads(registry.index_path.read_text(encoding="utf-8"))
    index["extensions"][installed.extension_id] = record
    registry.index_path.write_text(json.dumps(index), encoding="utf-8")
    registry._write_lock(index)

    result = ExtensionExporter(registry).export(
        installed.extension_id,
        target_format="skill",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossy"
    assert set(result.compatibility.lossy_fields) >= {
        "authority",
        "capabilities.authority_scope_policy",
        "entry_points.executor_constraints",
        "granted_capabilities",
    }
    skill_text = (Path(result.package_path) / "SKILL.md").read_text(encoding="utf-8")
    assert "kernel_grant" not in skill_text
    assert "api.example.test" not in skill_text
    second_registry = ExtensionRegistry(tmp_path / "reimported")
    reimported = second_registry.install(result.package_path)
    reimported_record = second_registry.get_record(reimported.extension_id)
    assert reimported_record is not None
    assert reimported_record["authority"] == "none"
    assert reimported_record["granted_capabilities"] == []


def test_agent_skill_export_rejects_unmappable_manifest():
    manifest = ExtensionManifest(
        extension_id="tools/only",
        version="1.0.0",
        description="tool only",
        source_format="nous-native",
        compatibility_level=CompatibilityLevel.IMPORT,
        kinds=("tool",),
    ).require_valid()

    compatibility = assess_export_compatibility(manifest, "skill")

    assert compatibility.status == "unsupported"
    assert "exactly one skill" in compatibility.unsupported_reasons[0]


def test_extension_export_cli_reports_compatibility(tmp_path: Path):
    registry_path = tmp_path / "registry"
    manifest = ExtensionRegistry(registry_path).install(
        _skill_package(tmp_path / "portable-skill")
    )

    result = CliRunner().invoke(
        extension_app,
        [
            "export",
            manifest.extension_id,
            "--format",
            "skill",
            "--output",
            str(tmp_path / "exports"),
            "--registry",
            str(registry_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["compatibility"]["status"] == "lossless"
    assert Path(payload["package_path"]).is_dir()


def test_legacy_json_skill_export_round_trips_semantics(tmp_path: Path):
    source = tmp_path / "legacy.json"
    source.write_text(
        json.dumps(
            {
                "id": "legacy-helper",
                "name": "legacy-helper",
                "description": "Legacy helper",
                "instruction": "Read before acting.",
                "tools": ["Read"],
                "permissions": ["network", "document.read"],
                "tool_profile": "reader",
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    original = registry.install(source)

    result = ExtensionExporter(registry).export(
        original.extension_id,
        target_format="nous-json-skill",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossless"
    exported = Path(result.package_path)
    imported_again = ExtensionInspector().inspect(exported)
    assert canonical_semantics(imported_again) == canonical_semantics(original)
    report_path = exported.with_name("legacy-helper.skill.nous-export-report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["target_format"] == "nous-json-skill"
    assert report["lossy_fields"] == []
    assert "kernel_grant" not in exported.read_text(encoding="utf-8")


def test_legacy_json_skill_reports_unrepresentable_resources():
    skill = SkillSpec(
        "example",
        "example",
        "instructions",
        resources=("references/guide.md",),
    )
    manifest = ExtensionManifest(
        extension_id="skills/example",
        version="1.0.0",
        description="example",
        source_format="agent-skill",
        compatibility_level=CompatibilityLevel.IMPORT,
        kinds=("skill",),
        skills=(skill,),
        capabilities=(
            CapabilityRequest(
                "filesystem.read",
                "read",
                skill.resources,
                "Read files shipped inside this skill package",
            ),
        ),
    ).require_valid()

    compatibility = assess_export_compatibility(manifest, "nous-json-skill")

    assert compatibility.status == "lossy"
    assert "skill_portability_fields" in compatibility.lossy_fields
    assert "capabilities.authority_scope_policy" in compatibility.lossy_fields


def test_openapi_export_round_trips_only_imported_openapi(tmp_path: Path):
    source = tmp_path / "service.json"
    source.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {
                    "title": "Portable Service",
                    "version": "1.0.0",
                    "description": "Portable API",
                },
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {
                    "/items/{id}": {
                        "get": {
                            "operationId": "getItem",
                            "summary": "Get item",
                            "parameters": [
                                {
                                    "name": "id",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "string"},
                                }
                            ],
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    original = registry.install(source)

    result = ExtensionExporter(registry).export(
        original.extension_id,
        target_format="openapi",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossless"
    reimported = ExtensionInspector().inspect(result.package_path)
    assert canonical_semantics(reimported) == canonical_semantics(original)
    report = json.loads(
        Path(result.package_path + ".nous-export-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["target_format"] == "openapi-3"


def test_arbitrary_network_tool_is_not_claimed_as_openapi_compatible():
    manifest = ExtensionManifest(
        extension_id="tools/firmware-flash",
        version="1.0.0",
        description="Firmware flashing",
        source_format="nous-native",
        compatibility_level=CompatibilityLevel.IMPORT,
        kinds=("tool",),
        tools=(
            ToolSpec(
                "flash",
                protocol="native",
                effect="write",
                operation="device.flash",
            ),
        ),
        capabilities=(CapabilityRequest("network.connect", "connect", ("device",)),),
    ).require_valid()

    compatibility = assess_export_compatibility(manifest, "openapi")

    assert compatibility.status == "unsupported"
    assert "arbitrary Nous tools" in compatibility.unsupported_reasons[0]


def test_mcp_export_rebuilds_redacted_config_and_round_trips(tmp_path: Path):
    source = tmp_path / ".mcp.json"
    source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": "python",
                        "args": ["server.py", "--中文"],
                        "env": {"API_TOKEN": "env:API_TOKEN"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    original = registry.install(source)

    result = ExtensionExporter(registry).export(
        original.extension_id,
        target_format="mcp",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossy"
    assert result.compatibility.lossy_fields == ("credential_values",)
    exported_text = Path(result.package_path).read_text(encoding="utf-8")
    assert "must-never-export" not in exported_text
    assert "API_TOKEN" in exported_text
    reimported = ExtensionInspector().inspect(result.package_path)
    assert canonical_semantics(reimported) == canonical_semantics(original)
    report = json.loads(
        Path(result.package_path).with_name(
            "local.mcp.nous-export-report.json"
        ).read_text(encoding="utf-8")
    )
    assert report["target_format"] == "mcp-config"
    assert report["target_import_authority"] == "none"


def test_legacy_plugin_export_round_trips_exact_ir(tmp_path: Path):
    source = tmp_path / "plugin-source"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "portable.plugin",
                "version": "1.2.3",
                "runtime_compatibility": ">=2.0",
                "entry_point": "portable_plugin:invoke",
                "capabilities": ["portable.echo"],
                "permissions": ["network", "filesystem.read"],
                "dependencies": ["base.plugin"],
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    installed = registry.install(source)
    original = registry.verify(installed.extension_id)

    result = ExtensionExporter(registry).export(
        original.extension_id,
        target_format="plugin",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossless"
    imported_again = ExtensionInspector().inspect(result.package_path)
    assert canonical_semantics(imported_again) == canonical_semantics(original)
    report = json.loads(
        (Path(result.package_path) / "NOUS_EXPORT_REPORT.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["target_format"] == "nous-plugin-v0"


@pytest.mark.parametrize(
    ("body", "target_format"),
    [
        (
            "name: runtime-pack\nversion: 1.0.0\ndescription: Runtime pack\n"
            "capabilities: [document.read]\n"
            "dependencies: {base-pack: '>=1'}\n"
            "models: [local-model]\nconfig: {mode: safe}\n",
            "nous-pack-runtime-v0",
        ),
        (
            "schema_version: 1\nname: kernel-pack\nversion: 1.1.0\n"
            "description: Kernel pack\nlicense: Apache-2.0\n"
            "resources: [docs/guide.md]\npolicies: [default-deny]\n",
            "nous-pack-kernel-v1",
        ),
    ],
)
def test_runtime_and_kernel_pack_export_round_trip(
    tmp_path: Path, body: str, target_format: str
):
    source = tmp_path / "pack-source"
    source.mkdir()
    (source / "pack.yaml").write_text(body, encoding="utf-8")
    registry = ExtensionRegistry(tmp_path / "registry")
    installed = registry.install(source)
    original = registry.verify(installed.extension_id)

    result = ExtensionExporter(registry).export(
        original.extension_id,
        target_format="pack",
        output_root=tmp_path / "exports",
    )

    assert result.compatibility.status == "lossless"
    assert result.loss_report.target_format == target_format
    imported_again = ExtensionInspector().inspect(result.package_path)
    assert canonical_semantics(imported_again) == canonical_semantics(original)


@pytest.mark.parametrize("target", ["openapi", "mcp", "unknown"])
def test_unregistered_export_targets_fail_closed(target: str):
    manifest = ExtensionManifest(
        extension_id="skills/example",
        version="1.0.0",
        description="example",
        source_format="nous-native",
        compatibility_level=CompatibilityLevel.IMPORT,
        kinds=("skill",),
        skills=(SkillSpec("example", "example", "instructions"),),
    ).require_valid()
    assert assess_export_compatibility(manifest, target).status == "unsupported"
