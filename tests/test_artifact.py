"""Artifact foundation model, registry, and manager tests."""

import pytest

from nous_runtime.artifact import (
    Artifact,
    ArtifactManager,
    ArtifactRegistry,
    ArtifactType,
)
from nous_runtime.core.errors import ArtifactError


def test_artifact_model_round_trip():
    artifact = Artifact(
        id="artifact-report",
        type=ArtifactType.REPORT,
        name="Batch report",
        location="docs/report.md",
        creator="agent",
        created_at="2026-07-21T00:00:00.000Z",
        metadata={"checksum": "abc"},
    )

    restored = Artifact.from_dict(artifact.to_dict())

    assert restored == artifact
    assert restored.type == "report"
    assert restored.metadata == {"checksum": "abc"}


def test_artifact_registry_registers_gets_and_lists_by_type():
    registry = ArtifactRegistry()
    code = registry.register(Artifact(type="code", name="main.py"))
    report = registry.register(Artifact(type="report", name="review.md"))

    assert registry.get(code.id) is code
    assert registry.get("missing") is None
    assert registry.list() == [code, report]
    assert registry.list(ArtifactType.REPORT) == [report]


def test_artifact_registry_rejects_duplicates_and_invalid_types():
    registry = ArtifactRegistry()
    artifact = registry.register(Artifact(id="fixed", type="file", name="file.txt"))

    with pytest.raises(ArtifactError, match="already registered"):
        registry.register(artifact)
    with pytest.raises(ArtifactError, match="unsupported artifact type"):
        Artifact(type="unknown", name="bad")


def test_artifact_manager_creates_registered_artifacts():
    manager = ArtifactManager()

    artifact = manager.create(
        "dataset",
        "training-data",
        location="data/train.jsonl",
        creator="agent",
        metadata={"rows": 12},
    )

    assert manager.get(artifact.id) is artifact
    assert manager.list("dataset") == [artifact]
    assert artifact.metadata["rows"] == 12
