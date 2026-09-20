"""Durable experiment specifications and lifecycle state."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ExperimentState(str, Enum):
    PROPOSED = "proposed"
    SANDBOX = "sandbox"
    BENCHMARKED = "benchmarked"
    ABLATED = "ablated"
    REPLICATED = "replicated"
    SHADOW = "shadow"
    CANARY = "canary"
    APPROVED = "approved"
    PRODUCTION = "production"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExperimentSpec:
    """Versioned experiment specification persisted without secret material."""

    experiment_id: str = ""
    hypothesis: str = ""
    baseline_name: str = ""
    candidate_name: str = ""
    dataset_id: str = ""
    task_set: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    seeds: list[int] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    model_versions: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    sample_size: int = 100
    statistical_test: str = "bootstrap"
    acceptance_threshold: float = 0.05
    rollback_condition: str = ""
    owner: str = ""
    state: ExperimentState = ExperimentState.PROPOSED
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentSpec":
        fields = {
            name: value
            for name, value in data.items()
            if name in cls.__dataclass_fields__ and name != "state"
        }
        fields["state"] = ExperimentState(str(data.get("state") or "proposed"))
        return cls(**fields)


class ExperimentRegistry:
    """Filesystem-backed experiment registry with atomic updates."""

    def __init__(self, storage_dir: str | os.PathLike[str] = "") -> None:
        if storage_dir:
            root = Path(storage_dir)
        else:
            workspace = os.environ.get("NOUS_WORKSPACE_ROOT")
            root = (
                Path(workspace) / ".nous" / "experiments"
                if workspace
                else Path.home() / ".nous" / "experiments"
            )
        self._dir = root.expanduser().resolve()
        self._spec_dir = self._dir / "specs"
        self._spec_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def register(self, spec: ExperimentSpec) -> str:
        if not spec.experiment_id:
            spec.experiment_id = f"exp_{uuid.uuid4().hex[:12]}"
        self._validate_id(spec.experiment_id)
        now = _utc_now()
        if not spec.created_at:
            spec.created_at = now
        spec.updated_at = now
        self.save(spec)
        return spec.experiment_id

    def save(self, spec: ExperimentSpec) -> None:
        self._validate_id(spec.experiment_id)
        spec.updated_at = _utc_now()
        path = self._path(spec.experiment_id)
        temporary = path.with_suffix(".tmp")
        payload = json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            temporary.write_text(payload + "\n", encoding="utf-8")
            os.replace(temporary, path)

    def get(self, experiment_id: str) -> ExperimentSpec | None:
        self._validate_id(experiment_id)
        path = self._path(experiment_id)
        if not path.is_file():
            return None
        with self._lock:
            return ExperimentSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[ExperimentSpec]:
        records: list[ExperimentSpec] = []
        with self._lock:
            paths = tuple(self._spec_dir.glob("*.json"))
        for path in paths:
            try:
                records.append(
                    ExperimentSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: item.updated_at or item.created_at, reverse=True)

    def list_by_state(self, state: ExperimentState) -> list[ExperimentSpec]:
        return [item for item in self.list() if item.state is state]

    def count(self) -> int:
        return len(self.list())

    def _path(self, experiment_id: str) -> Path:
        return self._spec_dir / f"{experiment_id}.json"

    @staticmethod
    def _validate_id(experiment_id: str) -> None:
        if not _EXPERIMENT_ID.fullmatch(experiment_id):
            raise ValueError("invalid experiment id")
