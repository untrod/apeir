# -*- coding: utf-8 -*-
"""Experience Analyzer — lightweight analysis and aggregation."""

from __future__ import annotations

from typing import Any

from nous_runtime.experience.store import ExperienceStore


class ExperienceAnalyzer:
    """Lightweight analytics over experience data."""

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()

    def summary(self) -> dict[str, Any]:
        """High-level experience summary."""
        stats = self._store.stats()
        experiences = self._store.list(limit=1000)

        task_types: dict[str, int] = {}
        for e in experiences:
            if e.task_type:
                task_types[e.task_type] = task_types.get(e.task_type, 0) + 1

        by_status: dict[str, int] = {"new": 0, "validated": 0, "trusted": 0, "deprecated": 0}
        for e in experiences:
            if e.status in by_status:
                by_status[e.status] += 1

        total = max(len(experiences), 1)

        return {
            **stats,
            "task_type_distribution": dict(sorted(task_types.items(), key=lambda x: x[1], reverse=True)[:10]),
            "status_distribution": by_status,
            "avg_confidence": round(sum(e.confidence for e in experiences) / total, 3),
            "lesson_count": sum(len(e.lessons) for e in experiences),
        }
