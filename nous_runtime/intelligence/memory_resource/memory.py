"""Explainable memory value, retention and token packing algorithms."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from nous_runtime.intelligence.memory_resource.errors import (
    InvalidMemorySignalError,
)
from nous_runtime.intelligence.memory_resource.models import (
    MemorySelection,
    MemorySelectionDecision,
    MemoryValueBreakdown,
    RetentionAction,
)


def _clamp(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise InvalidMemorySignalError("memory score inputs must be finite")
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class MemoryCandidate:
    memory_id: str
    content: str
    relevance: float = 0.5
    confidence: float = 0.5
    importance: float = 0.5
    access_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    token_estimate: int = 1
    created_at: str = ""
    last_accessed_at: str = ""
    sensitivity: float = 0.0
    pinned: bool = False
    superseded: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(
        cls,
        record: Any,
        *,
        relevance: float = 0.5,
        importance: float = 0.5,
        token_estimate: int | None = None,
    ) -> "MemoryCandidate":
        data = record if isinstance(record, Mapping) else record.to_dict()
        content = str(
            data.get("content")
            or data.get("detail")
            or data.get("value")
            or data.get("answer")
            or ""
        )
        return cls(
            memory_id=str(data.get("memory_id") or data.get("id") or ""),
            content=content,
            relevance=relevance,
            confidence=float(data.get("confidence") or 0.5),
            importance=importance,
            access_count=int(data.get("access_count") or 0),
            success_count=int(data.get("success_count") or 0),
            failure_count=int(data.get("failure_count") or 0),
            token_estimate=(
                int(token_estimate)
                if token_estimate is not None
                else max(1, len(content) // 4)
            ),
            created_at=str(data.get("created_at") or data.get("timestamp") or ""),
            last_accessed_at=str(data.get("last_accessed_at") or ""),
            sensitivity=float(data.get("sensitivity") or 0.0),
            pinned=bool(data.get("pinned", False)),
            superseded=bool(data.get("superseded") or not data.get("active", True)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MemoryValueWeights:
    relevance: float = 0.30
    confidence: float = 0.15
    importance: float = 0.20
    freshness: float = 0.10
    utility: float = 0.15
    frequency: float = 0.10
    token_penalty: float = 0.08
    sensitivity_penalty: float = 0.10
    version: str = "1.0.0"


@dataclass(frozen=True)
class MemoryRetentionPolicy:
    keep_threshold: float = 0.55
    compress_threshold: float = 0.35
    max_sensitivity: float = 1.0
    half_life_days: float = 30.0
    compressed_token_ratio: float = 0.35
    policy_version: str = "1.0.0"


class MemoryValueScorer:
    def __init__(
        self,
        weights: MemoryValueWeights | None = None,
        policy: MemoryRetentionPolicy | None = None,
    ) -> None:
        self.weights = weights or MemoryValueWeights()
        self.policy = policy or MemoryRetentionPolicy()

    def score(
        self,
        candidate: MemoryCandidate,
        *,
        now: datetime | None = None,
    ) -> MemoryValueBreakdown:
        relevance = _clamp(candidate.relevance)
        confidence = _clamp(candidate.confidence)
        importance = _clamp(candidate.importance)
        sensitivity = _clamp(candidate.sensitivity)
        freshness = self._freshness(candidate, now=now)
        total_outcomes = candidate.success_count + candidate.failure_count
        utility = (candidate.success_count + 1) / (total_outcomes + 2)
        frequency = 1.0 - math.exp(-max(0, candidate.access_count) / 5.0)
        token_penalty = min(1.0, max(1, candidate.token_estimate) / 4096.0)
        w = self.weights
        raw = (
            w.relevance * relevance
            + w.confidence * confidence
            + w.importance * importance
            + w.freshness * freshness
            + w.utility * utility
            + w.frequency * frequency
            - w.token_penalty * token_penalty
            - w.sensitivity_penalty * sensitivity
        )
        score = _clamp(raw)
        explanation = (
            f"relevance={relevance:.3f}",
            f"confidence={confidence:.3f}",
            f"importance={importance:.3f}",
            f"freshness={freshness:.3f}",
            f"utility={utility:.3f}",
            f"frequency={frequency:.3f}",
            f"token_penalty={token_penalty:.3f}",
            f"sensitivity_penalty={sensitivity:.3f}",
        )
        return MemoryValueBreakdown(
            relevance=relevance,
            confidence=confidence,
            importance=importance,
            freshness=freshness,
            utility=utility,
            frequency=frequency,
            token_penalty=token_penalty,
            sensitivity_penalty=sensitivity,
            score=round(score, 6),
            explanation=explanation,
        )

    def action(
        self,
        candidate: MemoryCandidate,
        breakdown: MemoryValueBreakdown,
    ) -> RetentionAction:
        if candidate.sensitivity > self.policy.max_sensitivity:
            return RetentionAction.REJECT
        if candidate.superseded:
            return RetentionAction.EVICT
        if candidate.pinned:
            return RetentionAction.PIN
        if breakdown.score >= self.policy.keep_threshold:
            return RetentionAction.KEEP
        if breakdown.score >= self.policy.compress_threshold:
            return RetentionAction.COMPRESS
        return RetentionAction.EVICT

    def _freshness(
        self,
        candidate: MemoryCandidate,
        *,
        now: datetime | None,
    ) -> float:
        timestamp = candidate.last_accessed_at or candidate.created_at
        if not timestamp:
            return 0.5
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            current = now or datetime.now(timezone.utc)
            age_days = max(0.0, (current - parsed).total_seconds() / 86400.0)
            return 2.0 ** (-age_days / self.policy.half_life_days)
        except (TypeError, ValueError):
            return 0.5


class MemoryIntelligence:
    def __init__(
        self,
        scorer: MemoryValueScorer | None = None,
    ) -> None:
        self.scorer = scorer or MemoryValueScorer()

    def select(
        self,
        candidates: tuple[MemoryCandidate, ...],
        *,
        token_budget: int,
        now: datetime | None = None,
    ) -> MemorySelectionDecision:
        if token_budget < 0:
            raise InvalidMemorySignalError(
                "token_budget must be non-negative"
            )
        evaluated = []
        for candidate in candidates:
            breakdown = self.scorer.score(candidate, now=now)
            action = self.scorer.action(candidate, breakdown)
            tokens = max(1, candidate.token_estimate)
            if action is RetentionAction.COMPRESS:
                tokens = max(
                    1,
                    round(
                        tokens
                        * self.scorer.policy.compressed_token_ratio
                    ),
                )
            evaluated.append((candidate, breakdown, action, tokens))
        evaluated.sort(
            key=lambda item: (
                0 if item[2] is RetentionAction.PIN else 1,
                -item[1].score,
                item[0].memory_id,
            )
        )
        selected = []
        rejected = []
        used = 0
        for candidate, breakdown, action, tokens in evaluated:
            if action in {RetentionAction.REJECT, RetentionAction.EVICT}:
                rejected.append(
                    MemorySelection(
                        candidate.memory_id,
                        action,
                        0,
                        breakdown,
                        "retention_policy",
                    )
                )
                continue
            if used + tokens > token_budget:
                rejected.append(
                    MemorySelection(
                        candidate.memory_id,
                        RetentionAction.EVICT,
                        0,
                        breakdown,
                        "token_budget_exhausted",
                    )
                )
                continue
            selected.append(
                MemorySelection(
                    candidate.memory_id,
                    action,
                    tokens,
                    breakdown,
                    "selected_by_value",
                )
            )
            used += tokens
        return MemorySelectionDecision(
            selected=tuple(selected),
            rejected=tuple(rejected),
            token_budget=token_budget,
            tokens_used=used,
            policy_version=self.scorer.policy.policy_version,
        )


__all__ = [
    "MemoryCandidate",
    "MemoryIntelligence",
    "MemoryRetentionPolicy",
    "MemoryValueScorer",
    "MemoryValueWeights",
]
