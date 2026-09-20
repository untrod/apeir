"""Outbox and indexing job primitives."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class IndexingJobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class IndexingJob:
    job_id: str
    job_type: str
    state: IndexingJobState
    payload: dict[str, Any]
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["created_at"] = _format_datetime(self.created_at)
        data["updated_at"] = _format_datetime(self.updated_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexingJob":
        return cls(
            job_id=str(data.get("job_id") or ""),
            job_type=str(data.get("job_type") or ""),
            state=IndexingJobState(str(data.get("state") or "pending")),
            payload=dict(data.get("payload") or {}),
            attempts=int(data.get("attempts") or 0),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            error=str(data.get("error") or ""),
        )

    def with_state(self, state: IndexingJobState, *, error: str = "") -> "IndexingJob":
        return IndexingJob(
            job_id=self.job_id,
            job_type=self.job_type,
            state=state,
            payload=dict(self.payload),
            attempts=self.attempts + (1 if state == IndexingJobState.RUNNING else 0),
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            error=error,
        )


class JsonlIndexingOutbox:
    def __init__(self, workspace_path: str | Path):
        self.path = Path(workspace_path) / "retrieval" / "indexing_jobs.jsonl"

    def enqueue(self, job_type: str, payload: dict[str, Any]) -> IndexingJob:
        job = IndexingJob(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            job_type=job_type,
            state=IndexingJobState.PENDING,
            payload=payload,
        )
        self._append(job)
        return job

    def pending(self) -> list[IndexingJob]:
        return [job for job in _latest(self.path).values() if job.state == IndexingJobState.PENDING]

    def lease_next(self) -> IndexingJob | None:
        pending = self.pending()
        if not pending:
            return None
        job = sorted(pending, key=lambda item: item.created_at)[0].with_state(IndexingJobState.RUNNING)
        self._append(job)
        return job

    def complete(self, job_id: str) -> IndexingJob:
        job = self._require(job_id).with_state(IndexingJobState.SUCCEEDED)
        self._append(job)
        return job

    def fail(self, job_id: str, error: str) -> IndexingJob:
        job = self._require(job_id).with_state(IndexingJobState.FAILED, error=error)
        self._append(job)
        return job

    def list(self) -> list[IndexingJob]:
        return sorted(_latest(self.path).values(), key=lambda item: item.created_at)

    def _require(self, job_id: str) -> IndexingJob:
        jobs = _latest(self.path)
        if job_id not in jobs:
            raise KeyError(f"indexing job not found: {job_id}")
        return jobs[job_id]

    def _append(self, job: IndexingJob) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(job.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def _latest(path: Path) -> dict[str, IndexingJob]:
    if not path.is_file():
        return {}
    jobs: dict[str, IndexingJob] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                job = IndexingJob.from_dict(data)
                jobs[job.job_id] = job
    return jobs


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text) if text else datetime.now(timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
