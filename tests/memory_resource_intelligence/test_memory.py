from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nous_runtime.intelligence.memory_resource import (
    InvalidMemorySignalError,
    MemoryCandidate,
    MemoryIntelligence,
    MemoryRetentionPolicy,
    MemoryValueScorer,
    RetentionAction,
)
from nous_runtime.project.memory_records import MemorySummary


def test_memory_candidate_adapts_existing_memory_record() -> None:
    record = MemorySummary(
        source_type="runtime",
        content="runtime architecture",
        confidence=0.8,
    )
    candidate = MemoryCandidate.from_record(
        record,
        relevance=0.9,
        importance=0.7,
    )

    assert candidate.memory_id == record.memory_id
    assert candidate.content == "runtime architecture"
    assert candidate.confidence == 0.8


def test_memory_value_is_decomposed_and_rewards_useful_fresh_memory() -> None:
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    scorer = MemoryValueScorer()
    valuable = MemoryCandidate(
        "valuable",
        "important decision",
        relevance=1,
        confidence=1,
        importance=1,
        access_count=10,
        success_count=8,
        failure_count=1,
        created_at=(now - timedelta(days=1)).isoformat(),
    )
    weak = MemoryCandidate(
        "weak",
        "old noise",
        relevance=0,
        confidence=0.1,
        importance=0,
        failure_count=5,
        created_at=(now - timedelta(days=365)).isoformat(),
        token_estimate=4096,
        sensitivity=1,
    )

    high = scorer.score(valuable, now=now)
    low = scorer.score(weak, now=now)

    assert high.score > low.score
    assert len(high.explanation) == 8
    assert scorer.action(valuable, high) is RetentionAction.KEEP
    assert scorer.action(weak, low) is RetentionAction.EVICT


def test_non_finite_memory_signal_is_rejected() -> None:
    with pytest.raises(InvalidMemorySignalError):
        MemoryValueScorer().score(
            MemoryCandidate("bad", "bad", relevance=float("nan"))
        )


def test_pinned_superseded_and_sensitive_actions_are_explicit() -> None:
    scorer = MemoryValueScorer(
        policy=MemoryRetentionPolicy(max_sensitivity=0.5)
    )
    pinned = MemoryCandidate("pin", "value", pinned=True)
    superseded = MemoryCandidate("old", "value", superseded=True)
    sensitive = MemoryCandidate("secret", "value", sensitivity=0.8)

    assert scorer.action(pinned, scorer.score(pinned)) is RetentionAction.PIN
    assert (
        scorer.action(superseded, scorer.score(superseded))
        is RetentionAction.EVICT
    )
    assert (
        scorer.action(sensitive, scorer.score(sensitive))
        is RetentionAction.REJECT
    )


def test_selection_is_deterministic_and_respects_token_budget() -> None:
    policy = MemoryRetentionPolicy(
        keep_threshold=0.4,
        compress_threshold=0.2,
    )
    intelligence = MemoryIntelligence(MemoryValueScorer(policy=policy))
    candidates = (
        MemoryCandidate(
            "b",
            "B",
            relevance=1,
            importance=1,
            confidence=1,
            token_estimate=8,
        ),
        MemoryCandidate(
            "a",
            "A",
            relevance=1,
            importance=1,
            confidence=1,
            token_estimate=8,
        ),
        MemoryCandidate(
            "pinned",
            "P",
            relevance=0,
            token_estimate=4,
            pinned=True,
        ),
    )

    decision = intelligence.select(candidates, token_budget=12)

    assert [item.memory_id for item in decision.selected] == ["pinned", "a"]
    assert decision.tokens_used == 12
    assert decision.rejected[0].reason == "token_budget_exhausted"


def test_compression_reduces_token_allocation() -> None:
    policy = MemoryRetentionPolicy(
        keep_threshold=0.9,
        compress_threshold=0.0,
        compressed_token_ratio=0.25,
    )
    decision = MemoryIntelligence(
        MemoryValueScorer(policy=policy)
    ).select(
        (MemoryCandidate("compress", "value", token_estimate=100),),
        token_budget=25,
    )

    assert decision.selected[0].action is RetentionAction.COMPRESS
    assert decision.selected[0].token_allocation == 25
