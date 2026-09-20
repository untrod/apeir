"""Plugin package integrity and optional signature boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from nous_runtime.plugins.models import PluginManifest

_TEXT_SUFFIXES = frozenset({".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"})


class SignatureVerifier(Protocol):
    def verify(self, payload_digest: str, signature: str) -> bool: ...


def package_checksum(root: str | Path, manifest: PluginManifest) -> str:
    package = Path(root).resolve()
    digest = hashlib.sha256()
    public_manifest = manifest.to_dict()
    public_manifest["package_checksum"] = ""
    public_manifest["signature"] = ""
    digest.update(json.dumps(public_manifest, sort_keys=True, separators=(",", ":")).encode())
    files = (item for item in package.rglob("*") if item.is_file() and item.name != "plugin.json")
    for path in sorted(files, key=lambda item: item.relative_to(package).as_posix()):
        relative = path.relative_to(package).as_posix()
        if relative.startswith(".nous/") or "__pycache__" in path.parts:
            continue
        digest.update(relative.encode())
        digest.update(b"\0")
        payload = path.read_bytes()
        if path.suffix.lower() in _TEXT_SUFFIXES:
            payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(payload)
    return digest.hexdigest()


def validate_package(root: str | Path, manifest: PluginManifest, *, verifier: SignatureVerifier | None = None) -> list[str]:
    errors = manifest.validate()
    calculated = package_checksum(root, manifest)
    if not manifest.package_checksum:
        errors.append("package_checksum is required")
    elif manifest.package_checksum != calculated:
        errors.append("package checksum mismatch")
    if manifest.signature:
        if verifier is None:
            errors.append("signature is present but no verifier is configured")
        elif not verifier.verify(calculated, manifest.signature):
            errors.append("plugin signature verification failed")
    return errors