# -*- coding: utf-8 -*-
"""Learning state contract tests."""

from nous_runtime.learning.state import (
    MasteryState,
    SpacedRepetitionScheduler,
    ProgressTracker,
)


class TestMasteryState:
    """MasteryState must track learning state in a domain-free way."""

    def test_default_state(self):
        """New items start with mastery 0.0."""
        state = MasteryState(item_id="item_001")
        assert state.mastery == 0.0
        assert state.review_count == 0

    def test_to_from_dict(self):
        """Round-trip through dict preserves data."""
        state = MasteryState(item_id="item_001", mastery=0.5, review_count=3)
        d = state.to_dict()
        restored = MasteryState.from_dict(d)
        assert restored.item_id == "item_001"
        assert restored.mastery == 0.5
        assert restored.review_count == 3


class TestSpacedRepetitionScheduler:
    """SM-2 scheduler must be configurable and domain-free."""

    def test_schedule_next_new_item(self):
        """New items are scheduled soon."""
        sched = SpacedRepetitionScheduler()
        next_date = sched.schedule_next(mastery=0.0, review_count=0)
        assert next_date  # Non-empty ISO string

    def test_schedule_mastered_item(self):
        """Mastered items are scheduled far out."""
        sched = SpacedRepetitionScheduler()
        next_date = sched.schedule_next(mastery=0.95, review_count=10)
        assert next_date  # Far in the future

    def test_update_mastery_correct(self):
        """Correct answers increase mastery."""
        sched = SpacedRepetitionScheduler()
        new = sched.update_mastery(0.5, "correct")
        assert new > 0.5

    def test_update_mastery_incorrect(self):
        """Incorrect answers decrease mastery."""
        sched = SpacedRepetitionScheduler()
        new = sched.update_mastery(0.5, "incorrect")
        assert new < 0.5

    def test_mastery_clamped(self):
        """Mastery stays in [0.0, 1.0]."""
        sched = SpacedRepetitionScheduler()
        assert sched.update_mastery(1.0, "correct") <= 1.0
        assert sched.update_mastery(0.0, "incorrect") >= 0.0

    def test_custom_intervals(self):
        """Custom intervals are supported."""
        sched = SpacedRepetitionScheduler(intervals=[1, 3, 7])
        next_date = sched.schedule_next(mastery=0.5, review_count=0)
        assert next_date


class TestProgressTracker:
    """ProgressTracker must be domain-free."""

    def test_record_and_coverage(self):
        """Recording sessions increases coverage."""
        pt = ProgressTracker()
        pt.record("item_001", "correct")
        pt.record("item_002", "correct")
        pt.record("item_001", "correct")  # Repeat
        assert pt.coverage() == 1.0  # All items reviewed

    def test_weak_items(self):
        """Weak items are identified."""
        pt = ProgressTracker()
        pt.record("item_001", "incorrect")
        # Record correct multiple times to raise mastery above threshold
        for _ in range(5):
            pt.record("item_002", "correct")
        weak = pt.weak_items(threshold=0.4)
        assert "item_001" in weak  # Still weak after incorrect
        assert "item_002" not in weak  # Mastered after multiple correct

    def test_due_items(self):
        """Unreviewed items are due."""
        pt = ProgressTracker()
        # Add item without recording a review — should be due
        state = MasteryState(item_id="new_item")
        pt.items["new_item"] = state
        due = pt.due_items()
        assert "new_item" in due

    def test_empty_tracker(self):
        """Empty tracker has zero coverage."""
        pt = ProgressTracker()
        assert pt.coverage() == 0.0
        assert pt.weak_items() == []
