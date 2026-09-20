# -*- coding: utf-8 -*-
"""SQLite-backed ProjectStore -durable project state persistence."""

from __future__ import annotations

import json
import logging
from typing import Any

from nous_runtime.compat import time as _time
from nous_runtime.compat.db import connect as _connect

from .models import (
    Project, ProjectGoal, Milestone, WorkPlan, WorkItem,
    ExecutionAttempt, Checkpoint, ContinuationDecision, ProjectEvent,
)

_log = logging.getLogger("nous.project.store")


class ProjectStore:
    """Durable SQLite store for project, work items, checkpoints, and events."""

    @staticmethod
    def _ensure_tables() -> None:
        try:
            with _connect() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS connectivity_projects (
                        project_id TEXT PRIMARY KEY, name TEXT, description TEXT,
                        status TEXT DEFAULT 'draft', owner TEXT,
                        created_at TEXT, updated_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_goals (
                        goal_id TEXT PRIMARY KEY, project_id TEXT, description TEXT,
                        success_criteria TEXT DEFAULT '[]', priority TEXT DEFAULT 'medium',
                        status TEXT DEFAULT 'pending'
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_milestones (
                        milestone_id TEXT PRIMARY KEY, project_id TEXT, goal_id TEXT,
                        description TEXT, target_date TEXT, status TEXT DEFAULT 'pending',
                        work_item_ids TEXT DEFAULT '[]'
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_work_plans (
                        plan_id TEXT PRIMARY KEY, project_id TEXT, version INTEGER DEFAULT 1,
                        work_item_ids TEXT DEFAULT '[]', dependency_graph TEXT DEFAULT '{}',
                        status TEXT DEFAULT 'draft', created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_work_items (
                        work_item_id TEXT PRIMARY KEY, project_id TEXT, milestone_id TEXT,
                        description TEXT, target_node TEXT, required_capability TEXT,
                        params_json TEXT DEFAULT '{}', risk_level TEXT DEFAULT 'low',
                        status TEXT DEFAULT 'planned', depends_on TEXT DEFAULT '[]',
                        task_id TEXT, budget_max_time_ms INTEGER DEFAULT 30000,
                        completion_condition TEXT, created_at TEXT, updated_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_execution_attempts (
                        attempt_id TEXT PRIMARY KEY, work_item_id TEXT, task_id TEXT,
                        node_id TEXT, status TEXT, result_json TEXT DEFAULT '{}',
                        error TEXT, duration_ms INTEGER DEFAULT 0,
                        started_at TEXT, completed_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_checkpoints (
                        checkpoint_id TEXT PRIMARY KEY, project_id TEXT,
                        description TEXT, work_item_states TEXT DEFAULT '{}',
                        artifact_hashes TEXT DEFAULT '[]', created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_continuation_decisions (
                        decision_id TEXT PRIMARY KEY, request_id TEXT, project_id TEXT,
                        action TEXT, resolved_work_item TEXT,
                        reason TEXT, created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_project_events (
                        event_id TEXT PRIMARY KEY, project_id TEXT, event_type TEXT,
                        work_item_id TEXT, data_json TEXT DEFAULT '{}', created_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS connectivity_runtime_bindings (
                        conversation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                        work_item_id TEXT NOT NULL, run_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'running',
                        checkpoint_id TEXT DEFAULT '', updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_runtime_bindings_project
                    ON connectivity_runtime_bindings(project_id);
                """)
        except Exception as e:
            _log.warning("Failed to create project tables: %s", e)

    # Project CRUD

    @staticmethod
    def create_project(project: Project) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT INTO connectivity_projects (project_id, name, description, status, owner, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project.project_id, project.name, project.description, project.status, project.owner, project.created_at, project.updated_at),
                )
            return True
        except Exception as e:
            _log.error("Failed to create project: %s", e)
            return False

    @staticmethod
    def get_project(project_id: str) -> dict[str, Any] | None:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute("SELECT * FROM connectivity_projects WHERE project_id = ?", (project_id,)).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    @staticmethod
    def list_projects() -> list[dict[str, Any]]:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute("SELECT * FROM connectivity_projects ORDER BY created_at DESC").fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def update_project_status(project_id: str, status: str) -> bool:
        try:
            with _connect() as db:
                db.execute("UPDATE connectivity_projects SET status = ?, updated_at = ? WHERE project_id = ?",
                           (status, _time.utc_now(), project_id))
            return True
        except Exception:
            return False

    # Goal CRUD

    @staticmethod
    def save_goal(goal: ProjectGoal) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO connectivity_goals (goal_id, project_id, description, success_criteria, priority, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (goal.goal_id, goal.project_id, goal.description,
                     json.dumps(list(goal.success_criteria)), goal.priority, goal.status),
                )
            return True
        except Exception:
            return False

    # Milestone CRUD

    @staticmethod
    def save_milestone(ms: Milestone) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO connectivity_milestones (milestone_id, project_id, goal_id, description, target_date, status, work_item_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ms.milestone_id, ms.project_id, ms.goal_id, ms.description,
                     ms.target_date, ms.status, json.dumps(list(ms.work_item_ids))),
                )
            return True
        except Exception:
            return False

    @staticmethod
    def list_milestones(project_id: str) -> list[dict[str, Any]]:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_milestones WHERE project_id = ? ORDER BY milestone_id", (project_id,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # WorkPlan CRUD

    @staticmethod
    def save_plan(plan: WorkPlan) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO connectivity_work_plans (plan_id, project_id, version, work_item_ids, dependency_graph, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (plan.plan_id, plan.project_id, plan.version,
                     json.dumps(list(plan.work_item_ids)), json.dumps(plan.dependency_graph),
                     plan.status, plan.created_at),
                )
            return True
        except Exception:
            return False

    @staticmethod
    def get_plan(project_id: str) -> dict[str, Any] | None:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_work_plans WHERE project_id = ? ORDER BY version DESC LIMIT 1",
                    (project_id,)
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    # WorkItem CRUD

    @staticmethod
    def save_work_item(wi: WorkItem) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT OR REPLACE INTO connectivity_work_items
                       (work_item_id, project_id, milestone_id, description, target_node,
                        required_capability, params_json, risk_level, status, depends_on,
                        task_id, budget_max_time_ms, completion_condition, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (wi.work_item_id, wi.project_id, wi.milestone_id, wi.description,
                     wi.target_node, wi.required_capability, json.dumps(wi.params),
                     wi.risk_level, wi.status, json.dumps(list(wi.depends_on)),
                     wi.task_id, wi.budget_max_time_ms, wi.completion_condition,
                     wi.created_at, wi.updated_at),
                )
            return True
        except Exception:
            return False

    @staticmethod
    def get_work_item(work_item_id: str) -> dict[str, Any] | None:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_work_items WHERE work_item_id = ?", (work_item_id,)
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    @staticmethod
    def list_work_items(project_id: str) -> list[dict[str, Any]]:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_work_items WHERE project_id = ? ORDER BY created_at",
                    (project_id,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def update_work_item_status(work_item_id: str, status: str, task_id: str = "") -> bool:
        try:
            with _connect() as db:
                updates = ["status = ?", "updated_at = ?"]
                params: list[Any] = [status, _time.utc_now()]
                if task_id:
                    updates.append("task_id = ?")
                    params.append(task_id)
                params.append(work_item_id)
                db.execute(
                    f"UPDATE connectivity_work_items SET {', '.join(updates)} WHERE work_item_id = ?",
                    params,
                )
            return True
        except Exception:
            return False

    # ExecutionAttempt

    @staticmethod
    def append_attempt(attempt: ExecutionAttempt) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO connectivity_execution_attempts
                       (attempt_id, work_item_id, task_id, node_id, status, result_json,
                        error, duration_ms, started_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (attempt.attempt_id, attempt.work_item_id, attempt.task_id,
                     attempt.node_id, attempt.status, json.dumps(attempt.result),
                     attempt.error, attempt.duration_ms, attempt.started_at,
                     attempt.completed_at),
                )
            return True
        except Exception:
            return False

    # Checkpoint

    @staticmethod
    def append_checkpoint(cp: Checkpoint) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO connectivity_checkpoints
                       (checkpoint_id, project_id, description, work_item_states,
                        artifact_hashes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (cp.checkpoint_id, cp.project_id, cp.description,
                     json.dumps(cp.work_item_states), json.dumps(list(cp.artifact_hashes)),
                     cp.created_at),
                )
            return True
        except Exception:
            return False

    @staticmethod
    def list_checkpoints(project_id: str) -> list[dict[str, Any]]:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_checkpoints WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # ContinuationDecision

    @staticmethod
    def append_continuation_decision(decision: ContinuationDecision) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT INTO connectivity_continuation_decisions (decision_id, request_id, project_id, action, resolved_work_item, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (decision.decision_id, decision.request_id, decision.project_id,
                     decision.action, decision.resolved_work_item, decision.reason,
                     decision.created_at),
                )
            return True
        except Exception:
            return False

    # ProjectEvent

    @staticmethod
    def append_event(event: ProjectEvent) -> bool:
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    "INSERT INTO connectivity_project_events (event_id, project_id, event_type, work_item_id, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (event.event_id, event.project_id, event.event_type,
                     event.work_item_id, json.dumps(event.data), event.created_at),
                )
            return True
        except Exception:
            return False

    @staticmethod
    def list_events(project_id: str) -> list[dict[str, Any]]:
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                rows = db.execute(
                    "SELECT * FROM connectivity_project_events WHERE project_id = ? ORDER BY created_at ASC",
                    (project_id,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # Runtime binding

    @staticmethod
    def save_runtime_binding(
        conversation_id: str,
        project_id: str,
        work_item_id: str,
        run_id: str,
        *,
        status: str = "running",
        checkpoint_id: str = "",
    ) -> bool:
        """Bind a conversation to its durable project execution cursor."""
        ProjectStore._ensure_tables()
        try:
            with _connect() as db:
                db.execute(
                    """INSERT INTO connectivity_runtime_bindings
                       (conversation_id, project_id, work_item_id, run_id,
                        status, checkpoint_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(conversation_id) DO UPDATE SET
                         project_id = excluded.project_id,
                         work_item_id = excluded.work_item_id,
                         run_id = excluded.run_id,
                         status = excluded.status,
                         checkpoint_id = excluded.checkpoint_id,
                         updated_at = excluded.updated_at""",
                    (
                        conversation_id,
                        project_id,
                        work_item_id,
                        run_id,
                        status,
                        checkpoint_id,
                        _time.utc_now(),
                    ),
                )
            return True
        except Exception as exc:
            _log.error("Failed to save runtime binding: %s", exc)
            return False

    @staticmethod
    def get_runtime_binding(conversation_id: str) -> dict[str, Any] | None:
        """Return the latest durable execution cursor for a conversation."""
        ProjectStore._ensure_tables()
        try:
            with _connect(readonly=True) as db:
                row = db.execute(
                    "SELECT * FROM connectivity_runtime_bindings WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None



