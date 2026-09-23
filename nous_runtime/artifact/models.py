"""Canonical artifact contracts for Runtime-produced outputs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from nous_runtime.core.errors import ArtifactError


class ArtifactType(str, Enum):
    """Foundation artifact categories."""

    CODE = "code"
    FILE = "file"
    MODEL = "model"
    DATASET = "dataset"
    REPORT = "report"
    DOCUMENT = "document"
    BINARY = "binary"
    SOURCE_BUNDLE = "source_bundle"
    CONTAINER = "container"
    FIRMWARE = "firmware"
    CONFIGURATION = "configuration"
    CALIBRATION = "calibration"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    ROUTE_DECISION = "route_decision"
    MODEL_METRICS = "model_metrics"
    VERIFICATION_RESULT = "verification_result"
    EVIDENCE = "evidence"


def _artifact_id() -> str:
    return f"artifact_{uuid.uuid4().hex}"


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class Artifact:
    """A code, file, model, dataset, or report produced by the Runtime."""

    id: str = field(default_factory=_artifact_id)
    type: str = ArtifactType.FILE.value
    name: str = ""
    location: str = ""
    creator: str = "runtime"
    created_at: str = field(default_factory=_timestamp)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        artifact_id = str(self.id or "").strip()
        artifact_type = str(
            self.type.value if isinstance(self.type, ArtifactType) else self.type
        )
        artifact_name = str(self.name or "").strip()
        if not artifact_id:
            raise ArtifactError("artifact id is required")
        if artifact_type not in {item.value for item in ArtifactType}:
            raise ArtifactError(f"unsupported artifact type: {artifact_type}")
        if not artifact_name:
            raise ArtifactError("artifact name is required")
        object.__setattr__(self, "id", artifact_id)
        object.__setattr__(self, "type", artifact_type)
        object.__setattr__(self, "name", artifact_name)
        object.__setattr__(self, "location", str(self.location or ""))
        object.__setattr__(self, "creator", str(self.creator or "runtime"))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "location": self.location,
            "creator": self.creator,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Artifact":
        return cls(
            id=str(data.get("id") or _artifact_id()),
            type=str(data.get("type") or ArtifactType.FILE.value),
            name=str(data.get("name") or ""),
            location=str(data.get("location") or ""),
            creator=str(data.get("creator") or "runtime"),
            created_at=str(data.get("created_at") or _timestamp()),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["Artifact", "ArtifactType"]
