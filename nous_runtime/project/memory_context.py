# -*- coding: utf-8 -*-
"""Budgeted memory context builder."""

from __future__ import annotations

import json as _json
from pathlib import Path as _Path
from typing import Any

from nous_runtime.project.memory import (
    project_summary,
    search_memory,
    task_context,
)


def build_memory_context(
    workspace: str | _Path,
    query: str = "",
    task_id: str = "",
    max_records: int = 12,
    max_characters: int = 4000,
) -> dict[str, Any]:
    """Build a compact memory context block with explicit budget controls."""
    records: list[dict[str, Any]] = []

    if task_id:
        records.extend(task_context(workspace, task_id).get("records", []))

    if query:
        records.extend(search_memory(workspace, query, limit=max_records))

    summary = project_summary(workspace)
    records.extend(summary.get("facts", [])[:6])
    records.extend(summary.get("recent_decisions", [])[:3])
    if summary.get("latest_summary"):
        records.append(summary["latest_summary"])

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    chars = 0
    for record in records:
        rid = str(record.get("memory_id") or record.get("id") or id(record))
        if rid in seen:
            continue
        seen.add(rid)
        compact = _compact_record(record)
        text = _json.dumps(compact, ensure_ascii=False, sort_keys=True)
        if len(selected) >= max_records or chars + len(text) > max_characters:
            break
        chars += len(text)
        selected.append(compact)

    return {
        "records": selected,
        "record_count": len(selected),
        "characters": chars,
        "context": _render_context(selected),
    }


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "record_type",
        "memory_id",
        "created_at",
        "event_type",
        "detail",
        "key",
        "value",
        "question",
        "answer",
        "title",
        "content",
        "capability_id",
        "provider_id",
        "outcome",
        "tags",
    }
    compact = {k: v for k, v in record.items() if k in keep and v not in ("", [], {})}
    if "content" in compact and isinstance(compact["content"], str) and len(compact["content"]) > 500:
        compact["content"] = compact["content"][:497] + "..."
    return compact


def _render_context(records: list[dict[str, Any]]) -> str:
    if not records:
        return "[Project Memory]\nNo relevant records selected."
    lines = ["[Project Memory]", f"Records used: {len(records)}"]
    for record in records:
        rtype = record.get("record_type", "record")
        rid = record.get("memory_id", record.get("id", "")) or ""
        if rtype == "fact":
            lines.append(f"- fact {record.get('key')}: {record.get('value')} ({rid})")
        elif rtype == "decision":
            lines.append(f"- decision {record.get('question')}: {record.get('answer')} ({rid})")
        elif rtype == "summary":
            lines.append(f"- summary {record.get('title', '')}: {record.get('content', '')} ({rid})")
        else:
            lines.append(f"- {rtype} {record.get('event_type', '')}: {record.get('detail', '')} ({rid})")
    return "\n".join(lines)
