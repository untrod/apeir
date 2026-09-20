"""Signed model catalog contracts and verification."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.model_runtime.errors import ModelResolutionError
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelModality,
    ModelPackage,
)


SignatureVerifier = Callable[[bytes, str], bool]


@dataclass(frozen=True)
class DownloadArtifact:
    artifact_id: str
    urls: tuple[str, ...]
    sha256: str
    size_bytes: int
    filename: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.urls or not self.filename:
            raise ModelResolutionError(
                "download artifact id, urls and filename are required"
            )
        filename = Path(self.filename)
        if filename.is_absolute() or filename.name != self.filename:
            raise ModelResolutionError(
                "download artifact filename must be a plain file name"
            )
        checksum = self.sha256.lower().strip()
        if len(checksum) != 64 or any(
            character not in "0123456789abcdef"
            for character in checksum
        ):
            raise ModelResolutionError(
                "download artifact requires a valid SHA256 checksum"
            )
        if self.size_bytes < 0:
            raise ModelResolutionError(
                "download artifact size must be non-negative"
            )
        object.__setattr__(self, "sha256", checksum)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "urls": list(self.urls),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "filename": self.filename,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DownloadArtifact":
        return cls(
            artifact_id=str(data.get("artifact_id") or ""),
            urls=tuple(str(item) for item in data.get("urls") or ()),
            sha256=str(data.get("sha256") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
            filename=str(data.get("filename") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class CatalogModel:
    descriptor: ModelDescriptor
    packages: tuple[ModelPackage, ...]
    artifacts: tuple[DownloadArtifact, ...] = ()
    channel: str = "stable"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "packages": [
                {
                    "package_id": item.package_id,
                    "model_id": item.model_id,
                    "capabilities": sorted(item.capabilities),
                    "modalities": sorted(
                        modality.value for modality in item.modalities
                    ),
                    "disk_mb": item.disk_mb,
                    "vram_mb": item.vram_mb,
                    "license_approved": item.license_approved,
                    "source": item.source,
                    "metadata": dict(item.metadata),
                }
                for item in self.packages
            ],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "channel": self.channel,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CatalogModel":
        return cls(
            descriptor=ModelDescriptor.from_dict(
                data.get("descriptor") or {}
            ),
            packages=tuple(
                ModelPackage(
                    package_id=str(item.get("package_id") or ""),
                    model_id=str(item.get("model_id") or ""),
                    capabilities=frozenset(
                        item.get("capabilities") or ()
                    ),
                    modalities=frozenset(
                        ModelModality(str(value))
                        for value in item.get("modalities") or ("text",)
                    ),
                    disk_mb=int(item.get("disk_mb") or 0),
                    vram_mb=int(item.get("vram_mb") or 0),
                    license_approved=bool(
                        item.get("license_approved", True)
                    ),
                    source=str(item.get("source") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in data.get("packages") or ()
            ),
            artifacts=tuple(
                DownloadArtifact.from_dict(item)
                for item in data.get("artifacts") or ()
            ),
            channel=str(data.get("channel") or "stable"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[CatalogModel, ...]
    catalog_version: str
    generated_at: str
    signature: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def model(self, model_id: str) -> CatalogModel | None:
        return next(
            (
                item
                for item in self.models
                if item.descriptor.model_id == str(model_id)
            ),
            None,
        )

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "generated_at": self.generated_at,
            "models": [item.to_dict() for item in self.models],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        verifier: SignatureVerifier | None,
        require_signature: bool = True,
    ) -> "ModelCatalog":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            catalog = cls(
                models=tuple(
                    CatalogModel.from_dict(item)
                    for item in data.get("models") or ()
                ),
                catalog_version=str(
                    data.get("catalog_version") or ""
                ),
                generated_at=str(data.get("generated_at") or ""),
                signature=str(data.get("signature") or ""),
                metadata=dict(data.get("metadata") or {}),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelResolutionError(
                f"failed to load model catalog: {exc}"
            ) from exc
        if not catalog.catalog_version or not catalog.generated_at:
            raise ModelResolutionError(
                "catalog version and generated_at are required"
            )
        model_ids = [item.descriptor.model_id for item in catalog.models]
        if len(model_ids) != len(set(model_ids)):
            raise ModelResolutionError(
                "model catalog contains duplicate model IDs"
            )
        if require_signature and not catalog.signature:
            raise ModelResolutionError("model catalog is unsigned")
        if catalog.signature:
            if verifier is None:
                raise ModelResolutionError(
                    "catalog signature verifier is required"
                )
            canonical = json.dumps(
                catalog.unsigned_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if not verifier(canonical, catalog.signature):
                raise ModelResolutionError(
                    "model catalog signature is invalid"
                )
        return catalog


class Ed25519CatalogVerifier:
    """Verify catalog signatures with a distributor public key."""

    def __init__(self, public_key_base64: str) -> None:
        try:
            self.public_key = base64.b64decode(
                public_key_base64,
                validate=True,
            )
        except (ValueError, TypeError) as exc:
            raise ModelResolutionError(
                "invalid catalog public key encoding"
            ) from exc
        if len(self.public_key) != 32:
            raise ModelResolutionError(
                "Ed25519 public key must be 32 bytes"
            )

    def __call__(self, payload: bytes, signature: str) -> bool:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
        except ImportError as exc:
            raise ModelResolutionError(
                "cryptography is required for signed catalog verification"
            ) from exc
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
            key = Ed25519PublicKey.from_public_bytes(self.public_key)
            key.verify(signature_bytes, payload)
        except Exception:
            return False
        return True


__all__ = [
    "CatalogModel",
    "DownloadArtifact",
    "Ed25519CatalogVerifier",
    "ModelCatalog",
    "SignatureVerifier",
]
