# -*- coding: utf-8 -*-
"""Local structured project memory.

Memory is local-first and append-only. `timeline.jsonl` is retained as a
compatibility alias, while new structured records are written to:

    events.jsonl
    facts.jsonl
    decisions.jsonl
    summaries.jsonl
    experiences.jsonl
    artifacts.jsonl
"""

from __future__ import annotations

import json as _json
import os as _os
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path
from typing import Any, Literal

from nous_runtime.project.memory_records import (
    MemoryArtifactRef,
    MemoryDecision,
    MemoryEvent,
    MemoryExperience,
    MemoryFact,
    MemoryRecord,
    MemorySummary,
)

MemoryKind = Literal[
    "timeline",
    "events",
    "decisions",
    "summaries",
    "facts",
    "experiences",
    "artifacts",
]

_KIND_FILENAME: dict[MemoryKind, str] = {
    "timeline": "timeline.jsonl",
    "events": "events.jsonl",
    "decisions": "decisions.jsonl",
    "summaries": "summaries.jsonl",
    "facts": "facts.jsonl",
    "experiences": "experiences.jsonl",
    "artifacts": "artifacts.jsonl",
}


def add_event(workspace: str | _Path, event_type: str, detail: str = "") -> dict[str, Any]:
    """Append a legacy timeline event and a structured event record."""
    entry = _append(
        workspace,
        "timeline",
        {"type": event_type, "detail": _compact_text(detail)},
    )
    record = MemoryEvent(
        source_type="runtime",
        project_id=_project_id(workspace),
        event_type=event_type,
        detail=_compact_text(detail),
        tags=["event"],
        metadata={"legacy_timeline_id": entry["id"]},
    )
    add_memory_record(workspace, record)
    return entry


def add_decision(
    workspace: str | _Path, question: str, answer: str, rationale: str = ""
) -> dict[str, Any]:
    """Record a user-confirmed decision."""
    record = MemoryDecision(
        source_type="user",
        project_id=_project_id(workspace),
        question=_redact_text(question),
        answer=_redact_text(answer),
        rationale=_redact_text(rationale),
        tags=["decision"],
    )
    return add_memory_record(workspace, record)


def add_summary(
    workspace: str | _Path, content: str, tags: list[str] | None = None
) -> dict[str, Any]:
    """Record a compact stage summary."""
    record = MemorySummary(
        source_type="runtime",
        project_id=_project_id(workspace),
        content=_compact_text(content),
        tags=tags or [],
    )
    return add_memory_record(workspace, record)


def add_fact(
    workspace: str | _Path, key: str, value: Any, source: str = ""
) -> dict[str, Any]:
    """Record a stable fact.

    Facts are append-only. A newer fact with the same key supersedes the
    previous one through the `supersedes` field; retrieval returns only the
    latest active fact per stable key.
    """
    previous = _latest_fact_for_key(workspace, key)
    record = MemoryFact(
        source_type="runtime",
        project_id=_project_id(workspace),
        key=key,
        stable_key=key,
        value=_redact_value(value),
        supersedes=previous.get("memory_id", previous.get("id", "")) if previous else "",
        tags=["fact"],
        metadata={"source": source} if source else {},
    )
    return add_memory_record(workspace, record)


def add_experience(
    workspace: str | _Path,
    capability_id: str,
    provider_id: str,
    outcome: str,
    error_code: str = "",
    count: int = 1,
) -> dict[str, Any]:
    """Record a provider/capability experience candidate."""
    record = MemoryExperience(
        source_type="observation",
        project_id=_project_id(workspace),
        capability_id=capability_id,
        provider_id=provider_id,
        outcome=outcome,
        error_code=error_code,
        count=count,
        tags=["experience", capability_id] if capability_id else ["experience"],
    )
    return add_memory_record(workspace, record)


