# -*- coding: utf-8 -*-
"""Context Snapshot — long-running session recovery.

create_snapshot()  — capture current context state for later restore.
restore_snapshot() — recover project, agent, task, decision, device state
                     after a server restart.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nous_runtime.context.builder import ContextBuilder, BuildRequest
from nous_runtime.context.exceptions import ContextRestoreError
from nous_runtime.context.models import ContextSnapshot
from nous_runtime.context.store import ContextStore
from nous_runtime.context.schema import SnapshotStatus
from nous_runtime.context.types import RestoreResult

_log = logging.getLogger("nous.context.snapshot")



# Create


def create_snapshot(
    workspace: str = "",
    *,
    intent: str = "session_checkpoint",
    user_id: str = "",
    project_id: str = "",
    task_id: str = "",
    agent_id: str = "",
    persist: bool = True,
) -> ContextSnapshot:
    """Create a full context snapshot for later recovery.

    Captures state from all context providers: project, memory, agent,
    decision, and device.  Optionally persists to the ContextStore.

    Args:
        workspace: Path to the .nous workspace.
        intent: Human-readable description of why this snapshot was created.
        user_id: Optional user identifier.
        project_id: Optional project identifier.
        task_id: Optional task identifier.
        agent_id: Optional agent identifier.
        persist: If True, also save to ContextStore.

    Returns:
        A ContextSnapshot ready for restore.

    Raises:
        ContextRestoreError: If snapshot creation fails.
    """
    t0 = time.perf_counter()
    _log.info("Creating snapshot for intent='%s'", intent)

    try:
        request = BuildRequest(
            intent=intent,
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            max_items=200,
        )
        builder = ContextBuilder(workspace=workspace)
        snapshot = builder.build_context(request)

        # Mark as a checkpoint
        object.__setattr__(snapshot, "metadata", {
            **snapshot.metadata,
            "snapshot_type": "checkpoint",
            "intent": intent,
        })

        if persist:
            store = ContextStore(workspace)
            store.save(snapshot)
            _log.info("Snapshot %s persisted to store.", snapshot.id)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        _log.info("Snapshot %s created in %d ms.", snapshot.id, elapsed_ms)
        return snapshot

    except Exception as exc:
        raise ContextRestoreError(f"Failed to create snapshot: {exc}") from exc



# Restore


def restore_snapshot(
    snapshot_id: str = "",
    workspace: str = "",
    *,
    intent: str = "",
) -> RestoreResult:
    """Restore context from a previously saved snapshot.

    Use this after a server restart to recover:
      - Project state (current phase, checkpoints, plan)
      - Active agents
      - Pending tasks
      - Recent decisions
      - Device registrations

    Args:
        snapshot_id: ID of the snapshot to restore. If empty, restores the
                     most recent active snapshot.
        workspace: Path to the .nous workspace.
        intent: Optional intent hint (used if a new snapshot must be built).

    Returns:
        RestoreResult with success status and details.
    """
    t0 = time.perf_counter()
    store = ContextStore(workspace)
    errors: list[str] = []
    missing_sources: list[str] = []

    try:
        # Resolve snapshot to restore
        snapshot: ContextSnapshot | None = None

        if snapshot_id:
            snapshot = store.get(snapshot_id)
            if snapshot is None:
                return RestoreResult(
                    snapshot_id=snapshot_id,
                    success=False,
                    errors=[f"Snapshot {snapshot_id} not found."],
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                )
        else:
            # Find the most recent active snapshot
            active = store.list(status="active", limit=1)
            if active:
                snapshot = active[0]
            else:
                # No stored snapshot — build a fresh one
                _log.info("No stored snapshot found; building fresh context.")
                snapshot = create_snapshot(workspace=workspace, intent=intent or "restore_fallback")

        # Validate snapshot
        restored_items = snapshot.item_count
        if restored_items == 0:
            missing_sources.append("all")

        # Validate provenance against the content that was actually restored.
        # A snapshot may intentionally contain only a subset of Context sources;
        # absence is an error only when the snapshot declares a source whose
        # corresponding content did not survive persistence.
        declared_sources = set(snapshot.sources)
        populated_sources = {item.source_type for item in snapshot.items}
        for source in declared_sources:
            if hasattr(snapshot, source) and getattr(snapshot, source):
                populated_sources.add(source)
        missing = declared_sources - populated_sources
        if missing:
            missing_sources.extend(sorted(missing))
            _log.warning("Restored snapshot missing sources: %s", sorted(missing))

        undeclared = populated_sources - declared_sources
        if undeclared:
            errors.append(
                "Restored content has undeclared sources: "
                + ", ".join(sorted(undeclared))
            )
            _log.warning("Restored snapshot has undeclared sources: %s", sorted(undeclared))

        # Mark as restored in store
        try:
            store.save(snapshot.with_status(SnapshotStatus.RESTORED))
        except Exception as exc:
            _log.warning("Failed to mark snapshot as restored: %s", exc)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        _log.info(
            "Restored snapshot %s: %d items from %d sources in %d ms.",
            snapshot.id, restored_items, len(declared_sources), elapsed_ms,
        )

        return RestoreResult(
            snapshot_id=snapshot.id,
            success=True,
            restored_items=restored_items,
            missing_sources=missing_sources,
            errors=errors,
            duration_ms=elapsed_ms,
        )

    except ContextRestoreError:
        raise
    except Exception as exc:
        raise ContextRestoreError(f"Failed to restore snapshot: {exc}") from exc



# List / query


def list_snapshots(
    workspace: str = "",
    *,
    limit: int = 50,
    status: str = "",
) -> list[dict[str, Any]]:
    """List available snapshots in the store.

    Returns lightweight summaries (not full snapshot objects).
    """
    store = ContextStore(workspace)
    snapshots = store.list(limit=limit, status=status)
    return [
        {
            "id": s.id,
            "timestamp": s.timestamp,
            "status": s.status,
            "item_count": s.item_count,
            "sources": list(s.sources),
            "confidence": s.confidence,
            "checksum": s.checksum(),
            "intent": s.metadata.get("intent", ""),
        }
        for s in snapshots
    ]


def latest_snapshot_id(workspace: str = "") -> str:
    """Return the ID of the most recent snapshot, or empty string."""
    store = ContextStore(workspace)
    active = store.list(status="active", limit=1)
    if active:
        return active[0].id
    return ""
