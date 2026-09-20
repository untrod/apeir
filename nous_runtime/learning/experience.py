# -*- coding: utf-8 -*-
"""
Experience Engine — records and retrieves execution experience.

The Experience Engine captures every capability execution so the Runtime
can learn from history: which providers are fastest, which fail most often,
which goal strategies work best.

Records:
    - Goal ID
    - Capability ID
    - Provider ID
    - Execution result (ok/fail)
    - Score (0.0-1.0)
    - Duration (ms)
    - Error code (if failed)
    - Trace ID

Usage:
    from nous_runtime.learning.experience import record, query, stats

    record(goal_id="goal_001", capability_id="model.reason",
           provider_id="openai", ok=True, score=0.9, duration_ms=450)

    recent = query(limit=10)
    provider_stats = stats(provider_id="openai")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

log = logging.getLogger("nous.experience")

# In-memory store for v1.0.0 (SQLite in v1.1)
_experiences: list[dict[str, Any]] = []
MAX_RECORDS = 10000


@dataclass
class ExperienceRecord:
    """A single execution experience record."""
    goal_id: str = ""
    capability_id: str = ""
    provider_id: str = ""
    ok: bool = False
    score: float = 0.0      # 0.0 = complete failure, 1.0 = perfect
    duration_ms: float = 0.0
    error_code: str = ""
    error_message: str = ""
    trace_id: str = ""
    recorded_at: str = ""

    def __post_init__(self):
        if not self.recorded_at:
            self.recorded_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    goal_id: str = "",
    capability_id: str = "",
    provider_id: str = "",
    ok: bool = False,
    score: float = 0.0,
    duration_ms: float = 0.0,
    error_code: str = "",
    error_message: str = "",
    trace_id: str = "",
) -> None:
    """
    Record an execution experience.

    Args:
        goal_id: The goal this execution belongs to.
        capability_id: The capability that was executed.
        provider_id: The provider that executed it.
        ok: Whether execution succeeded.
        score: Quality score (0.0-1.0).
        duration_ms: Execution duration in milliseconds.
        error_code: Error code if failed (e.g., NOUS_TIMEOUT).
        error_message: Human-readable error message.
        trace_id: Trace ID linking to reasoning trace.
    """
    entry = {
        "goal_id": goal_id,
        "capability_id": capability_id,
        "provider_id": provider_id,
        "ok": ok,
        "score": score,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "error_message": error_message,
        "trace_id": trace_id,
        "recorded_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _experiences.append(entry)

    # Prune old records
    while len(_experiences) > MAX_RECORDS:
        _experiences.pop(0)

    log.debug("Experience recorded: %s via %s -> %s (%.0fms)",
              capability_id, provider_id, "ok" if ok else "fail", duration_ms)


def query(
    goal_id: str | None = None,
    capability_id: str | None = None,
    provider_id: str | None = None,
    ok_only: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Query experience records with optional filters.

    Args:
        goal_id: Filter by goal.
        capability_id: Filter by capability.
        provider_id: Filter by provider.
        ok_only: If True, only successes. If False, only failures.
        limit: Maximum records to return.

    Returns:
        List of experience records, most recent first.
    """
    results = _experiences

    if goal_id:
        results = [e for e in results if e["goal_id"] == goal_id]
    if capability_id:
        results = [e for e in results if e["capability_id"] == capability_id]
    if provider_id:
        results = [e for e in results if e["provider_id"] == provider_id]
    if ok_only is not None:
        results = [e for e in results if e["ok"] == ok_only]

    return list(reversed(results[-limit:]))


def stats(provider_id: str | None = None, capability_id: str | None = None) -> dict[str, Any]:
    """
    Compute aggregate statistics.

    Args:
        provider_id: Filter by provider (optional).
        capability_id: Filter by capability (optional).

    Returns:
        Dict with total, success_rate, avg_duration_ms, avg_score, error_counts.
    """
    subset = _experiences
    if provider_id:
        subset = [e for e in subset if e["provider_id"] == provider_id]
    if capability_id:
        subset = [e for e in subset if e["capability_id"] == capability_id]

    if not subset:
        return {"total": 0, "success_rate": 0.0, "avg_duration_ms": 0.0, "avg_score": 0.0, "error_counts": {}}

    total = len(subset)
    successes = sum(1 for e in subset if e["ok"])
    durations = [e["duration_ms"] for e in subset if e["duration_ms"] > 0]
    scores = [e["score"] for e in subset if e["score"] > 0]

    error_counts: dict[str, int] = {}
    for e in subset:
        if e["error_code"]:
            error_counts[e["error_code"]] = error_counts.get(e["error_code"], 0) + 1

    return {
        "total": total,
        "success_rate": round(successes / total, 4) if total > 0 else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "error_counts": error_counts,
    }


def best_provider(capability_id: str) -> str | None:
    """
    Find the best provider for a capability based on experience.

    Criteria: highest success_rate, then lowest avg_duration.

    Args:
        capability_id: The capability to find a provider for.

    Returns:
        Provider ID of the best provider, or None if no experience.
    """
    providers: dict[str, list[dict]] = {}
    for e in _experiences:
        if e["capability_id"] == capability_id:
            providers.setdefault(e["provider_id"], []).append(e)

    if not providers:
        return None

    best_pid = ""
    best_score = -1.0

    for pid, records in providers.items():
        success_rate = sum(1 for r in records if r["ok"]) / len(records) if records else 0
        avg_dur = sum(r["duration_ms"] for r in records) / len(records) if records else 999999
        # Score: weighted toward success rate, penalized by duration
        score = success_rate * 1000 - avg_dur * 0.1
        if score > best_score:
            best_score = score
            best_pid = pid

    return best_pid if best_pid else None


def count() -> int:
    """Total records stored."""
    return len(_experiences)


def clear() -> None:
    """Clear all experience records."""
    _experiences.clear()
