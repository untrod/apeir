"""Checkpoint integrity diagnostics and governed retention operations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from nous_runtime.checkpoint import CheckpointStoreError, SQLiteCheckpointStore
from nous_runtime.project.workspace import find_workspace


CHECKPOINT_DATABASE = "agent-checkpoints.db"


def _empty_plan_digest(keep_latest_per_task: int) -> str:
    canonical = json.dumps(
        {
            "keep_latest_per_task": keep_latest_per_task,
            "candidate_checkpoint_ids": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _empty_report(
    status: str,
    *,
    keep_latest_per_task: int,
    workspace_available: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "workspace_available": workspace_available,
        "database": {
            "filename": CHECKPOINT_DATABASE,
            "exists": False,
            "size_bytes": 0,
        },
        "integrity": {
            "quick_check": "not_run",
            "messages": [],
            "total": 0,
            "valid": 0,
            "invalid": 0,
        },
        "tasks": 0,
        "latest": [],
        "invalid": [],
        "retention": {
            "policy": "keep_latest_per_task",
            "keep_latest_per_task": keep_latest_per_task,
            "candidate_count": 0,
            "protected_count": 0,
            "invalid_excluded": 0,
            "plan_digest": _empty_plan_digest(keep_latest_per_task),
            "requires_governed_apply": True,
        },
    }


def checkpoint_report(
    *,
    limit: int = 20,
    keep_latest_per_task: int = 20,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect the durable Agent checkpoint database without exposing payloads."""
    maximum = max(1, min(int(limit), 100))
    keep_latest = SQLiteCheckpointStore._validate_keep_latest(
        keep_latest_per_task
    )
    workspace_path = (
        Path(workspace).resolve()
        if workspace is not None
        else find_workspace()
    )
    if workspace_path is None:
        return _empty_report(
            "unavailable",
            keep_latest_per_task=keep_latest,
            workspace_available=False,
            reason="workspace_not_found",
        )

    database_path = workspace_path / CHECKPOINT_DATABASE
    if not database_path.is_file():
        return _empty_report(
            "empty",
            keep_latest_per_task=keep_latest,
            workspace_available=True,
            reason="checkpoint_database_not_created",
        )

    try:
        report = SQLiteCheckpointStore(database_path).inspect(
            limit=maximum,
            keep_latest_per_task=keep_latest,
        )
    except (CheckpointStoreError, OSError, sqlite3.Error, ValueError):
        return {
            **_empty_report(
                "degraded",
                keep_latest_per_task=keep_latest,
                workspace_available=True,
                reason="checkpoint_database_unavailable",
            ),
            "database": {
                "filename": CHECKPOINT_DATABASE,
                "exists": True,
                "size_bytes": (
                    database_path.stat().st_size
                    if database_path.is_file()
                    else 0
                ),
            },
            "integrity": {
                "quick_check": "failed",
                "messages": ["database_unavailable"],
                "total": 0,
                "valid": 0,
                "invalid": 0,
            },
        }

    report["workspace_available"] = True
    report["reason"] = ""
    return report


def apply_checkpoint_retention(
    *,
    keep_latest_per_task: int,
    expected_plan_digest: str,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Apply a previously previewed exact retention plan."""
    workspace_path = (
        Path(workspace).resolve()
        if workspace is not None
        else find_workspace()
    )
    if workspace_path is None:
        raise CheckpointStoreError("checkpoint workspace was not found")
    database_path = workspace_path / CHECKPOINT_DATABASE
    if not database_path.is_file():
        raise CheckpointStoreError("checkpoint database was not found")
    return SQLiteCheckpointStore(database_path).prune(
        keep_latest_per_task=keep_latest_per_task,
        expected_plan_digest=expected_plan_digest,
    )


__all__ = [
    "CHECKPOINT_DATABASE",
    "apply_checkpoint_retention",
    "checkpoint_report",
]
