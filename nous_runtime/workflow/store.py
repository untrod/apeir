"""SQLite persistence for workflow definitions, runs, and checkpoints."""

from __future__ import annotations

from contextlib import contextmanager

import json
import sqlite3
from pathlib import Path
from typing import Any

from nous_runtime.workflow.models import StepType, TriggerType, WorkflowDefinition, WorkflowRun, WorkflowState, WorkflowStep



class WorkflowStore:
    def __init__(self, root: str | Path = "."):
        self.path = Path(root).resolve() / ".nous" / "workflows.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    workflow_id TEXT NOT NULL, version TEXT NOT NULL,
                    definition_json TEXT NOT NULL, PRIMARY KEY(workflow_id, version)
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, workflow_version TEXT NOT NULL,
                    state TEXT NOT NULL, run_json TEXT NOT NULL, idempotency_key TEXT,
                    UNIQUE(workflow_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    run_id TEXT NOT NULL, step_id TEXT NOT NULL, checkpoint_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, step_id)
                );
                """
            )

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def put_definition(self, definition: WorkflowDefinition) -> None:
        with self._db() as connection:
            connection.execute("INSERT OR REPLACE INTO workflow_definitions VALUES (?, ?, ?)", (definition.workflow_id, definition.version, json.dumps(self._definition_dict(definition), sort_keys=True)))

    def list_definitions(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute("SELECT workflow_id, version, definition_json FROM workflow_definitions ORDER BY workflow_id, version").fetchall()
        return [{"workflow_id": row["workflow_id"], "version": row["version"], "definition": json.loads(row["definition_json"])} for row in rows]
    def get_definition(self, workflow_id: str, version: str) -> WorkflowDefinition | None:
        with self._db() as connection:
            row = connection.execute("SELECT definition_json FROM workflow_definitions WHERE workflow_id = ? AND version = ?", (workflow_id, version)).fetchone()
        return self._definition(json.loads(row[0])) if row else None

    def create_run(self, run: WorkflowRun) -> WorkflowRun:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if run.idempotency_key:
                row = connection.execute("SELECT run_json FROM workflow_runs WHERE workflow_id = ? AND idempotency_key = ?", (run.workflow_id, run.idempotency_key)).fetchone()
                if row:
                    return self._run(json.loads(row[0]))
            connection.execute("INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, NULLIF(?, ''))", (run.run_id, run.workflow_id, run.workflow_version, run.state.value, json.dumps(self._run_dict(run), sort_keys=True), run.idempotency_key))
        return run

    def save_run(self, run: WorkflowRun) -> None:
        with self._db() as connection:
            connection.execute("UPDATE workflow_runs SET state = ?, run_json = ? WHERE run_id = ?", (run.state.value, json.dumps(self._run_dict(run), sort_keys=True), run.run_id))

    def get_run(self, run_id: str) -> WorkflowRun | None:
        with self._db() as connection:
            row = connection.execute("SELECT run_json FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run(json.loads(row[0])) if row else None

    def history(self, workflow_id: str, *, limit: int = 50) -> list[WorkflowRun]:
        with self._db() as connection:
            rows = connection.execute("SELECT run_json FROM workflow_runs WHERE workflow_id = ? ORDER BY rowid DESC LIMIT ?", (workflow_id, max(1, min(limit, 500)))).fetchall()
        return [self._run(json.loads(row[0])) for row in rows]

    def checkpoint(self, run_id: str, step_id: str, data: dict[str, Any]) -> None:
        with self._db() as connection:
            connection.execute("INSERT OR REPLACE INTO workflow_checkpoints VALUES (?, ?, ?)", (run_id, step_id, json.dumps(data, sort_keys=True)))

    def checkpoints(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute("SELECT step_id, checkpoint_json FROM workflow_checkpoints WHERE run_id = ?", (run_id,)).fetchall()
        return {row["step_id"]: json.loads(row["checkpoint_json"]) for row in rows}

    @staticmethod
    def _definition_dict(definition: WorkflowDefinition) -> dict[str, Any]:
        return {"workflow_id": definition.workflow_id, "version": definition.version, "trigger": definition.trigger.value, "steps": [{"step_id": step.step_id, "step_type": step.step_type.value, "action": step.action, "depends_on": list(step.depends_on), "condition": step.condition, "retries": step.retries, "timeout_seconds": step.timeout_seconds, "approval_required": step.approval_required, "compensation": step.compensation, "params": step.params} for step in definition.steps], "inputs_schema": definition.inputs_schema, "outputs_schema": definition.outputs_schema, "audit_metadata": definition.audit_metadata}

    @staticmethod
    def _definition(data: dict[str, Any]) -> WorkflowDefinition:
        return WorkflowDefinition(str(data["workflow_id"]), str(data["version"]), TriggerType(str(data["trigger"])), tuple(WorkflowStep(str(item["step_id"]), StepType(str(item["step_type"])), str(item.get("action") or ""), tuple(item.get("depends_on") or ()), str(item.get("condition") or ""), int(item.get("retries") or 0), float(item.get("timeout_seconds") or 60), bool(item.get("approval_required", False)), str(item.get("compensation") or ""), dict(item.get("params") or {})) for item in data.get("steps") or ()), dict(data.get("inputs_schema") or {}), dict(data.get("outputs_schema") or {}), dict(data.get("audit_metadata") or {}))

    @staticmethod
    def _run_dict(run: WorkflowRun) -> dict[str, Any]:
        return {"workflow_id": run.workflow_id, "workflow_version": run.workflow_version, "inputs": run.inputs, "run_id": run.run_id, "state": run.state.value, "step_states": run.step_states, "outputs": run.outputs, "error": run.error, "idempotency_key": run.idempotency_key, "cancellation_requested": run.cancellation_requested}

    @staticmethod
    def _run(data: dict[str, Any]) -> WorkflowRun:
        return WorkflowRun(str(data["workflow_id"]), str(data["workflow_version"]), dict(data.get("inputs") or {}), str(data["run_id"]), WorkflowState(str(data.get("state") or "pending")), dict(data.get("step_states") or {}), dict(data.get("outputs") or {}), str(data.get("error") or ""), str(data.get("idempotency_key") or ""), bool(data.get("cancellation_requested", False)))