def add_artifact_ref(
    workspace: str | _Path,
    artifact_id: str,
    path: str,
    kind: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Record an artifact reference without storing artifact content."""
    record = MemoryArtifactRef(
        source_type="artifact",
        project_id=_project_id(workspace),
        artifact_id=artifact_id,
        path=_safe_path(path),
        kind=kind,
        description=_compact_text(description),
        tags=["artifact", kind] if kind else ["artifact"],
    )
    return add_memory_record(workspace, record)


def add_memory_record(workspace: str | _Path, record: MemoryRecord) -> dict[str, Any]:
    """Validate and append a canonical memory record."""
    errors = record.validate()
    if errors:
        raise ValueError("; ".join(errors))
    data = _redact_record(record.to_dict())
    if data.get("record_type") == "fact" and not data.get("supersedes"):
        stable_key = str(data.get("stable_key") or data.get("key") or "")
        previous = _latest_fact_for_key(workspace, stable_key) if stable_key else {}
        if previous:
            data["supersedes"] = previous.get("memory_id", previous.get("id", ""))
    kind = _record_kind(str(data.get("record_type", "event")))
    return _append_dict(workspace, kind, data)


def read_recent(
    workspace: str | _Path,
    kind: MemoryKind = "timeline",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the most recent entries from a memory stream."""
    limit = max(1, min(int(limit), 500))
    entries = read_all(workspace, kind)
    return entries[-limit:]


def read_all(
    workspace: str | _Path,
    kind: MemoryKind = "timeline",
) -> list[dict[str, Any]]:
    """Return all entries from a memory stream, skipping malformed lines."""
    fp = _file_path(workspace, kind)
    if not fp.is_file():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    entries.append(data)
    except Exception:
        return []
    return entries


def recent_events(workspace: str | _Path, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent structured events, falling back to legacy timeline."""
    events = read_recent(workspace, "events", limit=limit)
    if events:
        return events
    return read_recent(workspace, "timeline", limit=limit)


def active_facts(workspace: str | _Path, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """Return the latest active fact for each stable key."""
    tag_set = set(tags or [])
    latest: dict[str, dict[str, Any]] = {}
    for fact in read_all(workspace, "facts"):
        stable_key = fact.get("stable_key") or fact.get("key")
        if not stable_key:
            continue
        if tag_set and not tag_set.intersection(set(fact.get("tags", []))):
            continue
        latest[stable_key] = fact
    return [dict(f, active=True) for f in latest.values()]


def recent_decisions(workspace: str | _Path, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent decisions."""
    return read_recent(workspace, "decisions", limit=limit)


def project_summary(workspace: str | _Path) -> dict[str, Any]:
    """Return compact project memory summary."""
    summaries = read_recent(workspace, "summaries", limit=1)
    return {
        "latest_summary": summaries[-1] if summaries else {},
        "facts": active_facts(workspace)[:20],
        "recent_decisions": recent_decisions(workspace, limit=5),
        "recent_events": recent_events(workspace, limit=5),
    }


def task_context(workspace: str | _Path, task_id: str) -> dict[str, Any]:
    """Return memory records tied to a task ID."""
    records: list[dict[str, Any]] = []
    for kind in ("events", "summaries", "experiences", "artifacts"):
        records.extend(r for r in read_all(workspace, kind) if r.get("task_id") == task_id)
    return {"task_id": task_id, "records": records}


def search_memory(workspace: str | _Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Keyword search over local memory streams."""
    q = query.lower()
    results: list[dict[str, Any]] = []
    for kind in ("events", "facts", "decisions", "summaries", "experiences", "artifacts", "timeline"):
        for record in read_all(workspace, kind):
            text = _json.dumps(record, ensure_ascii=False).lower()
            if q in text:
                item = dict(record)
                item["_kind"] = kind
                results.append(item)
                if len(results) >= limit:
                    return results
    return results


def experience_for(workspace: str | _Path, capability_id: str) -> list[dict[str, Any]]:
    """Return experience records for a capability."""
    return [
        r for r in read_all(workspace, "experiences")
        if r.get("capability_id") == capability_id
    ]


def _file_path(workspace: str | _Path, kind: MemoryKind) -> _Path:
    fname = _KIND_FILENAME.get(kind, f"{kind}.jsonl")
    return _Path(workspace) / "memory" / fname


def _append(
    workspace: str | _Path,
    kind: MemoryKind,
    extra: dict[str, Any],
) -> dict[str, Any]:
    import uuid as _uuid

    entry: dict[str, Any] = {
        "id": _uuid.uuid4().hex[:12],
        "timestamp": _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    entry.update(_redact_record(extra))
    return _append_dict(workspace, kind, entry)


def _append_dict(workspace: str | _Path, kind: MemoryKind, entry: dict[str, Any]) -> dict[str, Any]:
    fp = _file_path(workspace, kind)
    _os.makedirs(fp.parent, exist_ok=True)
    line = _json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with open(fp, "a", encoding="utf-8") as fh:
        fh.write(line)
    return entry


def _record_kind(record_type: str) -> MemoryKind:
    mapping: dict[str, MemoryKind] = {
        "event": "events",
        "fact": "facts",
        "decision": "decisions",
        "summary": "summaries",
        "experience": "experiences",
        "artifactref": "artifacts",
        "artifact_ref": "artifacts",
    }
    return mapping.get(record_type, "events")


def _latest_fact_for_key(workspace: str | _Path, key: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for fact in read_all(workspace, "facts"):
        if fact.get("stable_key", fact.get("key")) == key:
            latest = fact
    return latest


def _project_id(workspace: str | _Path) -> str:
    fp = _Path(workspace) / "project.json"
    if fp.is_file():
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
            return str(data.get("name") or _Path(workspace).parent.name)
        except Exception:
            pass
    return _Path(workspace).parent.name


def _redact_record(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k).lower().replace("-", "_")
            if any(part in key for part in ("api_key", "apikey", "token", "secret", "password", "private_key")):
                redacted[k] = "<redacted>"
            else:
                redacted[k] = _redact_record(v)
        return redacted
    if isinstance(value, list):
        return [_redact_record(v) for v in value]
    if isinstance(value, str):
        return _compact_text(value)
    return value


def _redact_value(value: Any) -> Any:
    return _redact_record(value)


def _redact_text(value: str) -> str:
    return _compact_text(value)


def _compact_text(value: str, limit: int = 500) -> str:
    text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _safe_path(path: str) -> str:
    p = str(path)
    if p.startswith("/") or p.startswith("\\\\") or (len(p) > 2 and p[1:3] in (":\\", ":/")):
        return _Path(p).name
    return p
