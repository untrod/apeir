"""Supply-chain evidence and verification for installed extensions.

The package remains untrusted.  These records prove which bytes were reviewed;
they never grant an extension authority and never contain credential values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml
from cyclonedx.model import HashAlgorithm, HashType, Property, XsUri
from cyclonedx.model.bom import Bom, BomMetaData
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.model.license import LicenseExpression
from cyclonedx.model.service import Service
from cyclonedx.output.json import JsonV1Dot6
from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator

from nous_runtime.extensions.models import ExtensionManifest
from nous_runtime.extensions.sources import package_files


class SignatureStatus(str, Enum):
    UNSIGNED = "Unsigned"
    SIGNED = "Signed"
    VERIFIED = "Verified"
    INVALID = "Invalid"
    UNKNOWN = "Unknown"


class SecretMaterialError(ValueError):
    """Raised when an install source contains a plaintext credential value."""


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|"
    r"refresh[_-]?token|token|secret|password|credential|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|%[A-Za-z_][A-Za-z0-9_]*%|"
    r"\$env:[A-Za-z_][A-Za-z0-9_]*|(?:env|secret|credential)(?:://|:)[A-Za-z0-9_./:-]+)",
    re.IGNORECASE,
)
_HIGH_RISK_TOKEN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16})"
)
_TEXT_CONFIG_SUFFIXES = {".env", ".ini", ".cfg", ".conf", ".toml"}


def assert_package_secret_free(root: Path) -> None:
    """Reject unambiguous plaintext secrets before registry persistence."""

    findings: list[str] = []
    for path in package_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(root).as_posix()
        if "-----BEGIN " in text and "PRIVATE KEY-----" in text:
            findings.append(f"{relative}: private key material")
        if _HIGH_RISK_TOKEN.search(text):
            findings.append(f"{relative}: high-risk token pattern")
        suffix = path.suffix.lower()
        structured: Any = None
        try:
            if suffix == ".json":
                structured = json.loads(text)
            elif suffix in {".yaml", ".yml"}:
                structured = yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError):
            structured = None
        if structured is not None:
            findings.extend(_structured_secret_findings(structured, relative))
        elif suffix in _TEXT_CONFIG_SUFFIXES or path.name.lower() == ".env":
            findings.extend(_assignment_secret_findings(text, relative))
    if findings:
        joined = "; ".join(sorted(set(findings)))
        raise SecretMaterialError(
            "extension package contains plaintext credential material; "
            f"use env/secret references instead ({joined})"
        )


def create_supply_chain_records(
    object_root: Path, manifest: ExtensionManifest
) -> dict[str, str]:
    """Generate standard SBOM, signature state, and provenance evidence."""

    package_root = object_root / "package"
    assert_package_secret_free(package_root)
    normalized_digest = digest_json(manifest.to_dict())
    bom = generate_cyclonedx_bom(manifest, package_root)
    _write_json(object_root / "bom.json", bom)
    sbom_digest = digest_json(bom)
    payload_digest = digest_json(
        signature_payload(manifest, normalized_digest, sbom_digest)
    )
    signature = {
        "schema": "nous.extension-signature/v1",
        "status": SignatureStatus.UNSIGNED.value,
        "algorithm": "none",
        "profile": "detached-blob",
        "provider": "none",
        "payload_digest": payload_digest,
        "public_key": "",
        "signature": "",
    }
    _write_json(object_root / "signature.json", signature)
    signature_digest = digest_json(signature)
    provenance = provenance_record(
        manifest,
        normalized_digest=normalized_digest,
        sbom_digest=sbom_digest,
        signature_status=SignatureStatus.UNSIGNED,
        signature_digest=signature_digest,
    )
    _write_json(object_root / "provenance.json", provenance)
    return {
        "normalized_ir_digest": normalized_digest,
        "sbom_digest": sbom_digest,
        "provenance_digest": digest_json(provenance),
        "signature_status": SignatureStatus.UNSIGNED.value,
        "signature_digest": signature_digest,
    }


def verify_supply_chain_records(
    object_root: Path,
    manifest: ExtensionManifest,
    expected: dict[str, Any],
) -> dict[str, str]:
    """Fail closed if any installed supply-chain record was modified."""

    assert_package_secret_free(object_root / "package")
    normalized_digest = digest_json(manifest.to_dict())
    _expect(expected, "normalized_ir_digest", normalized_digest)

    bom_path = object_root / "bom.json"
    bom_text = bom_path.read_text(encoding="utf-8")
    validation_error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(bom_text)
    if validation_error is not None:
        raise ValueError(f"extension SBOM is invalid: {validation_error}")
    bom = _read_json(bom_path)
    expected_bom = generate_cyclonedx_bom(manifest, object_root / "package")
    if bom != expected_bom:
        raise ValueError("extension SBOM does not match installed content")
    sbom_digest = digest_json(bom)
    _expect(expected, "sbom_digest", sbom_digest)

    signature = _read_json(object_root / "signature.json")
    signature_status = verify_signature_record(
        signature,
        signature_payload(manifest, normalized_digest, sbom_digest),
    )
    signature_digest = digest_json(signature)
    _expect(expected, "signature_digest", signature_digest)
    _expect(expected, "signature_status", signature_status.value)

    provenance = _read_json(object_root / "provenance.json")
    required_provenance = provenance_record(
        manifest,
        normalized_digest=normalized_digest,
        sbom_digest=sbom_digest,
        signature_status=signature_status,
        signature_digest=signature_digest,
    )
    if provenance != required_provenance:
        raise ValueError("extension provenance record was modified")
    provenance_digest = digest_json(provenance)
    _expect(expected, "provenance_digest", provenance_digest)
    return {
        "normalized_ir_digest": normalized_digest,
        "sbom_digest": sbom_digest,
        "provenance_digest": provenance_digest,
        "signature_status": signature_status.value,
        "signature_digest": signature_digest,
    }


def sign_supply_chain_records(
    object_root: Path,
    manifest: ExtensionManifest,
    private_key_pem: bytes,
) -> dict[str, str]:
    """Create and immediately verify a digest-bound Ed25519 signature."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    normalized_digest = digest_json(manifest.to_dict())
    bom = _read_json(object_root / "bom.json")
    sbom_digest = digest_json(bom)
    payload = signature_payload(manifest, normalized_digest, sbom_digest)
    encoded = canonical_json(payload)
    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("extension signing key must be an unencrypted Ed25519 PEM") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("extension signing key must be Ed25519 PEM")
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = {
        "schema": "nous.extension-signature/v1",
        "status": SignatureStatus.SIGNED.value,
        "algorithm": "Ed25519",
        "profile": "detached-blob",
        "provider": "local-ed25519",
        "payload_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "public_key": base64.b64encode(public).decode("ascii"),
        "signature": base64.b64encode(key.sign(encoded)).decode("ascii"),
    }
    if verify_signature_record(signature, payload) is not SignatureStatus.VERIFIED:
        raise ValueError("new extension signature could not be verified")
    signature["status"] = SignatureStatus.VERIFIED.value
    _write_json(object_root / "signature.json", signature)
    signature_digest = digest_json(signature)
    provenance = provenance_record(
        manifest,
        normalized_digest=normalized_digest,
        sbom_digest=sbom_digest,
        signature_status=SignatureStatus.VERIFIED,
        signature_digest=signature_digest,
    )
    _write_json(object_root / "provenance.json", provenance)
    return {
        "normalized_ir_digest": normalized_digest,
        "sbom_digest": sbom_digest,
        "provenance_digest": digest_json(provenance),
        "signature_status": SignatureStatus.VERIFIED.value,
        "signature_digest": signature_digest,
    }


