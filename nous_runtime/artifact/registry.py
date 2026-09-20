"""Thread-safe artifact registry with optional append-only persistence."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from nous_runtime.artifact.models import Artifact, ArtifactType
from nous_runtime.core.errors import ArtifactError
from nous_runtime.locking import file_lock


class ArtifactRegistry:
    """Register and query artifacts through one canonical contract.

    The default remains in-memory for backward compatibility. Runtime services
    that need durable artifacts pass a workspace-scoped JSONL path.
    """

    def __init__(self, storage_path: str | Path = "") -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._lock = threading.RLock()
        self._path = Path(storage_path).expanduser().resolve() if storage_path else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def register(self, artifact: Artifact) -> Artifact:
        if not isinstance(artifact, Artifact):
            raise ArtifactError("artifact must be an Artifact instance")
        with self._lock:
            if artifact.id in self._artifacts:
                raise ArtifactError(f"artifact already registered: {artifact.id}")
            if self._path is not None:
                encoded = json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True)
                with file_lock(str(self._path) + ".lock"):
                    with self._path.open("a", encoding="utf-8", newline="\n") as stream:
                        stream.write(encoded + "\n")
                        stream.flush()
            self._artifacts[artifact.id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        with self._lock:
            return self._artifacts.get(str(artifact_id))

    def list(self, artifact_type: str | ArtifactType | None = None) -> list[Artifact]:
        normalized = (
            artifact_type.value
            if isinstance(artifact_type, ArtifactType)
            else str(artifact_type or "")
        )
        with self._lock:
            artifacts = list(self._artifacts.values())
        if normalized:
            artifacts = [artifact for artifact in artifacts if artifact.type == normalized]
        # Registration/file order is the stable public contract. Timestamp sorting
        # made ordering depend on whether adjacent artifacts crossed a millisecond.
        return artifacts

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            with file_lock(str(self._path) + ".lock"):
                lines = self._path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if not line.strip():
                    continue
                artifact = Artifact.from_dict(json.loads(line))
                self._artifacts[artifact.id] = artifact
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"artifact registry could not be loaded: {exc}") from exc


registry = ArtifactRegistry()

__all__ = ["ArtifactRegistry", "registry"]
