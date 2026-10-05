"""Durable Agent session contracts for Runtime coordination."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def session_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class AgentSessionState(str, Enum):
    """Lifecycle of a long-running intelligent participant."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    PLANNING = "PLANNING"
    SUBMITTING_WORK = "SUBMITTING_WORK"
    OBSERVING = "OBSERVING"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL_STATES = {
    AgentSessionState.COMPLETED,
    AgentSessionState.FAILED,
    AgentSessionState.CANCELLED,
}

_TRANSITIONS = {
    AgentSessionState.CREATED: {
        AgentSessionState.ACTIVE,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.ACTIVE: {
        AgentSessionState.WAITING,
        AgentSessionState.PLANNING,
        AgentSessionState.OBSERVING,
        AgentSessionState.COMPLETED,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.WAITING: {
        AgentSessionState.ACTIVE,
        AgentSessionState.OBSERVING,
        AgentSessionState.PLANNING,
        AgentSessionState.REPLANNING,
        AgentSessionState.SUBMITTING_WORK,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.PLANNING: {
        AgentSessionState.SUBMITTING_WORK,
        AgentSessionState.WAITING,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.SUBMITTING_WORK: {
        AgentSessionState.OBSERVING,
        AgentSessionState.WAITING,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.OBSERVING: {
        AgentSessionState.REPLANNING,
        AgentSessionState.WAITING,
        AgentSessionState.COMPLETED,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.REPLANNING: {
        AgentSessionState.SUBMITTING_WORK,
        AgentSessionState.WAITING,
        AgentSessionState.FAILED,
        AgentSessionState.CANCELLED,
    },
    AgentSessionState.COMPLETED: set(),
    AgentSessionState.FAILED: set(),
    AgentSessionState.CANCELLED: set(),
}


@dataclass(frozen=True)
class AgentSession:
    """Durable references that bind one agent to its governed work."""

    session_id: str
    agent_id: str
    model: str
    objective: str
    state: AgentSessionState = AgentSessionState.CREATED
    context: Mapping[str, Any] = field(default_factory=dict)
    active_work: tuple[str, ...] = ()
    pending_approvals: tuple[str, ...] = ()
    event_subscriptions: tuple[str, ...] = ()
    budget: Mapping[str, Any] = field(default_factory=dict)
    policy_scope: Mapping[str, Any] = field(default_factory=dict)
    plan_history: tuple[Mapping[str, Any], ...] = ()
    workflow_id: str = ""
    workflow_run_id: str = ""
    observations: tuple[Mapping[str, Any], ...] = ()
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=session_timestamp)
    updated_at: str = field(default_factory=session_timestamp)

    @classmethod
    def create(
        cls,
        *,
        agent_id: str,
        model: str,
        objective: str,
        context: Mapping[str, Any] | None = None,
        event_subscriptions: tuple[str, ...] = (),
        budget: Mapping[str, Any] | None = None,
        policy_scope: Mapping[str, Any] | None = None,
    ) -> "AgentSession":
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        if not objective.strip():
            raise ValueError("objective is required")
        subscriptions = tuple(
            dict.fromkeys(item.strip() for item in event_subscriptions)
        )
        if any(not item for item in subscriptions):
            raise ValueError("event subscription patterns cannot be empty")
        if len(subscriptions) > 32:
            raise ValueError("at most 32 event subscriptions are allowed")
        return cls(
            session_id=f"agent_session_{uuid.uuid4().hex}",
            agent_id=agent_id.strip(),
            model=model.strip(),
            objective=objective.strip(),
            context=dict(context or {}),
            event_subscriptions=subscriptions,
            budget=dict(budget or {}),
            policy_scope=dict(policy_scope or {}),
        )

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "model": self.model,
            "objective": self.objective,
            "state": self.state.value,
            "context": dict(self.context),
            "active_work": list(self.active_work),
            "pending_approvals": list(self.pending_approvals),
            "event_subscriptions": list(self.event_subscriptions),
            "budget": dict(self.budget),
            "policy_scope": dict(self.policy_scope),
            "plan_history": [dict(item) for item in self.plan_history],
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.workflow_run_id,
            "observations": [dict(item) for item in self.observations],
            "result": dict(self.result),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentSession":
        return cls(
            session_id=str(data.get("session_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            model=str(data.get("model") or ""),
            objective=str(data.get("objective") or ""),
            state=AgentSessionState(
                str(data.get("state") or AgentSessionState.CREATED.value)
            ),
            context=dict(data.get("context") or {}),
            active_work=tuple(str(item) for item in data.get("active_work") or ()),
            pending_approvals=tuple(
                str(item) for item in data.get("pending_approvals") or ()
            ),
            event_subscriptions=tuple(
                str(item) for item in data.get("event_subscriptions") or ()
            ),
            budget=dict(data.get("budget") or {}),
            policy_scope=dict(data.get("policy_scope") or {}),
            plan_history=tuple(dict(item) for item in data.get("plan_history") or ()),
            workflow_id=str(data.get("workflow_id") or ""),
            workflow_run_id=str(data.get("workflow_run_id") or ""),
            observations=tuple(dict(item) for item in data.get("observations") or ()),
            result=dict(data.get("result") or {}),
            error=str(data.get("error") or ""),
            created_at=str(data.get("created_at") or session_timestamp()),
            updated_at=str(data.get("updated_at") or session_timestamp()),
        )


def transition_session(
    session: AgentSession,
    target: AgentSessionState,
    *,
    error: str | None = None,
) -> AgentSession:
    if session.state is target:
        return session
    if target not in _TRANSITIONS[session.state]:
        raise ValueError(
            f"invalid Agent session transition: {session.state.value} -> {target.value}"
        )
    return replace(
        session,
        state=target,
        error=session.error if error is None else error,
        updated_at=session_timestamp(),
    )


class AgentSessionStore:
    """SQLite persistence for AgentSession without duplicating Work state."""

    def __init__(self, root: str | Path = "."):
        self.path = Path(root).resolve() / ".nous" / "agent_sessions.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._db() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_json TEXT NOT NULL
                )
                """
            )

    def save(self, session: AgentSession) -> AgentSession:
        from nous_runtime.core.redaction import redact_sensitive_data

        payload = json.dumps(redact_sensitive_data(session.to_dict()), sort_keys=True)
        with self._lock, self._db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO agent_sessions VALUES (?, ?, ?, ?)",
                (session.session_id, session.state.value, session.updated_at, payload),
            )
        return session

    def get(self, session_id: str) -> AgentSession | None:
        with self._lock, self._db() as connection:
            row = connection.execute(
                "SELECT session_json FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return AgentSession.from_dict(json.loads(row[0])) if row else None

    def list(self, *, include_terminal: bool = True) -> list[AgentSession]:
        query = "SELECT session_json FROM agent_sessions"
        params: tuple[Any, ...] = ()
        if not include_terminal:
            placeholders = ", ".join("?" for _ in _TERMINAL_STATES)
            query += f" WHERE state NOT IN ({placeholders})"
            params = tuple(state.value for state in _TERMINAL_STATES)
        query += " ORDER BY updated_at DESC"
        with self._lock, self._db() as connection:
            rows = connection.execute(query, params).fetchall()
        return [AgentSession.from_dict(json.loads(row[0])) for row in rows]

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


__all__ = [
    "AgentSession",
    "AgentSessionState",
    "AgentSessionStore",
    "session_timestamp",
    "transition_session",
]
