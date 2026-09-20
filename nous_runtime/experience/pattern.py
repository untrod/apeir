# -*- coding: utf-8 -*-
"""Pattern Discovery Engine — finds recurring patterns in experience history.

Methods: frequency analysis, failure clustering, similarity grouping.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from nous_runtime.experience.models import ExperiencePattern, ExperienceRecord
from nous_runtime.experience.schema import PatternType
from nous_runtime.experience.store import ExperienceStore

_log = logging.getLogger("nous.experience.pattern")


class PatternEngine:
    """Discovers patterns from experience records.

    Usage::

        engine = PatternEngine(store)
        patterns = engine.discover()
        for p in patterns:
            store.save_pattern(p)
    """

    def __init__(self, store: ExperienceStore | None = None):
        self._store = store or ExperienceStore()



    def discover(self, min_frequency: int = 3) -> list[ExperiencePattern]:
        """Run all discovery methods. Returns discovered patterns."""
        patterns: list[ExperiencePattern] = []
        experiences = self._store.list(limit=500)

        if len(experiences) < min_frequency:
            return patterns

        # 1. Success patterns
        patterns.extend(self._discover_success_patterns(experiences, min_frequency))

        # 2. Failure patterns
        patterns.extend(self._discover_failure_patterns(experiences, min_frequency))

        # 3. Fix patterns
        patterns.extend(self._discover_fix_patterns(experiences, min_frequency))

        return patterns


    # Discovery methods


    def _discover_success_patterns(self, experiences: list[ExperienceRecord], min_freq: int) -> list[ExperiencePattern]:
        """Find task types with high success rates."""
        patterns: list[ExperiencePattern] = []
        by_task: dict[str, list[ExperienceRecord]] = {}
        for e in experiences:
            if e.task_type:
                by_task.setdefault(e.task_type, []).append(e)

        for task_type, exps in by_task.items():
            if len(exps) < min_freq:
                continue
            successes = sum(1 for e in exps if e.success)
            success_rate = successes / len(exps)
            if success_rate >= 0.70:
                patterns.append(ExperiencePattern(
                    pattern_type=PatternType.SUCCESS.value,
                    name=f"High success: {task_type}",
                    description=f"Task type '{task_type}' has {success_rate:.0%} success rate across {len(exps)} executions.",
                    frequency=len(exps),
                    success_rate=success_rate,
                    confidence=min(0.95, 0.5 + success_rate * 0.5),
                    source_experiences=tuple(e.id for e in exps[:20]),
                    tags=(task_type, "success"),
                ))
        return patterns

    def _discover_failure_patterns(self, experiences: list[ExperienceRecord], min_freq: int) -> list[ExperiencePattern]:
        """Find recurring failure reasons."""
        patterns: list[ExperiencePattern] = []
        failures = [e for e in experiences if not e.success and e.failure_reason]

        # Cluster by error code
        by_error: dict[str, list[ExperienceRecord]] = {}
        for e in failures:
            key = e.error_code or e.failure_reason[:60]
            by_error.setdefault(key, []).append(e)

        for error_key, exps in by_error.items():
            if len(exps) < min_freq:
                continue
            patterns.append(ExperiencePattern(
                pattern_type=PatternType.FAILURE.value,
                name=f"Recurring failure: {error_key[:80]}",
                description=f"Failure '{error_key[:100]}' observed {len(exps)} times.",
                frequency=len(exps),
                success_rate=0.0,
                confidence=min(0.90, 0.3 + len(exps) * 0.1),
                source_experiences=tuple(e.id for e in exps[:20]),
                tags=("failure", error_key[:30]),
            ))
        return patterns

    def _discover_fix_patterns(self, experiences: list[ExperienceRecord], min_freq: int) -> list[ExperiencePattern]:
        """Find lessons that appear across multiple experiences."""
        patterns: list[ExperiencePattern] = []
        lesson_counter: Counter = Counter()
        lesson_experiences: dict[str, list[str]] = {}

        for e in experiences:
            for lesson in e.lessons:
                key = lesson[:80]
                lesson_counter[key] += 1
                lesson_experiences.setdefault(key, []).append(e.id)

        for lesson, freq in lesson_counter.most_common(30):
            if freq < min_freq:
                continue
            patterns.append(ExperiencePattern(
                pattern_type=PatternType.FIX.value,
                name=f"Lesson: {lesson[:80]}",
                description=f"Lesson '{lesson[:120]}' learned from {freq} experiences.",
                frequency=freq,
                success_rate=0.80,
                confidence=0.70,
                source_experiences=tuple(lesson_experiences.get(lesson, [])[:20]),
                tags=("lesson", "fix"),
            ))
        return patterns


    # Frequency analysis


    def frequency_analysis(self, limit: int = 20) -> dict[str, Any]:
        """Statistical frequency analysis of experience data."""
        experiences = self._store.list(limit=1000)
        if not experiences:
            return {"total": 0}

        task_counts = Counter(e.task_type for e in experiences if e.task_type)
        error_counts = Counter(e.error_code for e in experiences if e.error_code)
        agent_counts = Counter(e.agent_id for e in experiences if e.agent_id)

        return {
            "total": len(experiences),
            "success_rate": sum(1 for e in experiences if e.success) / max(len(experiences), 1),
            "top_tasks": task_counts.most_common(limit),
            "top_errors": error_counts.most_common(limit),
            "top_agents": agent_counts.most_common(limit),
        }