def generate_cyclonedx_bom(
    manifest: ExtensionManifest, package_root: Path
) -> dict[str, Any]:
    """Build a deterministic CycloneDX 1.6 SBOM with the official library."""

    assert manifest.provenance is not None
    root_hash = manifest.provenance.digest.removeprefix("sha256:")
    root_properties = [
        Property(name="nous:source-format", value=manifest.source_format),
        Property(name="nous:adapter", value=manifest.provenance.adapter),
    ]
    licenses = None
    if manifest.license:
        try:
            licenses = [LicenseExpression(manifest.license)]
        except ValueError:
            root_properties.append(Property(name="nous:declared-license", value=manifest.license))
    root_component = Component(
        type=ComponentType.APPLICATION,
        name=manifest.extension_id,
        version=manifest.version,
        description=manifest.description or None,
        bom_ref=f"nous-extension:{manifest.extension_id}@{manifest.version}",
        hashes=[HashType(alg=HashAlgorithm.SHA_256, content=root_hash)],
        licenses=licenses,
        properties=root_properties,
    )
    components: list[Component] = []
    for path in package_files(package_root):
        relative = path.relative_to(package_root).as_posix()
        components.append(
            Component(
                type=ComponentType.FILE,
                name=relative,
                bom_ref=f"file:{relative}",
                hashes=[
                    HashType(
                        alg=HashAlgorithm.SHA_256,
                        content=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                ],
            )
        )
    for name, constraint in sorted(manifest.dependencies.items()):
        components.append(
            Component(
                type=ComponentType.LIBRARY,
                name=name,
                version=constraint,
                bom_ref=f"dependency:{name}@{constraint}",
            )
        )
    services: list[Service] = []
    for index, entry in enumerate(manifest.entry_points):
        if entry.target.lower().startswith("https://"):
            services.append(
                Service(
                    name=f"{manifest.extension_id}:{index}",
                    bom_ref=f"service:{manifest.extension_id}:{index}",
                    endpoints=[XsUri(entry.target)],
                    authenticated=bool(entry.configuration.get("credential_env_refs")),
                    x_trust_boundary=True,
                )
            )
    timestamp = datetime.fromisoformat(manifest.provenance.imported_at.replace("Z", "+00:00"))
    bom = Bom(
        components=components,
        services=services,
        serial_number=uuid.uuid5(uuid.NAMESPACE_URL, f"nous:{manifest.provenance.digest}"),
        metadata=BomMetaData(timestamp=timestamp, component=root_component),
    )
    bom.register_dependency(root_component, components)
    output = JsonV1Dot6(bom).output_as_string(indent=2)
    error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(output)
    if error is not None:
        raise ValueError(f"generated CycloneDX SBOM is invalid: {error}")
    value = json.loads(output)
    if not isinstance(value, dict):
        raise ValueError("generated CycloneDX SBOM must be an object")
    return value


def signature_payload(
    manifest: ExtensionManifest, normalized_digest: str, sbom_digest: str
) -> dict[str, str]:
    assert manifest.provenance is not None
    return {
        "schema": "nous.extension-signing-payload/v1",
        "extension_id": manifest.extension_id,
        "content_digest": manifest.provenance.digest,
        "normalized_ir_digest": normalized_digest,
        "sbom_digest": sbom_digest,
    }


def verify_signature_record(
    record: dict[str, Any], payload: dict[str, str]
) -> SignatureStatus:
    status_text = str(record.get("status") or SignatureStatus.UNKNOWN.value)
    try:
        declared = SignatureStatus(status_text)
    except ValueError as exc:
        raise ValueError("extension signature status is Unknown") from exc
    payload_digest = "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()
    if record.get("payload_digest") != payload_digest:
        raise ValueError("extension signature payload binding is Invalid")
    if declared is SignatureStatus.UNSIGNED:
        if record.get("algorithm") != "none" or record.get("signature") or record.get("public_key"):
            raise ValueError("unsigned extension signature record is Invalid")
        return SignatureStatus.UNSIGNED
    if record.get("algorithm") != "Ed25519":
        raise ValueError("extension signature algorithm is Unknown")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public = base64.b64decode(str(record.get("public_key") or ""), validate=True)
        signature = base64.b64decode(str(record.get("signature") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_json(payload))
    except Exception as exc:
        raise ValueError("extension signature is Invalid") from exc
    return SignatureStatus.VERIFIED


def provenance_record(
    manifest: ExtensionManifest,
    *,
    normalized_digest: str,
    sbom_digest: str,
    signature_status: SignatureStatus,
    signature_digest: str,
) -> dict[str, Any]:
    assert manifest.provenance is not None
    try:
        runtime_version = version("nous-runtime")
    except PackageNotFoundError:
        runtime_version = "unknown"
    record: dict[str, Any] = {
        "schema": "nous.extension-provenance/v1",
        "extension_id": manifest.extension_id,
        "source_type": manifest.provenance.source_type,
        "source": _redact_source(manifest.provenance.source),
        "imported_at": manifest.provenance.imported_at,
        "original_digest": manifest.provenance.digest,
        "normalized_ir_digest": normalized_digest,
        "installer": {"name": "nous-runtime", "version": runtime_version},
        "adapter": {"name": manifest.provenance.adapter, "version": "extension-ir/v1"},
        "sbom": {
            "format": "CycloneDX",
            "spec_version": "1.6",
            "path": "bom.json",
            "digest": sbom_digest,
        },
        "signature_status": signature_status.value,
        "signature_digest": signature_digest,
    }
    build = manifest.metadata.get("build_provenance")
    if isinstance(build, dict):
        record["build_provenance"] = build
    return record


def canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_json(data: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(data)).hexdigest()


def _structured_secret_findings(value: Any, source: str) -> list[str]:
    findings: list[str] = []

    def walk(item: Any, path: str, parent_key: str = "") -> None:
        if isinstance(item, dict):
            for raw_key, child in item.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                sensitive = bool(_SENSITIVE_KEY.search(key))
                if sensitive and isinstance(child, (str, int, float)) and not _is_reference(child):
                    findings.append(f"{child_path}: plaintext credential value")
                walk(child, child_path, key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]", parent_key)

    walk(value, source)
    return findings


def _assignment_secret_findings(text: str, source: str) -> list[str]:
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*['\"]?([^'\"#]+)", line)
        if match and _SENSITIVE_KEY.search(match.group(1)) and not _is_reference(match.group(2)):
            findings.append(f"{source}:{number}: plaintext credential value")
    return findings


def _is_reference(value: Any) -> bool:
    text = str(value).strip()
    return not text or text == "<REDACTED>" or _REFERENCE.fullmatch(text) is not None


def _redact_source(source: str) -> str:
    parsed = urlsplit(source)
    if parsed.scheme not in {"http", "https"}:
        return source
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _expect(expected: dict[str, Any], field: str, actual: str) -> None:
    if str(expected.get(field) or "") != actual:
        raise ValueError(f"extension {field} integrity check failed")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid extension evidence file: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
