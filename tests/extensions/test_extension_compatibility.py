from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import validate

from nous_runtime.extensions import ExtensionInspector, ExtensionManifest, ExtensionRegistry
from nous_runtime.extensions.models import CompatibilityLevel
from nous_runtime.extensions.sources import UnsafeExtensionSource, package_digest


def make_skill(root: Path, *, name: str = "code-helper") -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Safely inspect and explain code.\n"
        "license: Apache-2.0\n"
        "compatibility: Nous and Agent Skills compatible hosts\n"
        "allowed-tools: Read Search\n"
        "metadata:\n"
        "  version: 1.2.3\n"
        "---\n"
        "Read the project context before proposing changes.\n",
        encoding="utf-8",
    )
    (root / "references").mkdir()
    (root / "references" / "guide.md").write_text("reference", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "never_run.py").write_text(
        "from pathlib import Path\nPath('executed').write_text('bad')\n",
        encoding="utf-8",
    )
    return root


def test_agent_skill_is_imported_without_execution(tmp_path: Path):
    source = make_skill(tmp_path / "code-helper")
    manifest = ExtensionInspector().inspect(source)

    assert manifest.extension_id == "skills/code-helper"
    assert manifest.version == "1.2.3"
    assert manifest.compatibility_level == CompatibilityLevel.IMPORT
    assert manifest.skills[0].allowed_tools == ("Read", "Search")
    assert manifest.skills[0].resources == (
        "references/guide.md",
        "scripts/never_run.py",
    )
    assert {item.capability for item in manifest.capabilities} == {
        "filesystem.read",
        "process.execute",
        "tool.invoke",
    }
    assert not (source / "executed").exists()


def test_agent_skill_requires_directory_name_match(tmp_path: Path):
    source = make_skill(tmp_path / "wrong-directory", name="right-name")
    with pytest.raises(ValueError, match="must match directory"):
        ExtensionInspector().inspect(source)


def test_zip_skill_and_archive_traversal_protection(tmp_path: Path):
    source = make_skill(tmp_path / "zip-skill", name="zip-skill")
    archive = tmp_path / "skill.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in source.rglob("*"):
            if path.is_file():
                output.write(path, Path("zip-skill") / path.relative_to(source))
    assert ExtensionInspector().inspect(archive).extension_id == "skills/zip-skill"

    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as output:
        output.writestr("../escape.txt", "no")
    with pytest.raises(UnsafeExtensionSource, match="unsafe archive entry"):
        ExtensionInspector().inspect(malicious)
    assert not (tmp_path / "escape.txt").exists()


def test_package_digest_is_deterministic_and_content_sensitive(tmp_path: Path):
    source = make_skill(tmp_path / "digest-skill", name="digest-skill")
    first = package_digest(source)
    assert package_digest(source) == first
    (source / "references" / "guide.md").write_text("changed", encoding="utf-8")
    assert package_digest(source) != first


def test_legacy_plugin_normalizes_permissions_without_authority(tmp_path: Path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "plugin_id": "example.plugin",
                "version": "1.0.0",
                "runtime_compatibility": "0.1",
                "entry_point": "plugin_impl:invoke",
                "capabilities": ["example.echo"],
                "permissions": ["network", "filesystem.read"],
            }
        ),
        encoding="utf-8",
    )
    manifest = ExtensionInspector().inspect(source)
    assert manifest.extension_id == "plugins/example.plugin"
    assert manifest.source_format == "nous-plugin-v0"
    assert {item.capability for item in manifest.capabilities} == {
        "network.connect",
        "filesystem.read",
        "process.execute",
    }
    assert manifest.kernel_projection()["executor"] == "python"
    assert manifest.compatibility_level == CompatibilityLevel.IMPORT


