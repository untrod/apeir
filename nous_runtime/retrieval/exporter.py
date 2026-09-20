"""Canonical RetrievalRecord exporters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from nous_runtime.project.memory import read_all
from nous_runtime.retrieval.indexing import ExportBatch, ExportCursor
from nous_runtime.retrieval.models import RetrievalRecord
from nous_runtime.retrieval.records.mapper import memory_record_to_retrieval

MEMORY_STREAMS = ("events", "facts", "decisions", "summaries", "experiences", "artifacts")


class RetrievalRecordExporter:
    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path)

    def export_all(
        self,
        *,
        workspace_id: str,
        project_id: str,
        record_types: tuple[str, ...] | None = None,
        active_only: bool = True,
    ) -> Iterator[RetrievalRecord]:
        wanted = set(record_types or ())
        superseded = _superseded_memory_ids(read_all(self.workspace_path, "facts"))
        for stream in MEMORY_STREAMS:
            for record in read_all(self.workspace_path, stream):
                mapped = memory_record_to_retrieval(record, workspace_id, project_id=project_id)
                if wanted and mapped.record_type not in wanted:
                    continue
                if active_only and (not mapped.active or mapped.source_id in superseded):
                    continue
                yield mapped

    def export_since(self, cursor: ExportCursor) -> ExportBatch:
        records = tuple(
            self.export_all(
                workspace_id=cursor.source_type,
                project_id="default",
                active_only=True,
            )
        )
        return ExportBatch(records=records, cursor=cursor, source_revision=source_revision(records))


def source_revision(records: tuple[RetrievalRecord, ...] | list[RetrievalRecord]) -> str:
    payload = [
        {
            "record_id": record.record_id,
            "source_id": record.source_id,
            "content_hash": record.content_hash,
            "updated_at": record.updated_at.isoformat(),
        }
        for record in records
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_revision(records: tuple[RetrievalRecord, ...] | list[RetrievalRecord]) -> str:
    raw = "|".join(sorted(record.content_hash for record in records))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _superseded_memory_ids(facts: list[dict]) -> set[str]:
    return {str(fact.get("supersedes")) for fact in facts if fact.get("supersedes")}
