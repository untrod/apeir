# -*- coding: utf-8 -*-
"""
Observability: Trace ID propagation, execution timeline, failure model.

Every execution gets a trace_id that follows the complete chain:
    Goal → Plan → Task → Dispatch → Execute → Evaluate

Trace IDs are propagated through all subsystems for correlation.

Usage:
    from nous_runtime.kernel.tracing import TraceContext, trace_id

    with TraceContext(goal_id="goal_001") as ctx:
        # All operations in this block share ctx.trace_id
        execute_capability("model.reason", prompt="...")
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

log = logging.getLogger("nous.tracing")

# Thread-local trace context
_tls = threading.local()


# Trace Context

@dataclass
class TraceContext:
    """Propagated trace information for a single execution chain."""
    trace_id: str = ""
    goal_id: str = ""
    plan_id: str = ""
    task_id: str = ""
    started_at: str = ""
    parent_trace_id: str = ""

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = f"trace_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        if not self.started_at:
            self.started_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self._previous = None

    def __enter__(self) -> "TraceContext":
        self._previous = getattr(_tls, "trace_context", None)
        _tls.trace_context = self
        return self

    def __exit__(self, *args):
        _tls.trace_context = self._previous


class TraceContextManager:
    """Context manager for trace propagation."""

    def __init__(self, **kwargs):
        self.ctx = TraceContext(**kwargs)
        self._previous = None

    def __enter__(self) -> TraceContext:
        self._previous = getattr(_tls, "trace_context", None)
        _tls.trace_context = self.ctx
        return self.ctx

    def __exit__(self, *args):
        _tls.trace_context = self._previous


def get_trace_context() -> TraceContext | None:
    """Get the current trace context for this thread."""
    return getattr(_tls, "trace_context", None)


def get_trace_id() -> str:
    """Get the current trace ID, or generate one."""
    ctx = get_trace_context()
    if ctx:
        return ctx.trace_id
    return f"trace_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


# Execution Timeline

@dataclass
class TimelineEntry:
    """A single step in the execution timeline."""
    step: int
    trace_id: str
    event: str                      # "planning", "dispatching", "executing", "evaluating", "completed", "failed"
    capability_id: str = ""
    provider_id: str = ""
    duration_ms: float = 0.0
    ok: bool | None = None
    error_code: str = ""
    detail: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ExecutionTimeline:
    """Records the step-by-step execution timeline for a trace."""

    def __init__(self, trace_id: str = ""):
        self.trace_id = trace_id or get_trace_id()
        self.entries: list[TimelineEntry] = []
        self._step = 0
        self._start = time.time()

    def add(self, step_name: str, **kwargs) -> TimelineEntry:
        event = str(kwargs.pop("event", step_name))
        if event != step_name and "detail" not in kwargs:
            kwargs["detail"] = step_name
        self._step += 1
        entry = TimelineEntry(
            step=self._step,
            trace_id=self.trace_id,
            event=event,
            **kwargs,
        )
        self.entries.append(entry)
        log.debug("Timeline [%s] step %d: %s", self.trace_id[:16], self._step, event)
        return entry

    def total_duration_ms(self) -> float:
        return (time.time() - self._start) * 1000

    def summary(self) -> dict[str, Any]:
        if not self.entries:
            return {"trace_id": self.trace_id, "steps": 0}
        failures = [e for e in self.entries if e.ok is False]
        successes = [e for e in self.entries if e.ok is True]
        return {
            "trace_id": self.trace_id,
            "steps": len(self.entries),
            "successes": len(successes),
            "failures": len(failures),
            "total_duration_ms": round(self.total_duration_ms(), 1),
            "events": [e.event for e in self.entries],
        }


# Failure Model

NOUS_ERROR_CODES = {
    "NOUS_OK": "Success",
    "NOUS_INVALID_REQUEST": "Malformed request",
    "NOUS_CAPABILITY_NOT_FOUND": "Capability not registered",
    "NOUS_CAPABILITY_DISABLED": "Capability is disabled",
    "NOUS_PROVIDER_NOT_FOUND": "No provider for capability",
    "NOUS_PROVIDER_UNAVAILABLE": "Provider is down or degraded",
    "NOUS_PROVIDER_TIMEOUT": "Provider did not respond in time",
    "NOUS_PERMISSION_DENIED": "Insufficient permissions",
    "NOUS_POLICY_REJECTED": "Policy blocked the request",
    "NOUS_AUTHENTICATION_FAILED": "Invalid credentials",
    "NOUS_RATE_LIMITED": "Too many requests",
    "NOUS_DEPENDENCY_FAILED": "Required capability failed",
    "NOUS_EXECUTION_FAILED": "Execution completed with errors",
    "NOUS_TIMEOUT": "Execution exceeded time limit",
    "NOUS_RECOVERY_FAILED": "Recovery unsuccessful",
    "NOUS_INTERNAL_ERROR": "Unexpected internal error",
}


def error_description(code: str) -> str:
    """Get the human-readable description for an error code."""
    return NOUS_ERROR_CODES.get(code, "Unknown error")


def is_retryable(code: str) -> bool:
    """Check if an error code is retryable."""
    retryable = {
        "NOUS_PROVIDER_TIMEOUT",
        "NOUS_PROVIDER_UNAVAILABLE",
        "NOUS_RATE_LIMITED",
        "NOUS_DEPENDENCY_FAILED",
        "NOUS_TIMEOUT",
    }
    return code in retryable


def is_permanent(code: str) -> bool:
    """Check if an error code is permanent (requires human intervention)."""
    permanent = {
        "NOUS_PERMISSION_DENIED",
        "NOUS_POLICY_REJECTED",
        "NOUS_AUTHENTICATION_FAILED",
        "NOUS_INVALID_REQUEST",
    }
    return code in permanent
