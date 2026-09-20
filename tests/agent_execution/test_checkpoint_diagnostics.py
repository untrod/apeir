from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from nous_runtime.api.routes import GOVERNED_MUTATION_ROUTES, route
from nous_runtime.checkpoint import (
    Checkpoint,
    CheckpointStoreError,
    SQLiteCheckpointStore,
)
from nous_runtime.core.redaction import REDACTED
from nous_runtime.inspector.checkpoints import checkpoint_report


def _checkpoint(
    checkpoint_id: str,
    task_id: str,
    timestamp: str,
    *,
    run_id: str = "",
) -> Checkpoint:
    return Checkpoint(
        checkpoint_id=checkpoint_id,
        task_id=task_id,
        timestamp=timestamp,
        state={"step": checkpoint_id},
        metadata={
            "kind": "agent_execution",
            "run_id": run_id or f"run-{checkpoint_id}",
            "agent_id": "agent-test",
            "private": {"must_not_leak": True},
        },
    )


def test_checkpoint_report_is_payload_free_and_has_retention_preview(
    tmp_path,
) -> None:
    workspace = tmp_path / ".nous"
    workspace.mkdir()
    store = SQLiteCheckpointStore(workspace / "agent-checkpoints.db")
    for item in (
        _checkpoint(
            "cp-a1",
            "task-a",
            "2026-01-01T00:00:01Z",
            run_id="sk-" + "abcdefghijklmnopqrstuvwxyz123456",  # security-scan: fixture
        ),
        _checkpoint("cp-a2", "task-a", "2026-01-01T00:00:02Z"),
        _checkpoint("cp-b1", "task-b", "2026-01-01T00:00:03Z"),
    ):
        store.save(item)

    report = checkpoint_report(
        workspace=workspace,
        limit=10,
        keep_latest_per_task=1,
    )

    assert report["status"] == "healthy"
    assert report["integrity"] == {
        "quick_check": "ok",
        "messages": ["ok"],
        "total": 3,
        "valid": 3,
        "invalid": 0,
    }
    assert report["tasks"] == 2
    assert report["retention"]["candidate_count"] == 1
    assert report["retention"]["protected_count"] == 2
    assert len(report["retention"]["plan_digest"]) == 64
    assert report["latest"][0]["checkpoint_id"] == "cp-b1"
    redacted = next(
        item for item in report["latest"]
        if item["checkpoint_id"] == "cp-a1"
    )
    assert redacted["run_id"] == REDACTED
    assert "state" not in report["latest"][0]
    assert "private" not in report["latest"][0]


def test_checkpoint_report_marks_tampered_rows_and_excludes_them_from_retention(
    tmp_path,
) -> None:
    workspace = tmp_path / ".nous"
    workspace.mkdir()
    path = workspace / "agent-checkpoints.db"
    store = SQLiteCheckpointStore(path)
    store.save(_checkpoint("cp-valid", "task-a", "2026-01-01T00:00:01Z"))
    store.save(_checkpoint("cp-tampered", "task-a", "2026-01-01T00:00:02Z"))
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE checkpoints SET payload_json = ? WHERE checkpoint_id = ?",
            ('{"state":{"secret":"changed"}}', "cp-tampered"),
        )
        connection.commit()

    report = checkpoint_report(
        workspace=workspace,
        keep_latest_per_task=1,
    )

    assert report["status"] == "degraded"
    assert report["integrity"]["valid"] == 1
    assert report["integrity"]["invalid"] == 1
    assert report["invalid"] == [
        {
            "checkpoint_id": "cp-tampered",
            "task_id": "task-a",
            "timestamp": "2026-01-01T00:00:02Z",
            "reason": "integrity_verification_failed",
        }
    ]
    assert report["retention"]["candidate_count"] == 0
    assert report["retention"]["invalid_excluded"] == 1


def test_retention_requires_current_plan_digest_and_keeps_latest_per_task(
    tmp_path,
) -> None:
    path = tmp_path / "agent-checkpoints.db"
    store = SQLiteCheckpointStore(path)
    store.save(_checkpoint("cp-a1", "task-a", "2026-01-01T00:00:01Z"))
    store.save(_checkpoint("cp-a2", "task-a", "2026-01-01T00:00:02Z"))
    initial = store.inspect(keep_latest_per_task=1)

    store.save(_checkpoint("cp-a3", "task-a", "2026-01-01T00:00:03Z"))
    with pytest.raises(CheckpointStoreError, match="plan changed"):
        store.prune(
            keep_latest_per_task=1,
            expected_plan_digest=initial["retention"]["plan_digest"],
        )

    current = store.inspect(keep_latest_per_task=1)
    result = store.prune(
        keep_latest_per_task=1,
        expected_plan_digest=current["retention"]["plan_digest"],
    )

    assert result["deleted_count"] == 2
    assert [item.checkpoint_id for item in store.list()] == ["cp-a3"]


def test_checkpoint_inspector_api_and_retention_governance(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / ".nous"
    workspace.mkdir()
    SQLiteCheckpointStore(workspace / "agent-checkpoints.db").save(
        _checkpoint("cp-api", "task-api", "2026-01-01T00:00:01Z")
    )
    monkeypatch.chdir(tmp_path)

    response = route(
        "GET",
        "/api/v1/inspector/checkpoints",
        params={"limit": "5", "keep_latest_per_task": "1"},
    )

    assert response["ok"] is True
    assert response["data"]["integrity"]["valid"] == 1
    assert GOVERNED_MUTATION_ROUTES[
        ("POST", "/api/v1/inspector/checkpoints/retention")
    ] == ("checkpoint.retention", "destructive", "irreversible")

    denied = route(
        "POST",
        "/api/v1/inspector/checkpoints/retention",
        body={
            "keep_latest_per_task": 1,
            "expected_plan_digest": response["data"]["retention"]["plan_digest"],
        },
    )
    assert denied["ok"] is False
    assert denied["error"]["code"] == "NOUS_UNAUTHENTICATED"
