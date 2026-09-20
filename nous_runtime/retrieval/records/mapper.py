"""Mapping from authoritative memory records into retrieval records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.retrieval.models import AccessScope, RetrievalRecord
from nous_runtime.retrieval.records.hashing import hash_content

_MEMORY_RECORD_TYPES = {
    "event": "memory_event",
    "fact": "memory_fact",
    "decision": "memory_decision",
    "summary": "memory_summary",
    "experience": "memory_experience",
    "artifactref": "memory_artifact",
    "artifact_ref": "memory_artifact",
}


def map_memory_records(
    records: list[Mapping[str, Any]],
    workspace_id: str,
    project_id: str | None = None,
) -> list[RetrievalRecord]:
    mapped: list[RetrievalRecord] = []
    for record in records:
        mapped.append(memory_record_to_retrieval(record, workspace_id, project_id=project_id))
    return mapped


def memory_record_to_retrieval(
    record: Mapping[str, Any],
    workspace_id: str,
    project_id: str | None = None,
) -> RetrievalRecord:
    source_id = str(record.get("memory_id") or record.get("id") or "")
    if not source_id:
        source_id = _stable_id("memory", json.dumps(dict(record), sort_keys=True, ensure_ascii=False))
    memory_type = str(record.get("record_type") or record.get("_kind") or "event").lower()
    record_type = _MEMORY_RECORD_TYPES.get(memory_type, "memory_event")
    project = str(record.get("project_id") or project_id or "default")
    content = _memory_content(record, memory_type)
    created_at = _parse_datetime(record.get("created_at") or record.get("timestamp"))
    metadata = _memory_metadata(record)
    metadata.setdefault("active", bool(record.get("active", True)))

    return RetrievalRecord(
        record_id=_stable_id(workspace_id, source_id, record_type),
        record_type=record_type,
        workspace_id=workspace_id,
        project_id=project,
        source_id=source_id,
        source_type=str(record.get("source_type") or "memory"),
        title=_memory_title(record, memory_type),
        content=content,
        content_hash=hash_content(content),
        stable_key=_optional_str(record.get("stable_key") or record.get("key")),
        version=1,
        supersedes=_optional_str(record.get("supersedes")),
        created_at=created_at,
        updated_at=created_at,
        metadata=metadata,
        access_scope=AccessScope(workspace_id=workspace_id, project_ids=(project,)),
        embedding_status="not_required",
        index_status="pending",
    )


def _memory_content(record: Mapping[str, Any], memory_type: str) -> str:
    if memory_type == "fact":
        return f"{record.get('key', '')}: {_stringify(record.get('value', ''))}".strip()
    if memory_type == "decision":
        return "\n".join(
            part for part in (
                f"Question: {record.get('question', '')}",
                f"Answer: {record.get('answer', '')}",
                f"Rationale: {record.get('rationale', '')}",
            )
            if part.split(": ", 1)[-1]
        )
    if memory_type == "summary":
        return str(record.get("content") or record.get("title") or "")
    if memory_type == "experience":
        return " ".join(
            part for part in (
                str(record.get("capability_id") or ""),
                str(record.get("provider_id") or ""),
                str(record.get("outcome") or ""),
                str(record.get("error_code") or ""),
            )
            if part
        )
    if memory_type in {"artifactref", "artifact_ref"}:
        return " ".join(
            part for part in (
                str(record.get("artifact_id") or ""),
                str(record.get("kind") or ""),
                str(record.get("path") or ""),
                str(record.get("description") or ""),
            )
            if part
        )
    return str(record.get("detail") or record.get("event_type") or record.get("type") or "")


def _memory_title(record: Mapping[str, Any], memory_type: str) -> str | None:
    if memory_type == "fact":
        return _optional_str(record.get("key"))
    if memory_type == "decision":
        return _optional_str(record.get("question"))
    if memory_type == "summary":
        return _optional_str(record.get("title"))
    if memory_type == "experience":
        return _optional_str(record.get("capability_id"))
    if memory_type in {"artifactref", "artifact_ref"}:
        return _optional_str(record.get("artifact_id") or record.get("path"))
    return _optional_str(record.get("event_type") or record.get("type"))


def _memory_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "task_graph_id",
        "task_id",
        "observation_id",
        "capability_id",
        "provider_id",
        "confidence",
        "tags",
        "schema_version",
        "artifact_id",
        "kind",
    )
    metadata: dict[str, Any] = {}
    for field in fields:
        value = record.get(field)
        if value not in ("", None, [], {}):
            metadata[field] = value
    nested = record.get("metadata")
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            if value not in ("", None, [], {}):
                metadata[str(key)] = value
    return metadata


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"retr_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
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


def _optional_str(value: Any) -> str | None:
    if value in ("", None):
        return None
    return str(value)


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