@pytest.mark.parametrize(
    ("body", "source_format"),
    [
        (
            "name: old_pack\nversion: 1.0.0\ndescription: Old\n"
            "capabilities: [document.read]\ndependencies: {base_pack: '>=1'}\n",
            "nous-pack-runtime-v0",
        ),
        (
            "schema_version: 1\nname: kernel-pack\nversion: 1.0.0\n"
            "description: Kernel\nlicense: Apache-2.0\nresources: [docs/a.md]\n",
            "nous-pack-kernel-v1",
        ),
    ],
)
def test_both_historical_pack_shapes_are_normalized(tmp_path: Path, body: str, source_format: str):
    source = tmp_path / source_format
    source.mkdir()
    (source / "pack.yaml").write_text(body, encoding="utf-8")
    manifest = ExtensionInspector().inspect(source)
    assert manifest.source_format == source_format
    assert manifest.kinds == ("pack",)


def test_openapi_imports_tools_and_network_scope(tmp_path: Path):
    source = tmp_path / "openapi.json"
    source.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Pet Service", "version": "1.0.0"},
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {
                    "/pets/{id}": {
                        "get": {
                            "operationId": "getPet",
                            "summary": "Get a pet",
                            "parameters": [
                                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                            ],
                        },
                        "delete": {"operationId": "deletePet"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = ExtensionInspector().inspect(source)
    assert [(tool.name, tool.effect) for tool in manifest.tools] == [
        ("getPet", "read"),
        ("deletePet", "write"),
    ]
    assert manifest.capabilities[0].scope == ("api.example.test",)


def test_mcp_config_import_redacts_inline_secret_values(tmp_path: Path):
    source = tmp_path / ".mcp.json"
    source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": "python",
                        "args": ["server.py"],
                        "env": {"API_TOKEN": "must-not-survive"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = ExtensionInspector().inspect(source)
    serialized = json.dumps(manifest.to_dict())
    assert manifest.extension_id == "mcp/local"
    assert manifest.entry_points[0].configuration["credential_env_refs"] == ["API_TOKEN"]
    assert "must-not-survive" not in serialized
    assert manifest.capabilities[0].capability == "process.execute"


def test_native_manifest_round_trip_and_schema(tmp_path: Path):
    imported = ExtensionInspector().inspect(make_skill(tmp_path / "native-skill", name="native-skill"))
    native = tmp_path / "native"
    native.mkdir()
    (native / "nous.extension.json").write_text(
        json.dumps(imported.to_dict()), encoding="utf-8"
    )
    manifest = ExtensionInspector().inspect(native)
    assert ExtensionManifest.from_dict(manifest.to_dict()).require_valid().extension_id == "skills/native-skill"

    schema_path = Path(__file__).parents[2] / "spec" / "extensions" / "v1" / "nous-extension.schema.json"
    validate(instance=manifest.to_dict(), schema=json.loads(schema_path.read_text(encoding="utf-8")))


def test_registry_is_content_addressed_locked_and_zero_authority(tmp_path: Path):
    source = make_skill(tmp_path / "registry-skill", name="registry-skill")
    registry = ExtensionRegistry(tmp_path / "registry")
    first = registry.install(source)
    second = registry.install(source)
    assert first.provenance and second.provenance
    assert first.provenance.digest == second.provenance.digest
    records = registry.list()
    assert records[0]["authority"] == "none"
    digest = first.provenance.digest.removeprefix("sha256:")
    object_path = registry.objects / digest
    assert (object_path / "package" / "SKILL.md").is_file()
    admission = json.loads(
        (object_path / "kernel-admission-request.json").read_text(encoding="utf-8")
    )
    assert admission["content_digest"] == first.provenance.digest
    metadata = admission["metadata"]
    assert metadata["authority"] == "none"
    assert metadata["supply_chain_verified"] == "true"
    for field in ("normalized_ir_digest", "sbom_digest", "provenance_digest",
                  "signature_digest", "signature_status"):
        assert metadata[field] == records[0][field]
    assert registry.admission_request(first.extension_id) == admission
    assert "skills" not in admission
    assert "instructions" not in json.dumps(admission)
    lock = json.loads(registry.lock_path.read_text(encoding="utf-8"))
    assert lock["extensions"][0]["authority"] == "none"
    assert registry.get("skills/registry-skill") is not None
    assert registry.remove("skills/registry-skill")
    assert registry.get("skills/registry-skill") is None
    assert object_path.is_dir()
