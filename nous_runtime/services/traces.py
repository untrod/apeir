"""Reasoning trace query service used by public runtime surfaces."""

from __future__ import annotations

from typing import Any


def get_recent_traces(limit: int = 20, outcome: str = "") -> list[dict[str, Any]]:
    """Return recent reasoning traces."""
    try:
        from nous_runtime.compat.reasoning import get_recent_traces as _get_recent_traces

        return _get_recent_traces(limit=limit, outcome=outcome)
    except Exception:
        return []


def get_session_traces(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return reasoning traces for a session."""
    try:
        from nous_runtime.compat.reasoning import get_session_traces as _get_session_traces

        return _get_session_traces(session_id=session_id, limit=limit)
    except TypeError:
        try:
            from nous_runtime.compat.reasoning import get_session_traces as _get_session_traces

            return _get_session_traces(session_id)
        except Exception:
            return []
    except Exception:
        return []


def get_trace_detail(trace_id: str) -> dict[str, Any] | None:
    """Return one reasoning trace with detail."""
    try:
        from nous_runtime.compat.reasoning import get_trace_detail as _get_trace_detail

        return _get_trace_detail(trace_id)
    except Exception:
        return None

