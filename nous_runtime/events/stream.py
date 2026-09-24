# -*- coding: utf-8 -*-
"""
EventStream — manages event emission, persistence, and retrieval.

Features:
- Monotonic per-run sequence numbers
- Idempotent event consumption
- Reconnect from last acknowledged sequence
- Bounded in-memory buffers
- Persistent event history via JSONL
- Pagination support
- Event retention policy
- Redaction before persistence
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import re
import threading
from pathlib import Path
from typing import Any, Iterator

from nous_runtime.events.models import RunEvent, RunRecord, RunState
from nous_runtime.locking import file_lock, runtime_locks

_log = logging.getLogger("nous.events.stream")

# Default: keep the last 10,000 events in memory per run
DEFAULT_BUFFER_SIZE = 10_000
# Default: maximum events to persist per run
DEFAULT_MAX_PERSISTED = 100_000
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DEFAULT_MAX_LISTENERS = 64
DEFAULT_CHUNK_BYTES = 16_384
_COALESCIBLE_EVENTS = {"step.progress", "run.heartbeat", "stream.fragment"}
_PROTECTED_PREFIXES = (
    "run.",
    "approval.",
    "security.",
    "artifact.",
    "network.",
    "claim.",
    "work.",
    "error.",
)
_PROTECTED_EVENTS = {"command.proposed", "file.changed", "test.completed"}


class EventStreamError(RuntimeError):
    """Raised when event validation or durable persistence fails."""


class EventStream:
    """Stream manager for run events with persistence and pagination."""

    def __init__(
        self,
        workspace_root: str = "",
        *,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        max_persisted: int = DEFAULT_MAX_PERSISTED,
        max_listeners_per_run: int = DEFAULT_MAX_LISTENERS,
        slow_consumer_seconds: float = 0.25,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    ):
        self._workspace = workspace_root or os.getcwd()
        self._buffer_size = max(1, int(buffer_size))
        self._max_persisted = max(1, int(max_persisted))
        self._lock = threading.RLock()
        # Per-run in-memory buffers: run_id -> list[RunEvent]
        self._buffers: dict[str, list[RunEvent]] = {}
        self._max_listeners_per_run = max(1, int(max_listeners_per_run))
        self._slow_consumer_seconds = max(0.0, float(slow_consumer_seconds))
        self._chunk_bytes = max(256, int(chunk_bytes))
        # Per-run sequence counters
        self._sequences: dict[str, int] = {}
        # Run records
        self._runs: dict[str, RunRecord] = {}
        # Live listeners: run_id -> list[callable]
        self._listeners: dict[str, list[callable]] = {}
        self._run_locks: dict[str, threading.Lock] = {}
        self._metrics: dict[str, float | int] = {
            "emitted_events": 0,
            "coalesced_progress_count": 0,
            "listener_failure_count": 0,
            "slow_consumer_count": 0,
            "persistence_latency_ms_total": 0.0,
            "persistence_writes": 0,
            "replay_requests": 0,
            "replay_lag_events": 0,
            "streaming_reads": 0,
            "streamed_events": 0,
        }

    # Event Emission

    def emit(self, event: RunEvent) -> RunEvent:
        """Persist an event with a monotonic per-run sequence."""
        with self._lock:
            run_lock = self._run_locks.setdefault(event.run_id, threading.Lock())
        run_id = event.run_id
        self._validate_run_id(run_id)
        started = time.perf_counter()
        with (
            run_lock,
            runtime_locks.acquire(f"run:{run_id}", owner=event.actor, timeout=5.0),
        ):
            with file_lock(self._event_lock_path(run_id)):
                persisted_events = self._load_events_unlocked(run_id)
                duplicate = next(
                    (
                        item
                        for item in persisted_events
                        if item.event_id == event.event_id
                    ),
                    None,
                )
                if duplicate is not None:
                    return duplicate
                persisted_sequence = max(
                    (item.sequence for item in persisted_events), default=0
                )
                with self._lock:
                    in_memory_sequence = self._sequences.get(run_id, 0)
                event.sequence = max(in_memory_sequence, persisted_sequence) + 1
                self._persist_event_unlocked(event)
                self._enforce_retention_unlocked(run_id)

        with self._lock:
            self._sequences[run_id] = event.sequence
            buf = self._buffers.setdefault(run_id, [])
            if self._can_coalesce(buf, event):
                buf[-1] = event
                self._metrics["coalesced_progress_count"] += 1
            else:
                buf.append(event)
            if len(buf) > self._buffer_size:
                self._buffers[run_id] = buf[-self._buffer_size :]
            if run_id in self._runs:
                record = self._runs[run_id]
                record.last_sequence = event.sequence
                record.updated_at = event.timestamp
                payload_state = str(event.payload.get("state") or "")
                if payload_state:
                    try:
                        record.state = RunState(payload_state)
                    except ValueError:
                        pass
                    else:
                        if record.state in {
                            RunState.COMPLETED,
                            RunState.FAILED,
                            RunState.CANCELLED,
                        }:
                            record.completed_at = event.timestamp
            self._metrics["emitted_events"] += 1
            self._metrics["persistence_writes"] += 1
            self._metrics["persistence_latency_ms_total"] += (
                time.perf_counter() - started
            ) * 1000
            listeners = tuple(self._listeners.get(run_id, ()))

        for callback in listeners:
            listener_started = time.perf_counter()
            try:
                callback(event)
            except Exception:
                with self._lock:
                    self._metrics["listener_failure_count"] += 1
                _log.warning("Event listener failed for run %s", run_id, exc_info=True)
            finally:
                if time.perf_counter() - listener_started > self._slow_consumer_seconds:
                    with self._lock:
                        self._metrics["slow_consumer_count"] += 1

        return event

    def emit_chunked(self, event: RunEvent, *, field: str = "text") -> list[RunEvent]:
        """Persist bounded stdout/stderr or stream fragments."""
        text = str(event.payload.get(field) or "")
        encoded = text.encode("utf-8")
        if len(encoded) <= self._chunk_bytes:
            return [self.emit(event)]
        parts: list[str] = []
        current = ""
        for character in text:
            candidate = current + character
            if current and len(candidate.encode("utf-8")) > self._chunk_bytes:
                parts.append(current)
                current = character
            else:
                current = candidate
        if current:
            parts.append(current)
        chunks: list[RunEvent] = []
        for index, part in enumerate(parts):
            payload = dict(event.payload)
            payload[field] = part
            payload.update({"chunk_index": index, "chunk_count": len(parts)})
            chunks.append(
                self.emit(
                    RunEvent(
                        run_id=event.run_id,
                        task_id=event.task_id,
                        event_type=event.event_type,
                        actor=event.actor,
                        payload=payload,
                    )
                )
            )
        return chunks

    def emit_state_change(
        self, run_id: str, state: RunState, *, task_id: str = "", **payload
    ) -> RunEvent:
        """Emit a state-change event."""
        event_type_map = {
            RunState.CREATED: "run.created",
            RunState.RECEIVED: "work.received",
            RunState.UNDERSTANDING: "work.analysis",
            RunState.PREPARING: "work.preparing",
            RunState.PLANNING: "plan.created",
            RunState.EXECUTING: "work.progress",
            RunState.OBSERVING: "work.observing",
            RunState.REPLANNING: "work.plan.updated",
            RunState.VERIFYING: "work.verifying",
            RunState.WAITING_FOR_NODE: "run.queued",
            RunState.WAITING_FOR_APPROVAL: "approval.requested",
            RunState.WAITING_USER: "work.waiting_user",
            RunState.RUNNING: "run.started",
            RunState.PAUSED: "run.paused",
            RunState.BLOCKED: "work.blocked",
            RunState.EVALUATING: "run.completed",
            RunState.RECOVERING: "run.recovering",
            RunState.COMPLETED: "run.completed",
            RunState.FAILED: "run.failed",
            RunState.CANCELLED: "run.cancelled",
        }
        event_type = event_type_map.get(state, "run.started")
        event = RunEvent(
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            payload={"state": state.value, **payload},
        )
        # Update run record
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].state = state
                if state in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED):
                    self._runs[run_id].completed_at = event.timestamp

        return self.emit(event)

    # Run Records

    def create_run(self, run_id: str, *, task_id: str = "", **kwargs) -> RunRecord:
        """Create a new run record."""
        self._validate_run_id(run_id)
        record = RunRecord(run_id=run_id, task_id=task_id, **kwargs)
        with self._lock:
            with file_lock(self._event_lock_path(run_id)):
                persisted_sequence = self._last_persisted_sequence_unlocked(run_id)
            self._runs[run_id] = record
            self._sequences[run_id] = persisted_sequence
            self._buffers[run_id] = []
        return record

    def get_run(self, run_id: str) -> RunRecord | None:
        self._validate_run_id(run_id)
        with self._lock:
            cached = self._runs.get(run_id)
            if cached is not None:
                return cached
        events = self.load_events(run_id)
        if not events:
            return None
        record = self._reconstruct_run(run_id, events)
        with self._lock:
            self._runs[run_id] = record
            self._sequences[run_id] = record.last_sequence
            self._buffers[run_id] = events[-self._buffer_size :]
        return record

    def list_runs(self, *, limit: int = 20, offset: int = 0) -> list[RunRecord]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        events_dir = Path(self._workspace) / ".nous" / "events"
        if events_dir.is_dir():
            paths = sorted(
                events_dir.glob("*.jsonl"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for path in paths[: limit + offset]:
                try:
                    self.get_run(path.stem)
                except (EventStreamError, OSError):
                    continue
        with self._lock:
            runs = sorted(
                self._runs.values(),
                key=lambda record: record.updated_at or record.created_at,
                reverse=True,
            )
            return runs[offset : offset + limit]

    def control_run(
        self, run_id: str, action: str, *, actor: str = "terminal"
    ) -> RunRecord:
        """Apply a supported control transition to the canonical RunRecord."""
        action = action.strip().lower()
        target = {
            "pause": RunState.PAUSED,
            "resume": RunState.RUNNING,
            "cancel": RunState.CANCELLED,
        }.get(action)
        if target is None:
            raise ValueError("run action must be pause, resume, or cancel")
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        allowed = {
            "pause": {
                RunState.RUNNING,
                RunState.RECEIVED,
                RunState.UNDERSTANDING,
                RunState.PREPARING,
                RunState.PLANNING,
                RunState.EXECUTING,
                RunState.OBSERVING,
                RunState.REPLANNING,
                RunState.VERIFYING,
            },
            "resume": {RunState.PAUSED, RunState.RECOVERING},
            "cancel": {
                RunState.CREATED,
                RunState.RECEIVED,
                RunState.UNDERSTANDING,
                RunState.PREPARING,
                RunState.PLANNING,
                RunState.EXECUTING,
                RunState.OBSERVING,
                RunState.REPLANNING,
                RunState.VERIFYING,
                RunState.WAITING_FOR_NODE,
                RunState.WAITING_FOR_APPROVAL,
                RunState.WAITING_USER,
                RunState.RUNNING,
                RunState.PAUSED,
                RunState.BLOCKED,
                RunState.EVALUATING,
                RunState.RECOVERING,
            },
        }
        if record.state not in allowed[action]:
            terminal = record.state in {
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.CANCELLED,
            }
            qualifier = "terminal state" if terminal else "state"
            raise ValueError(f"cannot {action} run in {qualifier} {record.state.value}")
        self.emit_state_change(
            run_id,
            target,
            task_id=record.task_id,
            controlled_by=actor,
            control_action=action,
        )
        return self.get_run(run_id) or record

    @staticmethod
    def _reconstruct_run(run_id: str, events: list[RunEvent]) -> RunRecord:
        ordered = sorted(events, key=lambda event: (event.sequence, event.event_id))
        first = ordered[0]
        record = RunRecord(
            run_id=run_id,
            task_id=first.task_id,
            state=RunState.CREATED,
            created_at=first.timestamp,
            updated_at=ordered[-1].timestamp,
            last_sequence=max(event.sequence for event in ordered),
        )
        terminal = False
        event_states = {
            "run.created": RunState.CREATED,
            "work.received": RunState.RECEIVED,
            "work.analysis": RunState.UNDERSTANDING,
            "work.preparing": RunState.PREPARING,
            "plan.created": RunState.PLANNING,
            "work.plan.created": RunState.PLANNING,
            "work.progress": RunState.EXECUTING,
            "work.observing": RunState.OBSERVING,
            "work.plan.updated": RunState.REPLANNING,
            "work.verifying": RunState.VERIFYING,
            "work.waiting_user": RunState.WAITING_USER,
            "work.waiting_approval": RunState.WAITING_FOR_APPROVAL,
            "work.blocked": RunState.BLOCKED,
            "work.completed": RunState.COMPLETED,
            "run.queued": RunState.WAITING_FOR_NODE,
            "approval.requested": RunState.WAITING_FOR_APPROVAL,
            "run.started": RunState.RUNNING,
            "workflow.started": RunState.RUNNING,
            "runtime.request.received": RunState.RUNNING,
            "run.paused": RunState.PAUSED,
            "run.resumed": RunState.RUNNING,
            "run.recovering": RunState.RECOVERING,
            "run.completed": RunState.COMPLETED,
            "workflow.completed": RunState.COMPLETED,
            "run.failed": RunState.FAILED,
            "workflow.failed": RunState.FAILED,
            "run.cancelled": RunState.CANCELLED,
            "workflow.cancelled": RunState.CANCELLED,
        }
        for event in ordered:
            state = event_states.get(event.event_type)
            payload_state = str(event.payload.get("state") or "")
            if payload_state:
                try:
                    state = RunState(payload_state)
                except ValueError:
                    pass
            if event.event_type == "runtime.response.ready":
                status = str(event.payload.get("status") or "")
                state = (
                    RunState.COMPLETED
                    if status in {"ok", "confirmation_required"}
                    else RunState.FAILED
                )
            if state is not None and not terminal:
                record.state = state
                terminal = state in {
                    RunState.COMPLETED,
                    RunState.FAILED,
                    RunState.CANCELLED,
                }
                if terminal:
                    record.completed_at = event.timestamp
        return record

    # Event Retrieval

    def get_events(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        limit: int = 100,
    ) -> list[RunEvent]:
        """Get events for a run, optionally from a given sequence."""
        with self._lock:
            buf = self._buffers.get(run_id, [])
            if since_sequence > 0:
                buf = [e for e in buf if e.sequence > since_sequence]
            return buf[-limit:]

    def get_event_page(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Get a paginated page of events for a run."""
        with self._lock:
            buf = self._buffers.get(run_id, [])
            total = len(buf)
            total_pages = max(1, (total + page_size - 1) // page_size)
            start = (page - 1) * page_size
            end = start + page_size
            page_events = buf[start:end]
            return {
                "run_id": run_id,
                "page": page,
                "page_size": page_size,
                "total_events": total,
                "total_pages": total_pages,
                "events": [e.to_dict() for e in page_events],
            }

    # Live Listeners

    def subscribe(self, run_id: str, callback: callable) -> None:
        """Subscribe to live events for a run."""
        with self._lock:
            listeners = self._listeners.setdefault(run_id, [])
            if callback in listeners:
                return
            if len(listeners) >= self._max_listeners_per_run:
                raise EventStreamError(f"Listener limit reached for {run_id}")
            listeners.append(callback)

    def unsubscribe(self, run_id: str, callback: callable) -> None:
        """Unsubscribe from live events."""
        with self._lock:
            if run_id in self._listeners:
                self._listeners[run_id] = [
                    cb for cb in self._listeners[run_id] if cb is not callback
                ]

    # Persistence

    def _event_log_path(self, run_id: str) -> str:
        self._validate_run_id(run_id)
        return str(Path(self._workspace) / ".nous" / "events" / f"{run_id}.jsonl")

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise EventStreamError("Invalid run_id for event persistence")

    def _event_lock_path(self, run_id: str) -> Path:
        return Path(self._event_log_path(run_id)).with_suffix(".lock")

    def _event_index_path(self, run_id: str) -> Path:
        return Path(self._event_log_path(run_id)).with_suffix(".idx")

    def _snapshot_path(self, run_id: str) -> Path:
        return Path(self._event_log_path(run_id)).with_suffix(".snapshot.json")

    def _last_persisted_sequence_unlocked(self, run_id: str) -> int:
        events = self._load_events_unlocked(run_id)
        return max((event.sequence for event in events), default=0)

    def _persist_event_unlocked(self, event: RunEvent) -> None:
        try:
            path = Path(self._event_log_path(event.run_id))
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._redact(event.to_dict())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(data, ensure_ascii=False) + "\n")
                offset = handle.tell()
                handle.flush()
                os.fsync(handle.fileno())
            with self._event_index_path(event.run_id).open(
                "a", encoding="utf-8"
            ) as index:
                index.write(
                    json.dumps(
                        {
                            "sequence": event.sequence,
                            "offset": offset,
                            "event_id": event.event_id,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        except Exception as exc:
            raise EventStreamError(f"Failed to persist event: {exc}") from exc

    def load_events(self, run_id: str) -> list[RunEvent]:
        """Load persisted events while excluding concurrent partial writes."""
        self._validate_run_id(run_id)
        with file_lock(self._event_lock_path(run_id)):
            return self._load_events_unlocked(run_id)

    def _load_events_unlocked(self, run_id: str) -> list[RunEvent]:
        events: list[RunEvent] = []
        path = Path(self._event_log_path(run_id))
        if not path.is_file():
            return events
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        events.append(RunEvent.from_dict(json.loads(text)))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        _log.warning("Invalid event record skipped for run %s", run_id)
        except OSError as exc:
            raise EventStreamError(f"Failed to load events: {exc}") from exc
        return events

    def iter_persisted_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> Iterator[RunEvent]:
        """Yield bounded persisted events without materializing the event log."""
        self._validate_run_id(run_id)
        if not 1 <= limit <= 100_000:
            raise ValueError("event stream limit must be between 1 and 100000")
        path = Path(self._event_log_path(run_id))
        emitted = 0
        seen: set[str] = set()
        try:
            with file_lock(self._event_lock_path(run_id)):
                if not path.is_file():
                    return
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            event = RunEvent.from_dict(json.loads(line))
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                            continue
                        if event.sequence <= after_sequence or event.event_id in seen:
                            continue
                        seen.add(event.event_id)
                        yield event
                        emitted += 1
                        if emitted >= limit:
                            break
        except OSError as exc:
            raise EventStreamError(f"Failed to stream events: {exc}") from exc
        finally:
            with self._lock:
                self._metrics["streaming_reads"] += 1
                self._metrics["streamed_events"] += emitted

    def replay_from(self, run_id: str, last_ack_seq: int) -> list[RunEvent]:
        """Replay events from the last acknowledged sequence."""
        events = sorted(
            self.load_events(run_id),
            key=lambda item: (item.sequence, item.event_id),
        )
        seen: set[str] = set()
        replay: list[RunEvent] = []
        for event in events:
            if event.sequence <= last_ack_seq or event.event_id in seen:
                continue
            seen.add(event.event_id)
            replay.append(event)
        with self._lock:
            self._metrics["replay_requests"] += 1
            self._metrics["replay_lag_events"] = len(replay)
        return replay

    def event_index(self, run_id: str) -> list[dict[str, Any]]:
        """Return a rebuildable sequence-to-offset index."""
        self._validate_run_id(run_id)
        with file_lock(self._event_lock_path(run_id)):
            index_path = self._event_index_path(run_id)
            if not index_path.is_file():
                self._rebuild_index_unlocked(run_id)
            records: list[dict[str, Any]] = []
            if index_path.is_file():
                for line in index_path.read_text(encoding="utf-8").splitlines():
                    try:
                        records.append(dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            return sorted(
                records,
                key=lambda item: (
                    int(item.get("sequence", 0)),
                    str(item.get("event_id", "")),
                ),
            )

    def create_snapshot(
        self, run_id: str, *, upto_sequence: int | None = None
    ) -> dict[str, Any]:
        """Persist a deterministic replay snapshot."""
        events = self.load_events(run_id)
        if upto_sequence is not None:
            events = [event for event in events if event.sequence <= upto_sequence]
        canonical = [
            event.to_dict() for event in sorted(events, key=lambda item: item.sequence)
        ]
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        snapshot = {
            "run_id": run_id,
            "last_sequence": max((event.sequence for event in events), default=0),
            "event_count": len(events),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
        path = self._snapshot_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
        return snapshot

    @staticmethod
    def _can_coalesce(buffer: list[RunEvent], event: RunEvent) -> bool:
        if not buffer or event.event_type not in _COALESCIBLE_EVENTS:
            return False
        previous = buffer[-1]
        return previous.event_type == event.event_type and previous.payload.get(
            "step_id"
        ) == event.payload.get("step_id")

    @staticmethod
    def _is_retention_protected(event: RunEvent) -> bool:
        return (
            event.event_type not in _COALESCIBLE_EVENTS
            or event.event_type in _PROTECTED_EVENTS
            or event.event_type.startswith(_PROTECTED_PREFIXES)
        )

    def _enforce_retention_unlocked(self, run_id: str) -> None:
        events = self._load_events_unlocked(run_id)
        if len(events) <= self._max_persisted:
            return
        protected = [event for event in events if self._is_retention_protected(event)]
        remaining = max(self._max_persisted - len(protected), 0)
        coalescible = [
            event for event in events if not self._is_retention_protected(event)
        ]
        retained = protected + (coalescible[-remaining:] if remaining else [])
        retained.sort(key=lambda item: item.sequence)
        path = Path(self._event_log_path(run_id))
        temporary = path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for event in retained:
                handle.write(
                    json.dumps(self._redact(event.to_dict()), ensure_ascii=False) + "\n"
                )
        os.replace(temporary, path)
        self._rebuild_index_unlocked(run_id)

    def _rebuild_index_unlocked(self, run_id: str) -> None:
        log_path = Path(self._event_log_path(run_id))
        index_path = self._event_index_path(run_id)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = index_path.with_suffix(".idx.tmp")
        offset = 0
        with temporary.open("w", encoding="utf-8") as index:
            if log_path.is_file():
                for line in log_path.read_bytes().splitlines(keepends=True):
                    try:
                        event = RunEvent.from_dict(json.loads(line))
                        index.write(
                            json.dumps(
                                {
                                    "sequence": event.sequence,
                                    "offset": offset,
                                    "event_id": event.event_id,
                                },
                                sort_keys=True,
                            )
                            + "\n"
                        )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                    offset += len(line)
        os.replace(temporary, index_path)

    # Redaction

    @staticmethod
    def _redact(data: Any) -> Any:
        """Redact secret material while retaining non-secret reference metadata."""
        from nous_runtime.core.redaction import redact_sensitive_data

        return redact_sensitive_data(data)

    # Cleanup

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from memory (persisted events remain on disk)."""
        with self._lock:
            self._buffers.pop(run_id, None)
            self._sequences.pop(run_id, None)
            self._listeners.pop(run_id, None)
            self._run_locks.pop(run_id, None)
            # Keep run record for history

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            writes = int(self._metrics["persistence_writes"])
            metrics = {
                **self._metrics,
                "queue_depth": sum(len(buffer) for buffer in self._buffers.values()),
                "persistence_latency_ms": (
                    float(self._metrics["persistence_latency_ms_total"]) / writes
                    if writes
                    else 0.0
                ),
                "lock_domains": runtime_locks.snapshot(),
            }
            return {
                "metrics": metrics,
                "active_runs": len(self._runs),
                "total_buffered_events": sum(len(b) for b in self._buffers.values()),
                "runs": {
                    rid: {
                        "state": r.state.value,
                        "events": len(self._buffers.get(rid, [])),
                        "sequence": self._sequences.get(rid, 0),
                    }
                    for rid, r in self._runs.items()
                },
            }
