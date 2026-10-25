"""SQLite persistence for workflow definitions, runs, and checkpoints."""

from __future__ import annotations

from contextlib import contextmanager

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.locking import file_lock
from nous_runtime.workflow.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowState,
)


def _safe_json(value, **kwargs):
    return json.dumps(redact_sensitive_data(value), **kwargs)


class WorkflowBindingError(ValueError):
    """An immutable Workflow or admitted step binding changed."""


class WorkflowConflictError(ValueError):
    """A Workflow update used a stale revision."""


def binding_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
                CREATE TABLE IF NOT EXISTS workflow_automations (
                    automation_id TEXT PRIMARY KEY, binding_json TEXT NOT NULL,
                    binding_digest TEXT NOT NULL, enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_automation_triggers (
                    automation_id TEXT NOT NULL, trigger_key TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(automation_id, trigger_key)
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
        value = self._definition_dict(definition)
        self._require_unredacted(value)
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT definition_json FROM workflow_definitions WHERE workflow_id=? AND version=?",
                (definition.workflow_id, definition.version),
            ).fetchone()
            if previous:
                if binding_digest(json.loads(previous[0])) != binding_digest(value):
                    raise WorkflowBindingError("immutable Workflow definition changed")
                return
            connection.execute(
                "INSERT INTO workflow_definitions VALUES (?, ?, ?)",
                (
                    definition.workflow_id,
                    definition.version,
                    _safe_json(value, sort_keys=True),
                ),
            )

    def list_definitions(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT workflow_id, version, definition_json FROM workflow_definitions ORDER BY workflow_id, version"
            ).fetchall()
        return [
            {
                "workflow_id": row["workflow_id"],
                "version": row["version"],
                "definition": json.loads(row["definition_json"]),
            }
            for row in rows
        ]

    def list_definition_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Bounded picker data; do not load private parameters into an index."""
        with self._db() as connection:
            rows = connection.execute(
                "SELECT workflow_id, version FROM workflow_definitions ORDER BY workflow_id, version LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_run_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Original run identity/state without repeatedly transferring results."""
        with self._db() as connection:
            rows = connection.execute(
                "SELECT run_id FROM workflow_runs ORDER BY rowid DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            summaries = []
            for row in rows:
                # Reuse the canonical persisted-identity checks. An index column
                # alone must not turn a damaged original record into success.
                run = self._require_run(connection, row["run_id"])
                summaries.append(
                    {
                        "run_id": run.run_id,
                        "workflow_id": run.workflow_id,
                        "workflow_version": run.workflow_version,
                        "state": run.state.value,
                    }
                )
            return summaries

    def get_definition(
        self, workflow_id: str, version: str
    ) -> WorkflowDefinition | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT definition_json FROM workflow_definitions WHERE workflow_id = ? AND version = ?",
                (workflow_id, version),
            ).fetchone()
        return self._definition(json.loads(row[0])) if row else None

    def create_run(self, run: WorkflowRun) -> WorkflowRun:
        self._require_unredacted(run.inputs)
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._create_run(connection, run)

    def _create_run(self, connection, run: WorkflowRun) -> WorkflowRun:
        definition = self._definition_for_run(connection, run)
        run.definition_digest = self.definition_digest(definition)
        run.inputs_digest = self.inputs_digest(run.inputs)
        if run.idempotency_key:
            row = connection.execute(
                "SELECT run_json FROM workflow_runs WHERE workflow_id = ? AND idempotency_key = ?",
                (run.workflow_id, run.idempotency_key),
            ).fetchone()
            if row:
                previous = self._run(json.loads(row[0]))
                self._validate_run(
                    previous,
                    definition=self._definition_for_run(connection, previous),
                )
                if (
                    previous.workflow_version != run.workflow_version
                    or self.inputs_digest(previous.inputs) != run.inputs_digest
                    or previous.definition_digest
                    and previous.definition_digest != run.definition_digest
                ):
                    raise WorkflowBindingError("Workflow idempotency binding changed")
                return previous
        connection.execute(
            "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, NULLIF(?, ''))",
            (
                run.run_id,
                run.workflow_id,
                run.workflow_version,
                run.state.value,
                _safe_json(self._run_dict(run), sort_keys=True),
                run.idempotency_key,
            ),
        )
        return run

    def put_automation(
        self,
        binding: dict[str, Any],
        *,
        before_publish: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Bind a trigger proposal to an immutable original Workflow definition."""
        self._require_unredacted(binding)
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_automation_definition(connection, binding)
            previous = connection.execute(
                "SELECT * FROM workflow_automations WHERE automation_id=?",
                (binding["id"],),
            ).fetchone()
            if previous and previous["binding_digest"] != binding_digest(binding):
                raise WorkflowBindingError("Automation binding changed")
            if before_publish is not None:
                before_publish()
            if previous:
                return self._automation(previous)
            connection.execute(
                "INSERT INTO workflow_automations VALUES (?, ?, ?, 1)",
                (
                    binding["id"],
                    _safe_json(binding, sort_keys=True),
                    binding_digest(binding),
                ),
            )
        return {**binding, "enabled": True}

    @staticmethod
    def _automation(row) -> dict[str, Any]:
        value = json.loads(row["binding_json"])
        if (
            value.get("id") != row["automation_id"]
            or binding_digest(value) != row["binding_digest"]
            or row["enabled"] not in (0, 1)
        ):
            raise WorkflowBindingError("Automation persisted binding changed")
        return {**value, "enabled": bool(row["enabled"])}

    def get_automation(self, automation_id: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_automations WHERE automation_id=?",
                (automation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(automation_id)
        return self._automation(row)

    def list_automations(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_automations ORDER BY rowid DESC LIMIT 500"
            ).fetchall()
        return [self._automation(row) for row in rows]

    def set_automation_enabled(
        self,
        automation_id: str,
        enabled: bool,
        *,
        before_publish: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Update configuration, optionally rechecking authority after writer admission."""
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workflow_automations WHERE automation_id=?",
                (automation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(automation_id)
            binding = self._automation(row)
            self._validate_automation_definition(connection, binding)
            # Trusted callbacks only revalidate authority. Keep the Workflow
            # writer held so another connection cannot replace the binding.
            if before_publish is not None:
                before_publish()
            connection.execute(
                "UPDATE workflow_automations SET enabled=? WHERE automation_id=?",
                (int(enabled), automation_id),
            )
        return self.get_automation(automation_id)

    def claim_automation_run(
        self,
        automation_id: str,
        trigger_key: str,
        *,
        before_publish: Callable[[], None] | None = None,
    ) -> WorkflowRun:
        """Atomically save the original run before a consumer can invoke handlers."""
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workflow_automations WHERE automation_id=?",
                (automation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(automation_id)
            binding = self._automation(row)
            self._validate_automation_definition(connection, binding)
            inputs = {
                **binding["inputs"],
                "_automation_id": automation_id,
                "_agent_id": "automation:" + automation_id,
                "_plan_id": binding["plan_id"],
                "_workflow_id": binding["workflow_id"],
            }
            previous = connection.execute(
                "SELECT run_id FROM workflow_automation_triggers WHERE automation_id=? AND trigger_key=?",
                (automation_id, trigger_key),
            ).fetchone()
            if previous:
                run = self._require_run(connection, previous[0])
                self._validate_run(
                    run, definition=self._definition_for_run(connection, run)
                )
                if (
                    run.workflow_id != binding["workflow_id"]
                    or run.workflow_version != binding["version"]
                    or self.inputs_digest(inputs) != self.inputs_digest(run.inputs)
                    or run.idempotency_key
                    != "automation:" + automation_id + ":" + binding_digest(trigger_key)
                    or run.definition_digest != binding["definition_digest"]
                    or run.inputs_digest != self.inputs_digest(inputs)
                ):
                    raise WorkflowBindingError(
                        "Automation original run binding changed"
                    )
                return run
            if not binding["enabled"]:
                raise ValueError("Automation is disabled")
            if before_publish is not None:
                before_publish()
            self._require_unredacted(inputs)
            run = self._create_run(
                connection,
                WorkflowRun(
                    binding["workflow_id"],
                    binding["version"],
                    inputs,
                    idempotency_key="automation:"
                    + automation_id
                    + ":"
                    + binding_digest(trigger_key),
                ),
            )
            connection.execute(
                "INSERT INTO workflow_automation_triggers VALUES (?, ?, ?)",
                (automation_id, trigger_key, run.run_id),
            )
            return run

    def automation_history(
        self, automation_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.get_automation(automation_id)
        with self._db() as connection:
            rows = connection.execute(
                "SELECT trigger_key, run_id FROM workflow_automation_triggers WHERE automation_id=? ORDER BY rowid DESC LIMIT ?",
                (automation_id, max(1, min(limit, 500))),
            ).fetchall()
            return [
                {
                    "trigger_key": row[0],
                    "run": self._run_dict(self._require_run(connection, row[1])),
                }
                for row in rows
            ]

    def automation_run(self, automation_id: str, run_id: str) -> WorkflowRun:
        with self._db() as connection:
            row = connection.execute(
                "SELECT trigger_key FROM workflow_automation_triggers WHERE automation_id=? AND run_id=?",
                (automation_id, run_id),
            ).fetchone()
        if row is None:
            raise WorkflowBindingError("Run is not the original Automation trigger")
        return self.claim_automation_run(automation_id, row[0])

    def _validate_automation_definition(self, connection, binding):
        definition = self._definition_for_run(
            connection, WorkflowRun(binding["workflow_id"], binding["version"], {})
        )
        if self.definition_digest(definition) != binding["definition_digest"]:
            raise WorkflowBindingError("Automation Workflow definition changed")

    def save_run(self, run: WorkflowRun) -> None:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._require_run(connection, run.run_id)
            if previous.revision != run.revision:
                raise WorkflowConflictError("Workflow revision changed")
            if (
                previous.workflow_id != run.workflow_id
                or previous.workflow_version != run.workflow_version
                or previous.idempotency_key != run.idempotency_key
                or self.inputs_digest(previous.inputs) != self.inputs_digest(run.inputs)
                or previous.definition_digest != run.definition_digest
                or previous.inputs_digest != run.inputs_digest
            ):
                raise WorkflowBindingError("Workflow run binding changed")
            self._validate_run(
                run, definition=self._definition_for_run(connection, run)
            )
            self._preserve_cancellation(connection, previous, run)
            self._write_run(connection, run)

    @contextmanager
    def execution_lock(self, run_id: str):
        """Exclude concurrent local executors while cancellation remains writable."""
        key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        with file_lock(self.path.with_name(f"workflow-run-{key}.lock")):
            yield

    def bind_run(self, run_id: str, definition: WorkflowDefinition) -> WorkflowRun:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_run(connection, run_id)
            self._validate_run(run, definition=definition)
            run.definition_digest = self.definition_digest(definition)
            run.inputs_digest = self.inputs_digest(run.inputs)
            self._write_run(connection, run)
        return run

    def update_run(
        self,
        run_id: str,
        *,
        state: WorkflowState | None = None,
        error: str | None = None,
        approved_steps: tuple[str, ...] = (),
        cancel: bool = False,
    ) -> WorkflowRun:
        """Mutate current state without overwriting parallel step evidence."""
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_run(connection, run_id)
            self._validate_run(
                run, definition=self._definition_for_run(connection, run)
            )
            if state is not None:
                run.state = state
            if error is not None:
                run.error = error
            if approved_steps:
                run.inputs["_approved_steps"] = sorted(
                    set(run.inputs.get("_approved_steps") or ()) | set(approved_steps)
                )
            if cancel:
                run.cancellation_requested = True
            self._preserve_cancellation(connection, run, run)
            self._write_run(connection, run)
        return run

    def mark_unknown(self, run_id: str, error: str) -> WorkflowRun:
        """Fence execution without repairing an invalid original binding."""
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_run(connection, run_id)
            run.state = WorkflowState.UNKNOWN
            run.error = error
            self._write_run(connection, run)
        return run

    def admit_step(
        self,
        run_id: str,
        step_id: str,
        checkpoint: dict[str, Any],
        *,
        expected_attempts: int,
    ) -> bool:
        """Commit the bound started marker before invoking a host handler."""
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_run(connection, run_id)
            self._validate_run(
                run, definition=self._definition_for_run(connection, run)
            )
            if run.cancellation_requested:
                return False
            previous = self._checkpoint(connection, run_id, step_id)
            self._validate_checkpoint(previous, checkpoint["binding_digest"])
            if int(previous.get("attempts") or 0) != expected_attempts:
                raise WorkflowConflictError("Workflow step attempts changed")
            if previous.get("status") in {"completed", "skipped"}:
                return False
            self._put_checkpoint(connection, run_id, step_id, checkpoint)
            run.step_states[step_id] = "started"
            self._write_run(connection, run)
        return True

    def finish_step(
        self,
        run_id: str,
        step_id: str,
        checkpoint: dict[str, Any],
    ) -> WorkflowRun:
        with self._db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_run(connection, run_id)
            self._validate_run(
                run, definition=self._definition_for_run(connection, run)
            )
            previous = self._checkpoint(connection, run_id, step_id)
            self._validate_checkpoint(previous, checkpoint["binding_digest"])
            self._put_checkpoint(connection, run_id, step_id, checkpoint)
            run.step_states[step_id] = str(checkpoint["status"])
            output = checkpoint.get("output")
            if output:
                run.outputs[step_id] = output
            self._preserve_cancellation(connection, run, run)
            self._write_run(connection, run)
        return run

    def get_run(self, run_id: str) -> WorkflowRun | None:
        with self._db() as connection:
            row = connection.execute(
                "SELECT run_id FROM workflow_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return self._require_run(connection, run_id) if row else None

    def history(self, workflow_id: str, *, limit: int = 50) -> list[WorkflowRun]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT run_json FROM workflow_runs WHERE workflow_id = ? ORDER BY rowid DESC LIMIT ?",
                (workflow_id, max(1, min(limit, 500))),
            ).fetchall()
        return [self._run(json.loads(row[0])) for row in rows]

    def list_runs(self, *, limit: int = 100) -> list[WorkflowRun]:
        """Bounded projection for clients; the Workflow store remains authoritative."""
        with self._db() as connection:
            rows = connection.execute(
                "SELECT run_json FROM workflow_runs ORDER BY rowid DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._run(json.loads(row[0])) for row in rows]

    def checkpoint(self, run_id: str, step_id: str, data: dict[str, Any]) -> None:
        with self._db() as connection:
            self._put_checkpoint(connection, run_id, step_id, data)

    def checkpoints(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT step_id, checkpoint_json FROM workflow_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return {row["step_id"]: json.loads(row["checkpoint_json"]) for row in rows}

    @staticmethod
    def _require_unredacted(value: Any) -> None:
        if redact_sensitive_data(value) != value:
            raise WorkflowBindingError(
                "Credential material cannot enter Workflow bindings"
            )
        binding_digest(value)

    @classmethod
    def definition_digest(cls, definition: WorkflowDefinition) -> str:
        return binding_digest(cls._definition_dict(definition))

    @staticmethod
    def inputs_digest(inputs: dict[str, Any]) -> str:
        return binding_digest(
            {key: value for key, value in inputs.items() if key != "_approved_steps"}
        )

    @classmethod
    def _validate_run(cls, run: WorkflowRun, *, definition: WorkflowDefinition) -> None:
        if (
            run.workflow_id != definition.workflow_id
            or run.workflow_version != definition.version
            or run.definition_digest
            and run.definition_digest != cls.definition_digest(definition)
            or run.inputs_digest
            and run.inputs_digest != cls.inputs_digest(run.inputs)
        ):
            raise WorkflowBindingError("Workflow run binding changed")

    @classmethod
    def _definition_for_run(cls, connection, run: WorkflowRun) -> WorkflowDefinition:
        row = connection.execute(
            "SELECT definition_json FROM workflow_definitions WHERE workflow_id=? AND version=?",
            (run.workflow_id, run.workflow_version),
        ).fetchone()
        if row is None:
            raise WorkflowBindingError("Workflow run definition is unavailable")
        return cls._definition(json.loads(row[0]))

    @classmethod
    def _require_run(cls, connection, run_id: str) -> WorkflowRun:
        row = connection.execute(
            "SELECT * FROM workflow_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = cls._run(json.loads(row["run_json"]))
        if (
            run.run_id != row["run_id"]
            or run.workflow_id != row["workflow_id"]
            or run.workflow_version != row["workflow_version"]
            or run.state.value != row["state"]
        ):
            raise WorkflowBindingError("Workflow persisted identity changed")
        return run

    @classmethod
    def _write_run(cls, connection, run: WorkflowRun) -> None:
        run.revision += 1
        connection.execute(
            "UPDATE workflow_runs SET state=?, run_json=? WHERE run_id=?",
            (
                run.state.value,
                _safe_json(cls._run_dict(run), sort_keys=True),
                run.run_id,
            ),
        )

    @staticmethod
    def _checkpoint(connection, run_id: str, step_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT checkpoint_json FROM workflow_checkpoints WHERE run_id=? AND step_id=?",
            (run_id, step_id),
        ).fetchone()
        return json.loads(row[0]) if row else {}

    @staticmethod
    def _validate_checkpoint(checkpoint: dict[str, Any], digest: str) -> None:
        if checkpoint.get("binding_digest") and checkpoint["binding_digest"] != digest:
            raise WorkflowBindingError("Workflow step binding changed")

    @staticmethod
    def _put_checkpoint(
        connection, run_id: str, step_id: str, data: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO workflow_checkpoints VALUES (?, ?, ?)",
            (run_id, step_id, _safe_json(data, sort_keys=True)),
        )

    @staticmethod
    def _preserve_cancellation(
        connection, previous: WorkflowRun, run: WorkflowRun
    ) -> None:
        if not previous.cancellation_requested:
            return
        run.cancellation_requested = True
        rows = connection.execute(
            "SELECT checkpoint_json FROM workflow_checkpoints WHERE run_id=?",
            (run.run_id,),
        ).fetchall()
        uncertain = any(
            json.loads(row[0]).get("status") in {"started", "unknown"} for row in rows
        )
        if uncertain:
            run.state = WorkflowState.UNKNOWN
            run.error = (
                run.error
                or "Cancelled admission; started effects require reconciliation"
            )
        else:
            run.state = WorkflowState.CANCELLED

    @staticmethod
    def _definition_dict(definition: WorkflowDefinition) -> dict[str, Any]:
        from nous_runtime.workflow.models import definition_to_dict

        return definition_to_dict(definition)

    @staticmethod
    def _definition(data: dict[str, Any]) -> WorkflowDefinition:
        from nous_runtime.workflow.models import definition_from_dict

        return definition_from_dict(data)

    @staticmethod
    def _run_dict(run: WorkflowRun) -> dict[str, Any]:
        return {
            "workflow_id": run.workflow_id,
            "workflow_version": run.workflow_version,
            "inputs": run.inputs,
            "run_id": run.run_id,
            "state": run.state.value,
            "step_states": run.step_states,
            "outputs": run.outputs,
            "error": run.error,
            "idempotency_key": run.idempotency_key,
            "cancellation_requested": run.cancellation_requested,
            "definition_digest": run.definition_digest,
            "inputs_digest": run.inputs_digest,
            "revision": run.revision,
        }

    @staticmethod
    def _run(data: dict[str, Any]) -> WorkflowRun:
        return WorkflowRun(
            str(data["workflow_id"]),
            str(data["workflow_version"]),
            dict(data.get("inputs") or {}),
            str(data["run_id"]),
            WorkflowState(str(data.get("state") or "pending")),
            dict(data.get("step_states") or {}),
            dict(data.get("outputs") or {}),
            str(data.get("error") or ""),
            str(data.get("idempotency_key") or ""),
            bool(data.get("cancellation_requested", False)),
            str(data.get("definition_digest") or ""),
            str(data.get("inputs_digest") or ""),
            int(data.get("revision") or 0),
        )
