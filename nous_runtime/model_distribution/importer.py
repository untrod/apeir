"""Local model discovery and import-by-reference support."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.model_runtime.errors import ModelResolutionError
from nous_runtime.model_runtime.models import utc_now


_FILE_FORMATS = {
    ".gguf": "gguf",
    ".safetensors": "safetensors",
    ".onnx": "onnx",
}


@dataclass(frozen=True)
class ImportedModel:
    import_id: str
    name: str
    format: str
    source_path: str
    location: str
    referenced: bool
    checksum: str
    size_bytes: int
    imported_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "name": self.name,
            "format": self.format,
            "source_path": self.source_path,
            "location": self.location,
            "referenced": self.referenced,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "imported_at": self.imported_at,
            "metadata": dict(self.metadata),
        }


class LocalModelImporter:
    def inspect(self, source: str | Path) -> dict[str, Any]:
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise ModelResolutionError(
                f"model import source not found: {path}"
            )
        model_format = self._detect_format(path)
        checksum, size_bytes = self._digest(path)
        return {
            "path": str(path),
            "name": path.stem if path.is_file() else path.name,
            "format": model_format,
            "checksum": checksum,
            "size_bytes": size_bytes,
        }

    def import_model(
        self,
        source: str | Path,
        *,
        destination_root: str | Path | None = None,
        reference: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> ImportedModel:
        info = self.inspect(source)
        source_path = Path(info["path"])
        if reference:
            location = source_path
        else:
            if destination_root is None:
                raise ModelResolutionError(
                    "destination_root is required when copying a model"
                )
            root = Path(destination_root).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            location = root / source_path.name
            if location.exists():
                raise ModelResolutionError(
                    f"model import destination already exists: {location}"
                )
            if source_path.is_dir():
                shutil.copytree(source_path, location)
            else:
                shutil.copy2(source_path, location)
        return ImportedModel(
            import_id=f"import_{uuid.uuid4().hex}",
            name=str(info["name"]),
            format=str(info["format"]),
            source_path=str(source_path),
            location=str(location),
            referenced=reference,
            checksum=str(info["checksum"]),
            size_bytes=int(info["size_bytes"]),
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _detect_format(path: Path) -> str:
        if path.is_file():
            model_format = _FILE_FORMATS.get(path.suffix.lower())
            if model_format:
                return model_format
            raise ModelResolutionError(
                f"unsupported model file format: {path.suffix or 'unknown'}"
            )
        names = {item.name.lower() for item in path.iterdir()}
        if "modelfile" in names:
            return "ollama"
        suffixes = {item.suffix.lower() for item in path.rglob("*") if item.is_file()}
        detected = sorted(
            _FILE_FORMATS[suffix]
            for suffix in suffixes
            if suffix in _FILE_FORMATS
        )
        if detected:
            return f"directory:{'+'.join(dict.fromkeys(detected))}"
        raise ModelResolutionError(
            "directory does not contain a supported model format"
        )

    @staticmethod
    def _digest(path: Path) -> tuple[str, int]:
        if path.is_file():
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            return digest.hexdigest(), size
        manifest = []
        total = 0
        for item in sorted(
            (candidate for candidate in path.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.as_posix(),
        ):
            digest = hashlib.sha256()
            size = 0
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            total += size
            manifest.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "sha256": digest.hexdigest(),
                    "size": size,
                }
            )
        payload = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest(), total


__all__ = ["ImportedModel", "LocalModelImporter"]
