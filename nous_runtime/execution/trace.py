# -*- coding: utf-8 -*-
"""ExecutionTrace — full lifecycle tracing for every execution.

Records the complete chain:
  Session → Task → Plan → Capability → Node → Model → Result → Verification

Each trace is an immutable, append-only record stored in SQLite with:
- Timeline queries for UI rendering
- Span-based hierarchical view (parent/child spans)
- Verification linkage (which verifications ran, what passed/failed)
- Cross-trace correlation via session_id and task_id
"""

from __future__ import annotations

import atexit
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from nous_runtime.schema_registry import EXECUTION_TRACE_SCHEMA_VERSION as SCHEMA_VERSION

_log = logging.getLogger("nous.trace")



# Span model


class SpanKind(str, Enum):
    """Type of execution span."""
    SESSION = "session"
    TASK = "task"
    PLAN = "plan"
    CAPABILITY = "capability"
    NODE = "node"
    MODEL = "model"
    VERIFICATION = "verification"
    SANDBOX = "sandbox"
    ARTIFACT = "artifact"
    APPROVAL = "approval"


class SpanStatus(str, Enum):
    """Execution status of a span."""
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class TraceSpan:
    """A single execution span within a trace."""
    span_id: str = ""
    trace_id: str = ""
    parent_span_id: str = ""
    span_kind: SpanKind = SpanKind.TASK
    span_name: str = ""
    status: SpanStatus = SpanStatus.STARTED

    # Timing
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0

    # Context
    session_id: str = ""
    task_id: str = ""
    plan_id: str = ""
    capability_id: str = ""
    node_id: str = ""
    model_id: str = ""
    provider_id: str = ""

    # Result
    result_summary: str = ""
    result_detail: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    error_category: str = ""

    # Metrics
    token_usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    retry_count: int = 0
    fallback_used: bool = False

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Schema
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "span_kind": self.span_kind.value,
            "span_name": self.span_name,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "capability_id": self.capability_id,
            "node_id": self.node_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "result_summary": self.result_summary,
            "result_detail": self.result_detail,
            "error_message": self.error_message,
            "error_category": self.error_category,
            "token_usage": self.token_usage,
            "cost_usd": self.cost_usd,
            "retry_count": self.retry_count,
            "fallback_used": self.fallback_used,
            "tags": self.tags,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceSpan":
        return cls(
            span_id=str(data.get("span_id", "")),
            trace_id=str(data.get("trace_id", "")),
            parent_span_id=str(data.get("parent_span_id", "")),
            span_kind=SpanKind(str(data.get("span_kind", "task"))),
            span_name=str(data.get("span_name", "")),
            status=SpanStatus(str(data.get("status", "started"))),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            duration_ms=float(data.get("duration_ms", 0)),
            session_id=str(data.get("session_id", "")),
            task_id=str(data.get("task_id", "")),
            plan_id=str(data.get("plan_id", "")),
            capability_id=str(data.get("capability_id", "")),
            node_id=str(data.get("node_id", "")),
            model_id=str(data.get("model_id", "")),
            provider_id=str(data.get("provider_id", "")),
            result_summary=str(data.get("result_summary", "")),
            result_detail=dict(data.get("result_detail", {})),
            error_message=str(data.get("error_message", "")),
            error_category=str(data.get("error_category", "")),
            token_usage=dict(data.get("token_usage", {})),
            cost_usd=float(data.get("cost_usd", 0)),
            retry_count=int(data.get("retry_count", 0)),
            fallback_used=bool(data.get("fallback_used", False)),
            tags=dict(data.get("tags", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ExecutionTrace:
    """A complete execution trace spanning Session → Task → Plan → ... → Verification."""
    trace_id: str = ""
    session_id: str = ""
    task_id: str = ""
    root_span_id: str = ""
    spans: list[TraceSpan] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = SCHEMA_VERSION

    @property
    def total_duration_ms(self) -> float:
        root = self.root_span
        return root.duration_ms if root else 0.0

    @property
    def root_span(self) -> TraceSpan | None:
        for s in self.spans:
            if s.span_id == self.root_span_id:
                return s
        return None

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def has_errors(self) -> bool:
        return any(
            s.status == SpanStatus.FAILED for s in self.spans
        )

    def get_spans_by_kind(self, kind: SpanKind) -> list[TraceSpan]:
        return [s for s in self.spans if s.span_kind == kind]

    def get_child_spans(self, parent_span_id: str) -> list[TraceSpan]:
        return [s for s in self.spans if s.parent_span_id == parent_span_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "root_span_id": self.root_span_id,
            "spans": [s.to_dict() for s in self.spans],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "total_duration_ms": self.total_duration_ms,
            "span_count": self.span_count,
            "has_errors": self.has_errors,
        }



# ExecutionTracer — service


class ExecutionTracer:
    """Service for recording and querying execution traces.

    Stores spans in SQLite for persistence across sessions.
    Supports hierarchical span trees and timeline queries.
    """

    def __init__(self, workspace_root: str = ""):
        self._workspace = workspace_root or "."
        self._db_path = Path(self._workspace) / ".nous" / "execution_traces.db"
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._active_traces: dict[str, ExecutionTrace] = {}
        self._active_spans: dict[str, TraceSpan] = {}
        self._ensure_db()

    # Trace lifecycle

    def create_trace(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        trace_id: str = "",
    ) -> ExecutionTrace:
        """Create a new execution trace."""
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:16]}"
        now = _utc_now()

        root_span = TraceSpan(
            span_id=f"span_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            span_kind=SpanKind.TASK,
            span_name="Root",
            status=SpanStatus.STARTED,
            started_at=now,
            session_id=session_id,
            task_id=task_id,
        )

        trace = ExecutionTrace(
            trace_id=trace_id,
            session_id=session_id,
            task_id=task_id,
            root_span_id=root_span.span_id,
            spans=[root_span],
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._active_traces[trace_id] = trace
            self._active_spans[root_span.span_id] = root_span

        self._persist_span(root_span)
        _log.debug("Created trace %s (session=%s, task=%s)", trace_id, session_id, task_id)
        return trace

    # Span lifecycle

    def start_span(
        self,
        trace_id: str,
        span_kind: SpanKind,
        span_name: str,
        *,
        parent_span_id: str = "",
        session_id: str = "",
        task_id: str = "",
        plan_id: str = "",
        capability_id: str = "",
        node_id: str = "",
        model_id: str = "",
        provider_id: str = "",
        tags: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """Start a new span within a trace."""
        trace = self._active_traces.get(trace_id)
        if trace is None:
            trace = self._load_trace(trace_id)
            if trace is not None:
                with self._lock:
                    self._active_traces[trace_id] = trace

        parent = parent_span_id or (trace.root_span_id if trace else "")

        span = TraceSpan(
            span_id=f"span_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            parent_span_id=parent,
            span_kind=span_kind,
            span_name=span_name,
            status=SpanStatus.STARTED,
            started_at=_utc_now(),
            session_id=session_id or (trace.session_id if trace else ""),
            task_id=task_id or (trace.task_id if trace else ""),
            plan_id=plan_id,
            capability_id=capability_id,
            node_id=node_id,
            model_id=model_id,
            provider_id=provider_id,
            tags=dict(tags or {}),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._active_spans[span.span_id] = span
            if trace is not None:
                trace.spans.append(span)
                trace.updated_at = span.started_at

        self._persist_span(span)
        return span

    def complete_span(
        self,
        span_id: str,
        *,
        status: SpanStatus = SpanStatus.COMPLETED,
        result_summary: str = "",
        result_detail: dict[str, Any] | None = None,
        error_message: str = "",
        error_category: str = "",
        token_usage: dict[str, int] | None = None,
        cost_usd: float = 0.0,
        retry_count: int = 0,
        fallback_used: bool = False,
    ) -> TraceSpan | None:
        """Mark a span as completed (or failed/cancelled)."""
        span = self._active_spans.get(span_id)
        if span is None:
            return None

        now = _utc_now()
        span.status = status
        span.finished_at = now
        span.result_summary = result_summary
        span.result_detail = dict(result_detail or {})
        span.error_message = error_message
        span.error_category = error_category
        span.token_usage = dict(token_usage or {})
        span.cost_usd = cost_usd
        span.retry_count = retry_count
        span.fallback_used = fallback_used

        # Calculate duration
        try:
            started = _parse_timestamp(span.started_at)
            finished = _parse_timestamp(now)
            span.duration_ms = (finished - started) * 1000
        except Exception:
            span.duration_ms = 0.0

        self._update_span(span)
        return span

    def fail_span(
        self,
        span_id: str,
        error_message: str,
        *,
        error_category: str = "unknown",
    ) -> TraceSpan | None:
        """Convenience method to fail a span."""
        return self.complete_span(
            span_id,
            status=SpanStatus.FAILED,
            error_message=error_message,
            error_category=error_category,
        )

    # Query

    def get_trace(self, trace_id: str) -> ExecutionTrace | None:
        """Get a complete trace by ID."""
        cached = self._active_traces.get(trace_id)
        if cached is not None:
            return cached
        return self._load_trace(trace_id)

    def get_span(self, span_id: str) -> TraceSpan | None:
        """Get a span by ID."""
        cached = self._active_spans.get(span_id)
        if cached is not None:
            return cached
        return self._load_span(span_id)

    def list_recent_traces(
        self,
        *,
        limit: int = 20,
        session_id: str = "",
        task_id: str = "",
    ) -> list[dict[str, Any]]:
        """List recent traces, optionally filtered."""
        self._ensure_db()
        if self._db is None:
            return []

        conditions = []
        params: list[Any] = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = self._db.execute(
                f"SELECT DISTINCT trace_id, session_id, task_id, root_span_id, "
                f"created_at, updated_at FROM trace_spans{where} "
                f"ORDER BY updated_at DESC LIMIT ?",
                params + [max(1, min(int(limit), 100))],
            ).fetchall()

            return [
                {
                    "trace_id": r[0], "session_id": r[1], "task_id": r[2],
                    "root_span_id": r[3], "created_at": r[4], "updated_at": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            _log.warning("Failed to list traces: %s", e)
            return []

    def get_trace_timeline(
        self,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        """Get all spans for a trace in chronological order (timeline view)."""
        trace = self.get_trace(trace_id)
        if trace is not None:
            spans = sorted(trace.spans, key=lambda s: s.started_at)
            return [s.to_dict() for s in spans]

        # Load from DB
        self._ensure_db()
        if self._db is None:
            return []

        try:
            rows = self._db.execute(
                "SELECT payload FROM trace_spans WHERE trace_id = ? "
                "ORDER BY started_at",
                (trace_id,),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        except Exception as e:
            _log.warning("Failed to load timeline: %s", e)
            return []

    def get_trace_statistics(self) -> dict[str, Any]:
        """Return aggregate statistics across all traces."""
        self._ensure_db()
        if self._db is None:
            return {"total_traces": len(self._active_traces)}

        try:
            total = self._db.execute(
                "SELECT COUNT(DISTINCT trace_id) FROM trace_spans"
            ).fetchone()

            by_kind = self._db.execute(
                "SELECT span_kind, COUNT(*) FROM trace_spans GROUP BY span_kind"
            ).fetchall()

            by_status = self._db.execute(
                "SELECT status, COUNT(*) FROM trace_spans GROUP BY status"
            ).fetchall()

            avg_duration = self._db.execute(
                "SELECT AVG(duration_ms) FROM trace_spans WHERE duration_ms > 0"
            ).fetchone()

            total_cost = self._db.execute(
                "SELECT SUM(cost_usd) FROM trace_spans"
            ).fetchone()

            return {
                "total_traces": int(total[0]) if total else 0,
                "spans_by_kind": {r[0]: r[1] for r in by_kind},
                "spans_by_status": {r[0]: r[1] for r in by_status},
                "avg_span_duration_ms": round(float(avg_duration[0] or 0), 2),
                "total_cost_usd": round(float(total_cost[0] or 0), 6),
            }
        except Exception as e:
            _log.warning("Failed to get trace statistics: %s", e)
            return {}

    def shutdown(self) -> None:
        """Close the database connection."""
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None

    # Internal

    def _ensure_db(self) -> None:
        if self._db is not None:
            return
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=5.0,
            )
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS trace_spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT NOT NULL DEFAULT '',
                    span_kind TEXT NOT NULL,
                    span_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'started',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    duration_ms REAL NOT NULL DEFAULT 0,
                    session_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    plan_id TEXT NOT NULL DEFAULT '',
                    capability_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    model_id TEXT NOT NULL DEFAULT '',
                    provider_id TEXT NOT NULL DEFAULT '',
                    result_summary TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    error_category TEXT NOT NULL DEFAULT '',
                    token_usage TEXT NOT NULL DEFAULT '{}',
                    cost_usd REAL NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
                    schema_version TEXT NOT NULL DEFAULT '1.0.0'
                )
            """)
            for idx_col in ("trace_id", "session_id", "task_id", "span_kind",
                            "status", "started_at", "parent_span_id"):
                try:
                    self._db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_trace_{idx_col} "
                        f"ON trace_spans({idx_col})"
                    )
                except Exception:
                    pass
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to init trace DB: %s", e)
            self._db = None

    def _persist_span(self, span: TraceSpan) -> None:
        self._ensure_db()
        if self._db is None:
            return
        try:
            payload = json.dumps(span.to_dict(), ensure_ascii=False)
            self._db.execute(
                """INSERT OR REPLACE INTO trace_spans
                   (span_id, trace_id, parent_span_id, span_kind, span_name,
                    status, started_at, finished_at, duration_ms,
                    session_id, task_id, plan_id, capability_id,
                    node_id, model_id, provider_id,
                    result_summary, error_message, error_category,
                    token_usage, cost_usd, retry_count, fallback_used,
                    tags, metadata, payload, schema_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    span.span_id, span.trace_id, span.parent_span_id,
                    span.span_kind.value, span.span_name,
                    span.status.value, span.started_at, span.finished_at,
                    span.duration_ms,
                    span.session_id, span.task_id, span.plan_id,
                    span.capability_id, span.node_id, span.model_id,
                    span.provider_id,
                    span.result_summary, span.error_message, span.error_category,
                    json.dumps(span.token_usage), span.cost_usd,
                    span.retry_count, int(span.fallback_used),
                    json.dumps(span.tags), json.dumps(span.metadata),
                    payload, span.schema_version,
                ),
            )
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to persist span %s: %s", span.span_id, e)

    def _update_span(self, span: TraceSpan) -> None:
        self._ensure_db()
        if self._db is None:
            return
        try:
            payload = json.dumps(span.to_dict(), ensure_ascii=False)
            self._db.execute(
                """UPDATE trace_spans SET
                   status=?, finished_at=?, duration_ms=?,
                   result_summary=?, error_message=?, error_category=?,
                   token_usage=?, cost_usd=?, retry_count=?, fallback_used=?,
                   payload=?
                   WHERE span_id=?""",
                (
                    span.status.value, span.finished_at, span.duration_ms,
                    span.result_summary, span.error_message, span.error_category,
                    json.dumps(span.token_usage), span.cost_usd,
                    span.retry_count, int(span.fallback_used),
                    payload, span.span_id,
                ),
            )
            self._db.commit()
        except Exception as e:
            _log.warning("Failed to update span %s: %s", span.span_id, e)

    def _load_trace(self, trace_id: str) -> ExecutionTrace | None:
        self._ensure_db()
        if self._db is None:
            return None
        try:
            rows = self._db.execute(
                "SELECT payload FROM trace_spans WHERE trace_id = ? "
                "ORDER BY started_at",
                (trace_id,),
            ).fetchall()
            if not rows:
                return None

            spans = [
                TraceSpan.from_dict(json.loads(r[0]))
                for r in rows
            ]
            first_span = spans[0] if spans else None

            trace = ExecutionTrace(
                trace_id=trace_id,
                session_id=first_span.session_id if first_span else "",
                task_id=first_span.task_id if first_span else "",
                root_span_id=first_span.span_id if first_span else "",
                spans=spans,
                created_at=min(s.started_at for s in spans if s.started_at),
                updated_at=max(
                    s.finished_at or s.started_at
                    for s in spans
                    if s.started_at
                ),
            )
            with self._lock:
                self._active_traces[trace_id] = trace
                for s in spans:
                    self._active_spans[s.span_id] = s
            return trace
        except Exception as e:
            _log.warning("Failed to load trace %s: %s", trace_id, e)
            return None

    def _load_span(self, span_id: str) -> TraceSpan | None:
        self._ensure_db()
        if self._db is None:
            return None
        try:
            row = self._db.execute(
                "SELECT payload FROM trace_spans WHERE span_id = ?",
                (span_id,),
            ).fetchone()
            if row is None:
                return None
            span = TraceSpan.from_dict(json.loads(row[0]))
            with self._lock:
                self._active_spans[span_id] = span
            return span
        except Exception as e:
            _log.warning("Failed to load span %s: %s", span_id, e)
            return None



# Singleton


_tracer_instance: ExecutionTracer | None = None
_tracer_lock = threading.Lock()


def get_tracer(workspace_root: str = "") -> ExecutionTracer:
    global _tracer_instance
    if _tracer_instance is not None:
        return _tracer_instance
    with _tracer_lock:
        if _tracer_instance is not None:
            return _tracer_instance
        _tracer_instance = ExecutionTracer(workspace_root=workspace_root)
        return _tracer_instance


def reset_tracer() -> None:
    global _tracer_instance
    with _tracer_lock:
        if _tracer_instance is not None:
            _tracer_instance.shutdown()
        _tracer_instance = None


atexit.register(reset_tracer)


# Helpers

def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_timestamp(ts: str) -> float:
    """Parse ISO-8601 timestamp to Unix epoch seconds."""
    from datetime import datetime
    ts_clean = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_clean).timestamp()


__all__ = [
    "ExecutionTracer",
    "ExecutionTrace",
    "TraceSpan",
    "SpanKind",
    "SpanStatus",
    "get_tracer",
    "reset_tracer",
]
