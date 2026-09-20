# -*- coding: utf-8 -*-
"""
Reasoning Trace — captures WHY every decision was made.

Not just WHAT happened, but:
  - Why this model was chosen
  - Why this device was used
  - Why this tool was selected
  - Why it failed
  - What alternatives were considered

Every capability execution auto-records a trace. Traces are linked
by correlation_id across a session, forming a complete decision tree.

Usage:
  from nous_core.reasoning import start_trace, add_step, end_trace

  trace_id = start_trace("model.reason", "What model to use for math?")
  add_step(trace_id, "model_choice", "Pick LLM backend",
           options=["deepseek", "claude", "gpt4"],
           chosen="deepseek", why="Lower cost, good at math, available")
  add_step(trace_id, "observation", "Request sent", result="200 OK, 1.2s")
  end_trace(trace_id, outcome="success", decision="deepseek")

  # Query all traces
  traces = get_session_traces(session_id)
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from . import ids as _ids
from . import time as _time
from .db import connect as _connect

_log = _logging.getLogger("nous_core.reasoning")


# Trace Lifecycle

def start_trace(
    capability: str,
    question: str = "",
    *,
    session_id: str = "",
    correlation_id: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """Begin a reasoning trace. Returns trace_id."""
    tid = _ids.make_id("rtr")
    now = _time.utc_now()
    corr = correlation_id or _ids.make_corr_id()

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO reasoning_traces (id, session_id, capability, question,
                   correlation_id, context, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tid, session_id, capability, question, corr,
                 _json.dumps(context or {}, ensure_ascii=False), now),
            )
        return tid
    except Exception:
        return ""


def add_step(
    trace_id: str,
    step_type: str,
    question: str,
    *,
    options: list[str] | None = None,
    chosen: str = "",
    why: str = "",
    result: str = "",
) -> str:
    """Add a reasoning step to a trace. Returns step_id."""
    sid = _ids.make_id("trs")
    now = _time.utc_now()

    # Get current max step_order
    order = 0
    try:
        with _connect(readonly=True) as db:
            row = db.execute(
                "SELECT MAX(step_order) as n FROM trace_steps WHERE trace_id = ?",
                (trace_id,)
            ).fetchone()
            if row and row["n"] is not None:
                order = row["n"] + 1
    except Exception:
        pass

    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO trace_steps (id, trace_id, step_order, step_type,
                   question, options, chosen, why, result, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, trace_id, order, step_type, question,
                 _json.dumps(options or [], ensure_ascii=False),
                 chosen, why, result, now),
            )
        return sid
    except Exception:
        return ""


def end_trace(
    trace_id: str,
    outcome: str = "success",
    decision: str = "",
    rationale: str = "",
) -> bool:
    """Complete a reasoning trace with final outcome."""
    now = _time.utc_now()
    try:
        with _connect() as db:
            # Calculate duration
            row = db.execute(
                "SELECT created_at FROM reasoning_traces WHERE id = ?", (trace_id,)
            ).fetchone()
            duration = 0
            if row:
                start = _time.parse_iso(row["created_at"])
                if start > 0:
                    import time
                    duration = int((time.time() - start) * 1000)

            db.execute(
                """UPDATE reasoning_traces SET outcome = ?, decision = ?,
                   rationale = ?, duration_ms = ? WHERE id = ?""",
                (outcome, decision, rationale, duration, trace_id),
            )
        return True
    except Exception:
        return False


# Auto-trace capability execution

def trace_capability_call(
    capability: str,
    params: dict[str, Any],
    result: dict[str, Any],
    *,
    session_id: str = "",
    correlation_id: str = "",
) -> str:
    """
    Auto-record a complete trace for a capability execution.
    Call this from the capability system after each request_capability().

    Returns the trace_id.
    """
    # Determine the key question based on capability category
    cat = capability.split(".")[0] if "." in capability else capability
    questions = {
        "model": f"Which model/provider to use for: {capability}?",
        "rag": f"What knowledge to retrieve for: {capability}?",
        "device": f"Which device to use for: {capability}?",
        "notification": "What notification to send?",
        "tool": f"Which tool to use for: {capability}?",
        "automation": "Which rule to trigger?",
    }
    question = questions.get(cat, f"How to execute: {capability}?")

    tid = start_trace(capability, question, session_id=session_id,
                      correlation_id=correlation_id,
                      context={"params_summary": str(params)[:300]})

    if not tid:
        return ""

    # Step 1: capability choice
    add_step(tid, "capability_choice",
             "Which capability for this request?",
             options=[capability],
             chosen=capability,
             why=f"Requested directly: {capability}",
             result="selected")

    # Step 2: provider info
    provider = result.get("provider", "unknown")
    add_step(tid, "provider_info",
             f"Which provider executed {capability}?",
             chosen=provider,
             why=f"Registered provider for {capability}",
             result=f"duration={result.get('duration_ms', '?')}ms")

    # Step 3: outcome
    ok = result.get("ok", False)
    if ok:
        outcome = "success"
        add_step(tid, "observation", "Execution result",
                 result=f"Success ({result.get('duration_ms', '?')}ms)")
    else:
        outcome = "failure"
        error = result.get("error", "unknown")
        add_step(tid, "error", "Why did this fail?",
                 why=error,
                 result=f"Status: {result.get('status', 'unknown')}")

    end_trace(tid, outcome=outcome,
              decision=f"Execute {capability} via {provider}",
              rationale=f"Capability '{capability}' → provider '{provider}' → {'OK' if ok else error}")

    return tid


# Query

def get_session_traces(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get all reasoning traces for a session, with steps."""
    limit = max(1, min(limit, 100))
    try:
        with _connect(readonly=True) as db:
            traces = db.execute(
                "SELECT * FROM reasoning_traces WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()

            result = []
            for t in traces:
                steps = db.execute(
                    "SELECT * FROM trace_steps WHERE trace_id = ? ORDER BY step_order",
                    (t["id"],)
                ).fetchall()
                result.append({
                    **_row_to_dict(t),
                    "steps": [_row_to_dict(s) for s in steps],
                })
            return result
    except Exception:
        return []


def get_recent_traces(limit: int = 20, outcome: str = "") -> list[dict[str, Any]]:
    """Get recent traces, optionally filtered by outcome."""
    limit = max(1, min(limit, 100))
    try:
        with _connect(readonly=True) as db:
            if outcome:
                rows = db.execute(
                    "SELECT * FROM reasoning_traces WHERE outcome = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (outcome, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM reasoning_traces ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def get_trace_detail(trace_id: str) -> dict[str, Any] | None:
    """Get full detail of a single trace including all steps."""
    try:
        with _connect(readonly=True) as db:
            trace = db.execute(
                "SELECT * FROM reasoning_traces WHERE id = ?", (trace_id,)
            ).fetchone()
            if not trace:
                return None
            steps = db.execute(
                "SELECT * FROM trace_steps WHERE trace_id = ? ORDER BY step_order",
                (trace_id,),
            ).fetchall()
            return {
                **_row_to_dict(trace),
                "steps": [_row_to_dict(s) for s in steps],
            }
    except Exception:
        return None


def get_failure_analysis(limit: int = 20) -> dict[str, Any]:
    """
    Analyze failure patterns from recent traces.
    Returns: {total_failures, top_error_reasons, affected_capabilities}
    """
    try:
        with _connect(readonly=True) as db:
            failures = db.execute(
                "SELECT capability, rationale, COUNT(*) as n FROM reasoning_traces "
                "WHERE outcome = 'failure' GROUP BY capability ORDER BY n DESC LIMIT ?",
                (limit,),
            ).fetchall()

            error_steps = db.execute(
                "SELECT ts.why, COUNT(*) as n FROM trace_steps ts "
                "JOIN reasoning_traces rt ON ts.trace_id = rt.id "
                "WHERE rt.outcome = 'failure' AND ts.step_type = 'error' "
                "GROUP BY ts.why ORDER BY n DESC LIMIT 10"
            ).fetchall()

            return {
                "total_failures": sum(f["n"] for f in failures),
                "top_failing_capabilities": [{"capability": f["capability"], "count": f["n"],
                                              "last_reason": f["rationale"][:120]}
                                             for f in failures],
                "top_error_reasons": [{"reason": e["why"][:200], "count": e["n"]}
                                     for e in error_steps],
            }
    except Exception:
        return {"total_failures": 0, "top_failing_capabilities": [], "top_error_reasons": []}


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    for field in ("context", "options"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = _json.loads(d[field])
            except Exception:
                pass
    return d
