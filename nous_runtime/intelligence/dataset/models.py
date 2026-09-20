# -*- coding: utf-8 -*-
"""Dataset record models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DatasetType(str, Enum):
    PRODUCTION = "production"
    SANITIZED = "sanitized"
    BENCHMARK = "benchmark"
    REPLAY = "replay"
    SHADOW = "shadow"
    EXPERIMENTAL = "experimental"
    FAILED = "failed"
    COUNTERFACTUAL = "counterfactual"


@dataclass
class DatasetRecord:
    """Versioned dataset metadata record."""

    dataset_id: str = ""
    version: str = "1.0.0"
    dataset_type: DatasetType = DatasetType.EXPERIMENTAL
    source: str = ""              # "trace_store", "benchmark", "manual", etc.
    time_range: tuple[str, str] = ("", "")  # (start, end) ISO 8601
    schema_version: str = "1.0.0"
    task_count: int = 0
    privacy_level: str = ""       # public, internal, confidential, restricted
    license: str = ""             # SPDX identifier
    filtering_rules: dict = field(default_factory=dict)
    data_hash: str = ""           # SHA-256 of canonical representation
    creation_method: str = ""     # "trace_query", "benchmark_export", "manual", etc.
    known_biases: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    description: str = ""
    created_at: str = ""
    storage_path: str = ""        # absolute path to dataset files
    storage_format: str = ""      # "jsonl", "sqlite", "parquet", etc.
    trace_ids: list[str] = field(default_factory=list)  # source trace IDs
    metadata: dict = field(default_factory=dict)

    def seal(self) -> None:
        self.created_at = self.created_at or _utc_now()
        self.data_hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "dataset_type": self.dataset_type.value,
            "source": self.source,
            "time_range": list(self.time_range),
            "schema_version": self.schema_version,
            "task_count": self.task_count,
            "privacy_level": self.privacy_level,
            "license": self.license,
            "filtering_rules": self.filtering_rules,
            "data_hash": self.data_hash,
            "creation_method": self.creation_method,
            "known_biases": self.known_biases,
            "limitations": self.limitations,
            "description": self.description,
            "created_at": self.created_at,
            "storage_path": self.storage_path,
            "storage_format": self.storage_format,
            "trace_ids": self.trace_ids,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DatasetRecord":
        tr = data.get("time_range", ["", ""])
        return cls(
            dataset_id=str(data.get("dataset_id", "")),
            version=str(data.get("version", "1.0.0")),
            dataset_type=DatasetType(str(data.get("dataset_type", "experimental"))),
            source=str(data.get("source", "")),
            time_range=(
                str(tr[0]) if isinstance(tr, list) and len(tr) > 0 else "",
                str(tr[1]) if isinstance(tr, list) and len(tr) > 1 else "",
            ),
            schema_version=str(data.get("schema_version", "1.0.0")),
            task_count=int(data.get("task_count", 0)),
            privacy_level=str(data.get("privacy_level", "")),
            license=str(data.get("license", "")),
            filtering_rules=dict(data.get("filtering_rules", {})),
            data_hash=str(data.get("data_hash", "")),
            creation_method=str(data.get("creation_method", "")),
            known_biases=list(data.get("known_biases", [])),
            limitations=list(data.get("limitations", [])),
            description=str(data.get("description", "")),
            created_at=str(data.get("created_at", "")),
            storage_path=str(data.get("storage_path", "")),
            storage_format=str(data.get("storage_format", "")),
            trace_ids=list(data.get("trace_ids", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def _compute_hash(self) -> str:
        d = self.to_dict()
        d.pop("data_hash", None)
        d.pop("created_at", None)
        canonical = json.dumps(d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
