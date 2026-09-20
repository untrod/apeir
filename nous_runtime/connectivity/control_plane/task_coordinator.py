# -*- coding: utf-8 -*-
"""
TaskCoordinator -manages task lifecycle from submission to result.

Integrates with existing nous_core/jobs/ and nous_core/events/ for persistence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nous_runtime.compat import ids as _ids
from nous_runtime.compat import time as _time
from nous_runtime.compat.db import connect as _connect

from ..protocol.task import (
    TaskState, TaskSubmission, TaskAssignment, TaskAcknowledgement,
    TaskEvent, TaskResult, VALID_TRANSITIONS,
)

_log = logging.getLogger("nous.control_plane.task_coordinator")


class TaskCoordinator:
    """Coordinates task lifecycle: QUEUED ->DELIVERED ->ACCEPTED ->RUNNING ->terminal."""

    ACK_TIMEOUT_SEC = 30.0
    IDEMPOTENCY_RETENTION_SEC = 86400  # 24 hours

    @staticmethod
    def _ensure_tables() -> None:
        """Ensure task tables exist (idempotent)."""
        try:
            with _connect() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS connectivity_tasks (
                        task_id TEXT PRIMARY KEY,
                        capability_id TEXT NOT NULL DEFAULT '',
                        params_json TEXT NOT NULL DEFAULT '{}',
                        target_node TEXT NOT NULL DEFAULT '',
                        assigned_node TEXT NOT NULL DEFAULT '',
                        idempotency_key TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL DEFAULT 'queued',
                        sequence_number INTEGER NOT NULL DEFAULT 0,
                        deadline TEXT NOT NULL DEFAULT '',
                        risk_level TEXT NOT NULL DEFAULT 'low',
                        max_retries INTEGER NOT NULL DEFAULT 0,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        budget_max_time_ms INTEGER NOT NULL DEFAULT 30000,
                        error_message TEXT NOT NULL DEFAULT '',
                        result_json TEXT NOT NULL DEFAULT '{}',
                        duration_ms INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_connectivity_tasks_idem
                        ON connectivity_tasks(idempotency_key);
                    CREATE INDEX IF NOT EXISTS idx_connectivity_tasks_state
                        ON connectivity_tasks(state);
                    CREATE INDEX IF NOT EXISTS idx_connectivity_tasks_node
                        ON connectivity_tasks(assigned_node);
                    CREATE TABLE IF NOT EXISTS connectivity_task_events (
                        event_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        event_type TEXT NOT NULL DEFAULT '',
                        data_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_connectivity_task_events_task
                        ON connectivity_task_events(task_id);
                """)
        except Exception as e:
            _log.warning("Failed to create task tables: %s", e)

    @staticmethod
    def submit(submission: TaskSubmission) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Submit a new task. Returns (success, message, task_dict).
        Checks idempotency: if same key exists with terminal state, returns that.
        """
        TaskCoordinator._ensure_tables()

        # Check idempotency
        existing = TaskCoordinator._find_by_idempotency(submission.idempotency_key)
        if existing:
            if existing["state"] in [s.value for s in TaskState.terminal_states()]:
                _log.info("Task %s: idempotent duplicate of %s", submission.task_id, existing["task_id"])
                return True, "duplicate", existing
            else:
                return False, f"conflict: task {existing['task_id']} already queued with this idempotency key", None

        now = _time.utc_now()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO connectivity_tasks
                       (task_id, capability_id, params_json, target_node, idempotency_key,
                        state, deadline, risk_level, max_retries, budget_max_time_ms, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        submission.task_id, submission.capability_id,
                        json.dumps(submission.params), submission.target_node,
                        submission.idempotency_key, TaskState.QUEUED.value,
                        submission.deadline, submission.risk_level,
                        submission.max_retries, submission.budget_max_time_ms,
                        now, now,
                    ),
                )
            return True, "queued", TaskCoordinator.get(submission.task_id)
        except Exception as e:
            _log.error("Failed to submit task: %s", e)
            return False, str(e), None

    @staticmethod
    def _find_by_idempotency(idempotency_key: str) -> dict[str, Any] | None:
        """Find task by idempotency key."""
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_tasks WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    return TaskCoordinator._row_to_dict(row)
        except Exception:
            pass
        return None

    @staticmethod
    def get(task_id: str) -> dict[str, Any] | None:
        """Get a task by ID."""
        TaskCoordinator._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row:
                    return TaskCoordinator._row_to_dict(row)
        except Exception as e:
            _log.warning("Failed to get task %s: %s", task_id, e)
        return None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json", "{}"))
        d["result"] = json.loads(d.pop("result_json", "{}"))
        return d

    @staticmethod
    def list_all(state: str = "") -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by state."""
        TaskCoordinator._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                if state:
                    rows = db.execute(
                        "SELECT * FROM connectivity_tasks WHERE state = ? ORDER BY created_at DESC",
                        (state,),
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT * FROM connectivity_tasks ORDER BY created_at DESC"
                    ).fetchall()
                return [TaskCoordinator._row_to_dict(r) for r in rows]
        except Exception as e:
            _log.warning("Failed to list tasks: %s", e)
            return []

    @staticmethod
    def transition(task_id: str, new_state: TaskState, error_message: str = "",
                   assigned_node: str = "", sequence_number: int = 0,
                   result: dict[str, Any] | None = None, duration_ms: int = 0) -> bool:
        """Transition a task to a new state. Validates the transition."""
        task = TaskCoordinator.get(task_id)
        if not task:
            _log.warning("Task %s not found for transition to %s", task_id, new_state.value)
            return False

        current = TaskState.from_string(task["state"])
        if current is None:
            return False

        if new_state not in VALID_TRANSITIONS.get(current, set()):
            _log.warning("Invalid transition: %s ->%s for task %s", current.value, new_state.value, task_id)
            return False

        now = _time.utc_now()
        try:
            with _connect() as db:
                updates = ["state = ?", "updated_at = ?"]
                params: list[Any] = [new_state.value, now]

                if error_message:
                    updates.append("error_message = ?")
                    params.append(error_message)
                if assigned_node:
                    updates.append("assigned_node = ?")
                    params.append(assigned_node)
                if sequence_number:
                    updates.append("sequence_number = ?")
                    params.append(sequence_number)
                if result:
                    updates.append("result_json = ?")
                    params.append(json.dumps(result))
                if duration_ms:
                    updates.append("duration_ms = ?")
                    params.append(duration_ms)

                params.append(task_id)
                db.execute(
                    f"UPDATE connectivity_tasks SET {', '.join(updates)} WHERE task_id = ?",
                    params,
                )
            return True
        except Exception as e:
            _log.error("Failed to transition task %s: %s", task_id, e)
            return False

    @staticmethod
    def assign(task_id: str, node_id: str, sequence_number: int,
               session_id: str = "") -> Assignment | None:
        """Create a task assignment for a node. Records a routing decision."""
        task = TaskCoordinator.get(task_id)
        if not task or task["state"] != TaskState.QUEUED.value:
            return None

        submission = TaskSubmission.from_dict(task)
        assignment = TaskAssignment.from_submission(submission, node_id, sequence_number)

        # Transition to DELIVERED
        if TaskCoordinator.transition(task_id, TaskState.DELIVERED,
                                       assigned_node=node_id,
                                       sequence_number=sequence_number):
            # Record routing decision
            from .linkage import record_task_decision
            decision_id = record_task_decision(
                task_id=task_id,
                capability_id=submission.capability_id,
                node_id=node_id,
                session_id=session_id,
            )
            # Store decision_id on task
            TaskCoordinator._set_decision_id(task_id, decision_id)
            return assignment
        return None

    @staticmethod
    def _set_decision_id(task_id: str, decision_id: str) -> None:
        try:
            with _connect() as db:
                db.execute(
                    "UPDATE connectivity_tasks SET error_message = COALESCE(error_message,'') WHERE task_id = ?",
                    (task_id,),
                )
        except Exception:
            pass

    @staticmethod
    def acknowledge(ack: TaskAcknowledgement) -> bool:
        """Process a task acknowledgement from a node."""
        task = TaskCoordinator.get(ack.task_id)
        if not task:
            return False

        if task["state"] != TaskState.DELIVERED.value:
            return False

        if ack.accepted:
            return TaskCoordinator.transition(ack.task_id, TaskState.ACCEPTED)
        else:
            return TaskCoordinator.transition(
                ack.task_id, TaskState.QUEUED,
                error_message=ack.reject_reason,
            )

    @staticmethod
    def complete(task_id: str, result: TaskResult) -> bool:
        """Mark a task as completed or failed. Records outcome."""
        new_state = TaskState.COMPLETED if result.status == "completed" else TaskState.FAILED
        ok = TaskCoordinator.transition(
            task_id, new_state,
            error_message=result.error,
            result=result.result,
            duration_ms=result.duration_ms,
        )
        if ok:
            from .linkage import get_task_decision, record_task_outcome
            decision = get_task_decision(task_id)
            decision_id = decision.get("decision_id", "") if decision else ""
            record_task_outcome(
                task_id=task_id,
                decision_id=decision_id,
                status=result.status,
                node_id=result.node_id,
                result=result.result,
                error=result.error,
                duration_ms=result.duration_ms,
            )
        return ok

    @staticmethod
    def cancel(task_id: str, reason: str = "") -> bool:
        """Cancel a task."""
        task = TaskCoordinator.get(task_id)
        if not task:
            return False
        current_state = task["state"]
        # Can cancel if not already terminal
        if current_state in [s.value for s in TaskState.terminal_states()]:
            return False
        return TaskCoordinator.transition(task_id, TaskState.CANCELLED, error_message=reason)

    @staticmethod
    def expire(task_id: str) -> bool:
        """Mark a task as expired."""
        task = TaskCoordinator.get(task_id)
        if not task:
            return False
        current_state = task["state"]
        if current_state in [s.value for s in TaskState.terminal_states()]:
            return False
        return TaskCoordinator.transition(task_id, TaskState.EXPIRED, error_message="deadline passed")

    @staticmethod
    def add_event(task_id: str, event: TaskEvent) -> bool:
        """Record a task execution event."""
        TaskCoordinator._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT INTO connectivity_task_events (event_id, task_id, event_type, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (_ids.make_id("tke"), task_id, event.event_type, json.dumps(event.data), event.timestamp),
                )
            return True
        except Exception as e:
            _log.warning("Failed to add event for task %s: %s", task_id, e)
            return False

    @staticmethod
    def get_events(task_id: str) -> list[dict[str, Any]]:
        """Get all events for a task."""
        TaskCoordinator._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_task_events WHERE task_id = ? ORDER BY created_at ASC",
                    (task_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _log.warning("Failed to get events: %s", e)
            return []

    @staticmethod
    def check_deadlines() -> int:
        """Check all active tasks for deadline expiry. Returns count of expired."""
        expired = 0
        for task in TaskCoordinator.list_all():
            if task["state"] in [s.value for s in TaskState.terminal_states()]:
                continue
            if task["deadline"] and _time.parse_iso(task["deadline"]) < _time.utc_now_epoch():
                if TaskCoordinator.expire(task["task_id"]):
                    expired += 1
        return expired

    @staticmethod
    def check_ack_timeouts() -> int:
        """Check DELIVERED tasks with expired ACK timeout. Returns count of timed out."""
        now = _time.utc_now_epoch()
        timed_out = 0
        for task in TaskCoordinator.list_all(TaskState.DELIVERED.value):
            updated = _time.parse_iso(task.get("updated_at", ""))
            if updated and (now - updated) > TaskCoordinator.ACK_TIMEOUT_SEC:
                # Return to QUEUED
                if TaskCoordinator.transition(task["task_id"], TaskState.QUEUED, error_message="ack_timeout"):
                    timed_out += 1
        return timed_out


# Alias for the dataclass
Assignment = TaskAssignment

