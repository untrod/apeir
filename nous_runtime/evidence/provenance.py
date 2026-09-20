# -*- coding: utf-8 -*-
"""Provenance Tracking — records the full chain of data transformations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ProvenanceRecord:
    """A single step in a data provenance chain."""
    record_id: str = ""
    artifact_id: str = ""
    operation: str = ""            # created, transformed, merged, derived, copied
    inputs: list[str] = field(default_factory=list)    # upstream artifact IDs
    outputs: list[str] = field(default_factory=list)   # downstream artifact IDs
    agent_id: str = ""             # who performed the operation
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ProvenanceTracker:
    """Tracks the full provenance chain of all artifacts."""

    def __init__(self) -> None:
        self._records: dict[str, ProvenanceRecord] = {}
        self._lineage: dict[str, list[str]] = {}  # artifact_id → ancestor chain

    def record(self, operation: str, inputs: list[str], outputs: list[str], agent_id: str = "") -> list[str]:
        """Record a provenance event. Returns record IDs."""
        record_ids = []
        ts = _utc_now()
        for output_id in outputs:
            rec = ProvenanceRecord(
                record_id=f"prov_{uuid.uuid4().hex[:12]}",
                artifact_id=output_id,
                operation=operation,
                inputs=list(inputs),
                outputs=[output_id],
                agent_id=agent_id,
                timestamp=ts,
            )
            self._records[rec.record_id] = rec
            record_ids.append(rec.record_id)

            # Build lineage
            ancestors = []
            for inp in inputs:
                ancestors.extend(self._lineage.get(inp, [inp]))
            self._lineage[output_id] = list(set(ancestors))

        return record_ids

    def get_ancestors(self, artifact_id: str) -> list[str]:
        """Get all ancestors of an artifact."""
        return self._lineage.get(artifact_id, [])

    def get_record(self, record_id: str) -> ProvenanceRecord | None:
        return self._records.get(record_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
