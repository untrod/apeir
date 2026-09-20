"""Shared retrieval filtering helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nous_runtime.retrieval.models import RetrievalFilters, RetrievalRecord, RetrievalScope


def record_matches_scope(record: RetrievalRecord, scope: RetrievalScope) -> bool:
    if record.workspace_id != scope.workspace_id:
        return False
    if record.project_id not in scope.project_ids:
        return False
    if record.access_scope.principal_ids:
        return bool(scope.principal_id) and scope.principal_id in record.access_scope.principal_ids
    return record.access_scope.visibility != "private"


def record_matches_filters(
    record: RetrievalRecord,
    filters: RetrievalFilters,
    superseded_source_ids: set[str] | None = None,
) -> bool:
    if filters.active_only:
        if not record.active:
            return False
        if record.source_id in (superseded_source_ids or set()):
            return False
    if filters.record_types and record.record_type not in filters.record_types:
        return False
    if filters.source_types and record.source_type not in filters.source_types:
        return False
    if filters.task_ids and str(record.metadata.get("task_id") or "") not in filters.task_ids:
        return False
    if filters.capability_ids and str(record.metadata.get("capability_id") or "") not in filters.capability_ids:
        return False
    if filters.provider_ids and str(record.metadata.get("provider_id") or "") not in filters.provider_ids:
        return False
    if filters.created_after and record.created_at < filters.created_after:
        return False
    if filters.created_before and record.created_at > filters.created_before:
        return False
    return _metadata_matches(record.metadata, filters.metadata_equals)


def _metadata_matches(metadata: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if metadata.get(key) != value:
            return False
    return True


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
