# -*- coding: utf-8 -*-
"""
Decision/Outcome linkage for connectivity tasks.

Records deterministic routing decisions and execution outcomes,
linking tasks ->decisions ->outcomes ->audit records.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time
from nous_runtime.project.workspace import default_workspace_path

_log = logging.getLogger("nous.control_plane.linkage")

# Store paths -use project memory store from workspace
_DEFAULT_STORE_DIR = str(default_workspace_path("intelligence"))
_file_lock = threading.RLock()


def _ensure_store_dir(workspace_root: str = "") -> str:
    """Ensure the store directory exists."""
    store_dir = os.path.join(workspace_root or os.getcwd(), _DEFAULT_STORE_DIR)
    os.makedirs(store_dir, exist_ok=True)
    return store_dir


def _append_jsonl(filepath: str, record: dict[str, Any]) -> None:
    """Append one complete JSONL record while coordinating local readers."""
    try:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _file_lock, open(filepath, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception as e:
        _log.warning("Failed to append to %s: %s", filepath, e)


def _iter_jsonl_records(filepath: str) -> Iterator[dict[str, Any]]:
    """Yield valid records without letting one damaged line poison the store."""
    if not os.path.exists(filepath):
        return
    with _file_lock, open(filepath, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeError) as exc:
                _log.warning(
                    "Skipping malformed JSONL record in %s at line %d: %s",
                    filepath,
                    line_number,
                    exc,
                )
                continue
            if isinstance(record, dict):
                yield record


def record_task_decision(
    task_id: str,
    capability_id: str,
    node_id: str,
    session_id: str,
    reason: str = "deterministic_routing",
    workspace_root: str = "",
) -> str:
    """
    Record a deterministic routing decision for a task assignment.

    Returns the decision ID.
    """
    decision_id = _ids.make_id("dec")
    now = _time.utc_now()

    record = {
        "decision_id": decision_id,
        "decision_type": "task_routing",
        "task_id": task_id,
        "capability_id": capability_id,
        "selected_node": node_id,
        "session_id": session_id,
        "reason": reason,
        "candidates": [{"node_id": node_id, "capability_id": capability_id, "reason": reason}],
        "created_at": now,
    }

    store_dir = _ensure_store_dir(workspace_root)
    _append_jsonl(os.path.join(store_dir, "decisions.jsonl"), record)
    return decision_id


def record_task_outcome(
    task_id: str,
    decision_id: str,
    status: str,
    node_id: str,
    result: dict[str, Any] | None = None,
    error: str = "",
    duration_ms: int = 0,
    workspace_root: str = "",
) -> str:
    """
    Record a task execution outcome linked to its decision.

    Returns the outcome ID.
    """
    outcome_id = _ids.make_id("out")
    now = _time.utc_now()

    record = {
        "outcome_id": outcome_id,
        "decision_id": decision_id,
        "task_id": task_id,
        "node_id": node_id,
        "status": status,
        "result": result or {},
        "error": error,
        "duration_ms": duration_ms,
        "created_at": now,
    }

    store_dir = _ensure_store_dir(workspace_root)
    _append_jsonl(os.path.join(store_dir, "outcomes.jsonl"), record)
    return outcome_id


def get_task_decision(task_id: str, workspace_root: str = "") -> dict[str, Any] | None:
    """Find the decision record for a task."""
    store_dir = _ensure_store_dir(workspace_root)
    filepath = os.path.join(store_dir, "decisions.jsonl")
    try:
        for record in _iter_jsonl_records(filepath):
            if record.get("task_id") == task_id:
                return record
    except OSError as e:
        _log.warning("Failed to read decisions: %s", e)
    return None


def get_task_outcome(task_id: str, workspace_root: str = "") -> dict[str, Any] | None:
    """Find the outcome record for a task."""
    store_dir = _ensure_store_dir(workspace_root)
    filepath = os.path.join(store_dir, "outcomes.jsonl")
    try:
        for record in _iter_jsonl_records(filepath):
            if record.get("task_id") == task_id:
                return record
    except OSError as e:
        _log.warning("Failed to read outcomes: %s", e)
    return None


def verify_linkage(task_id: str, workspace_root: str = "") -> dict[str, Any]:
    """
    Verify that a task has complete decision/outcome linkage.
    Returns dict with linkage status and IDs.
    """
    decision = get_task_decision(task_id, workspace_root)
    outcome = get_task_outcome(task_id, workspace_root)

    return {
        "task_id": task_id,
        "has_decision": decision is not None,
        "decision_id": decision.get("decision_id") if decision else None,
        "has_outcome": outcome is not None,
        "outcome_id": outcome.get("outcome_id") if outcome else None,
        "decision_outcome_linked": (
            decision is not None
            and outcome is not None
            and decision.get("decision_id") == outcome.get("decision_id")
        ),
    }
