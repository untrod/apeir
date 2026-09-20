# -*- coding: utf-8 -*-
"""
Generic Learning Runtime — domain-free learning state management.

This module provides the learning primitives that any Study Pack or
Knowledge Pack can use. The Runtime knows HOW to manage learning state
(spaced repetition, mastery tracking, progress) but never WHAT is
being learned (subjects, exams, specific knowledge content).

Key concepts:
    MasteryState     — tracked per item: mastery level, review count, scheduling
    SpacedRepetitionScheduler — SM-2 algorithm, configurable intervals
    ProgressTracker  — coverage %, streaks, weak-spot detection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# MasteryState

@dataclass
class MasteryState:
    """Per-item learning state — domain-agnostic."""

    item_id: str                          # Opaque ID (pack-provided)
    mastery: float = 0.0                  # 0.0 (new) → 1.0 (mastered)
    review_count: int = 0
    last_reviewed: str = ""               # ISO datetime
    next_review: str = ""                 # ISO datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "mastery": self.mastery,
            "review_count": self.review_count,
            "last_reviewed": self.last_reviewed,
            "next_review": self.next_review,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MasteryState":
        return cls(
            item_id=str(d.get("item_id", "")),
            mastery=float(d.get("mastery", 0.0)),
            review_count=int(d.get("review_count", 0)),
            last_reviewed=str(d.get("last_reviewed", "")),
            next_review=str(d.get("next_review", "")),
        )


# SpacedRepetitionScheduler

class SpacedRepetitionScheduler:
    """
    SM-2 spaced repetition scheduler with configurable intervals.

    Usage:
        sched = SpacedRepetitionScheduler()
        next_date = sched.schedule_next(mastery=0.5, review_count=2)
    """

    # Default SM-2 intervals (days)
    DEFAULT_INTERVALS = [1, 2, 4, 7, 14, 30, 60, 120, 240]

    def __init__(self, intervals: list[int] | None = None):
        self.intervals = intervals or self.DEFAULT_INTERVALS

    def schedule_next(self, mastery: float, review_count: int) -> str:
        """
        Compute the next review date.

        Args:
            mastery: Current mastery level (0.0 - 1.0).
            review_count: Number of times this item has been reviewed.

        Returns:
            ISO-format datetime string for the next review.
        """
        now = datetime.now(timezone.utc)
        idx = min(review_count, len(self.intervals) - 1)
        base_days = self.intervals[idx]

        # Adjust interval by mastery: low mastery → sooner, high → later
        if mastery < 0.3:
            factor = 0.5
        elif mastery < 0.7:
            factor = 1.0
        elif mastery < 0.9:
            factor = 1.5
        else:
            factor = 2.0

        days = max(1, int(base_days * factor))
        next_date = now + timedelta(days=days)
        return next_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    def update_mastery(self, current: float, result: str) -> float:
        """
        Update mastery based on a review result.

        Args:
            current: Current mastery level.
            result: "correct", "partial", or "incorrect".

        Returns:
            New mastery level (clamped 0.0 - 1.0).
        """
        deltas = {"correct": +0.15, "partial": +0.03, "incorrect": -0.10}
        delta = deltas.get(result, 0.0)
        new = max(0.0, min(1.0, current + delta))
        return round(new, 4)


# ProgressTracker

@dataclass
class ProgressTracker:
    """
    Tracks aggregate progress across a set of items.

    Usage:
        pt = ProgressTracker()
        pt.record("item_001", "correct")
        print(pt.coverage())  # fraction of items reviewed at least once
    """

    items: dict[str, MasteryState] = field(default_factory=dict)

    def record(self, item_id: str, result: str) -> MasteryState:
        """Record a review attempt and return updated state."""
        state = self.items.get(item_id, MasteryState(item_id=item_id))
        scheduler = SpacedRepetitionScheduler()
        state.mastery = scheduler.update_mastery(state.mastery, result)
        state.review_count += 1
        state.last_reviewed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state.next_review = scheduler.schedule_next(state.mastery, state.review_count)
        self.items[item_id] = state
        return state

    def coverage(self) -> float:
        """Fraction of items reviewed at least once."""
        if not self.items:
            return 0.0
        reviewed = sum(1 for s in self.items.values() if s.review_count > 0)
        return round(reviewed / len(self.items), 4)

    def weak_items(self, threshold: float = 0.4) -> list[str]:
        """Return item IDs with mastery below threshold."""
        return [iid for iid, s in self.items.items() if s.mastery < threshold]

    def due_items(self) -> list[str]:
        """Return item IDs that are due for review."""
        now = datetime.now(timezone.utc)
        due = []
        for iid, s in self.items.items():
            if not s.next_review:
                due.append(iid)
                continue
            try:
                next_dt = datetime.strptime(s.next_review, "%Y-%m-%dT%H:%M:%SZ")
                if now >= next_dt:
                    due.append(iid)
            except (ValueError, TypeError):
                due.append(iid)
        return due

    def streak_days(self, activity_log: list[str]) -> int:
        """Count consecutive days with at least one review, from today backward."""
        if not activity_log:
            return 0
        # activity_log: list of ISO date strings
        dates = sorted(set(d[:10] for d in activity_log), reverse=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        streak = 0
        expected = today
        for d in dates:
            if d == expected:
                streak += 1
                expected = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            elif d < expected:
                break
        return streak
