from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator
from jsonschema import validate
from typer.testing import CliRunner

from nous_runtime.extensions.cli import extension_app
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.extensions.supply_chain import SecretMaterialError


def _skill(root: Path) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {root.name}\ndescription: C5 evidence fixture\n"
        "license: Apache-2.0\nallowed-tools: []\n---\n\nUse the governed tool.\n",
        encoding="utf-8",
    )
    (root / "reference.txt").write_text("public reference\n", encoding="utf-8")
    return root


def _object_root(registry: ExtensionRegistry, extension_id: str) -> Path:
    manifest = registry.get(extension_id)
    assert manifest is not None and manifest.provenance is not None
    return registry.objects / manifest.provenance.digest.removeprefix("sha256:")


def test_install_generates_standard_sbom_provenance_and_lock_bindings(tmp_path: Path):
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(_skill(tmp_path / "skill"))
    root = _object_root(registry, manifest.extension_id)

    bom_text = (root / "bom.json").read_text(encoding="utf-8")
    assert JsonStrictValidator(SchemaVersion.V1_6).validate_str(bom_text) is None
    bom = json.loads(bom_text)
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert {item["name"] for item in bom["components"]} >= {
        "SKILL.md",
        "reference.txt",
    }

    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["original_digest"] == manifest.provenance.digest
    assert provenance["normalized_ir_digest"].startswith("sha256:")
    assert provenance["sbom"]["digest"].startswith("sha256:")
    assert provenance["signature_status"] == "Unsigned"
    assert "credential" not in json.dumps(provenance).lower()
    schema_root = Path(__file__).parents[2] / "spec" / "extensions" / "v1"
    validate(
        provenance,
        json.loads(
            (schema_root / "extension-provenance.schema.json").read_text(encoding="utf-8")
        ),
    )
    validate(
        json.loads((root / "signature.json").read_text(encoding="utf-8")),
        json.loads(
            (schema_root / "extension-signature.schema.json").read_text(encoding="utf-8")
        ),
    )

    record = registry.get_record(manifest.extension_id)
    assert record is not None
    lock = json.loads(registry.lock_path.read_text(encoding="utf-8"))["extensions"][0]
    for field in (
        "normalized_ir_digest",
        "sbom_digest",
        "provenance_digest",
        "signature_status",
        "signature_digest",
    ):
        assert lock[field] == record[field]
    registry.verify(manifest.extension_id)


def test_ed25519_signature_is_digest_bound_and_private_key_is_not_persisted(
    tmp_path: Path,
):
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(_skill(tmp_path / "skill"))
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "operator-signing-key.pem"
    key_path.write_bytes(pem)

    result = registry.sign(manifest.extension_id, key_path)

    assert result["signature_status"] == "Verified"
    assert registry.get_record(manifest.extension_id)["signature_status"] == "Verified"
    registry.verify(manifest.extension_id)
    registry_bytes = b"".join(
        path.read_bytes() for path in registry.root.rglob("*") if path.is_file()
    )
    assert pem not in registry_bytes

    signature_path = _object_root(registry, manifest.extension_id) / "signature.json"
    signature = json.loads(signature_path.read_text(encoding="utf-8"))
    signature["signature"] = "AAAA"
    signature_path.write_text(json.dumps(signature), encoding="utf-8")
    with pytest.raises(ValueError, match="signature is Invalid"):
        registry.verify(manifest.extension_id)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("bom.json", "SBOM"),
        ("provenance.json", "provenance"),
        ("signature.json", "signature"),
    ],
)
def test_evidence_tamper_fails_closed(tmp_path: Path, target: str, message: str):
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(_skill(tmp_path / "skill"))
    path = _object_root(registry, manifest.extension_id) / target
    data = json.loads(path.read_text(encoding="utf-8"))
    if target == "bom.json":
        data["metadata"]["component"]["name"] = "tampered"
    elif target == "provenance.json":
        data["source"] = "tampered"
    else:
        data["public_key"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        registry.verify(manifest.extension_id)


def test_registry_critical_field_tamper_is_caught_by_lock(tmp_path: Path):
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(_skill(tmp_path / "skill"))
    index = json.loads(registry.index_path.read_text(encoding="utf-8"))
    index["extensions"][manifest.extension_id]["sbom_digest"] = "sha256:" + "0" * 64
    registry.index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(ValueError, match="lock sbom_digest"):
        registry.verify(manifest.extension_id)


def test_plaintext_mcp_credential_is_rejected_before_registry_persistence(
    tmp_path: Path,
):
    source = tmp_path / ".mcp.json"
    source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "unsafe": {
                        "command": "python",
                        "args": ["server.py"],
                        "env": {"API_TOKEN": "must-not-survive"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")

    with pytest.raises(SecretMaterialError, match="plaintext credential"):
        registry.install(source)
    assert not registry.index_path.exists()
    assert not registry.objects.exists() or not any(registry.objects.iterdir())


def test_mcp_credential_reference_is_safe_to_install(tmp_path: Path):
    source = tmp_path / ".mcp.json"
    source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "safe": {
                        "command": "python",
                        "args": ["server.py"],
                        "env": {"API_TOKEN": "env:API_TOKEN"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(source)

    assert registry.verify(manifest.extension_id).extension_id == manifest.extension_id


def test_cli_exposes_supply_chain_verify_and_sign(tmp_path: Path):
    registry_path = tmp_path / "registry"
    manifest = ExtensionRegistry(registry_path).install(_skill(tmp_path / "skill"))
    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    runner = CliRunner()

    signed = runner.invoke(
        extension_app,
        [
            "sign",
            manifest.extension_id,
            "--key",
            str(key_path),
            "--registry",
            str(registry_path),
            "--json",
        ],
    )
    assert signed.exit_code == 0, signed.output
    assert json.loads(signed.output)["signature_status"] == "Verified"

    verified = runner.invoke(
        extension_app,
        ["verify", manifest.extension_id, "--registry", str(registry_path), "--json"],
    )
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["verified"] is True


def test_signing_invalidates_prior_kernel_authority(tmp_path: Path):
    registry = ExtensionRegistry(tmp_path / "registry")
    manifest = registry.install(_skill(tmp_path / "skill"))
    assert manifest.provenance is not None
    registry.record_admission(
        manifest.extension_id,
        {
            "normalized_digest": manifest.provenance.digest,
            "approval_required": False,
            "receipt_id": "old-kernel-receipt",
            "policy_version": "old-policy",
            "granted_capabilities": ["filesystem.read"],
        },
    )
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    registry.sign(manifest.extension_id, key_path)

    record = registry.get_record(manifest.extension_id)
    assert record is not None
    assert record["state"] == "installed"
    assert record["authority"] == "none"
    assert record["granted_capabilities"] == []
    assert record["previous_granted_capabilities"] == ["filesystem.read"]
    assert registry.read_admission(manifest.extension_id) is None
    request = registry.admission_request(manifest.extension_id)
    assert request["metadata"]["signature_status"] == "Verified"
