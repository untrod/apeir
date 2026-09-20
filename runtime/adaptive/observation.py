"""
Observation and Outcome Ledger.

Every scheduling/routing decision is recorded with:
- Why was this decision made?
- What was the predicted outcome?
- What was the actual outcome?
- What is the prediction error?
- Should we continue using this policy?

This is the EVIDENCE BASE for all adaptive policy evolution.
No decision may be made without an audit trail.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class DecisionType(str, Enum):
    MODEL_ROUTING = "model_routing"
    ENGINE_PLACEMENT = "engine_placement"
    DEVICE_SELECTION = "device_selection"
    CONTEXT_PAGING = "context_paging"
    CACHE_EVICTION = "cache_eviction"
    PREFETCHING = "prefetching"
    RETRY_STRATEGY = "retry_strategy"
    CHECKPOINT_TIMING = "checkpoint_timing"
    CONCURRENCY_LIMIT = "concurrency_limit"
    ENERGY_MODE = "energy_mode"
    VERIFICATION_STRATEGY = "verification_strategy"
    FALLBACK_SELECTION = "fallback_selection"


@dataclass
class CandidateRecord:
    """A candidate considered during decision-making."""

    candidate_id: str
    candidate_type: str
    estimated_quality: float
    estimated_latency_ms: float
    estimated_cost: float
    estimated_reliability: float = 0.99
    constraint_satisfied: bool = True
    filter_reason: str | None = None


@dataclass
class DecisionRecord:
    """The authoritative record of an adaptive decision.

    Every adaptive decision MUST produce one of these records.
    """

    decision_id: str = field(default_factory=lambda: str(uuid4()))
    workload_id: str = ""
    policy_id: str = ""
    policy_revision: int = 0
    decision_type: DecisionType = DecisionType.MODEL_ROUTING
    workload_class: str | None = None

    # Feature snapshot
    feature_snapshot: dict[str, Any] = field(default_factory=dict)

    # Candidates considered
    candidate_set: list[CandidateRecord] = field(default_factory=list)

    # Selected candidate
    selected_candidate_id: str = ""

    # Predicted outcomes
    predicted_quality: float = 0.0
    predicted_latency_ms: float = 0.0
    predicted_cost: float = 0.0
    predicted_reliability: float = 0.0

    # Actual outcomes (filled in after execution)
    actual_quality: float | None = None
    actual_latency_ms: float | None = None
    actual_cost: float | None = None
    actual_reliability: float | None = None

    # Deltas
    quality_delta: float | None = None
    latency_delta_ms: float | None = None
    cost_delta: float | None = None
    reliability_delta: float | None = None

    # Constraint violations
    constraint_violations: list[str] = field(default_factory=list)

    # Fallback information
    fallback_triggered: bool = False
    fallback_reason: str | None = None

    # Safety assessment
    safety_pass: bool = True
    safety_issues: list[str] = field(default_factory=list)

    # Trace linkage
    trace_id: str = ""
    parent_decision_id: str | None = None

    # Timing
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    observed_at: datetime | None = None

    def record_outcome(
        self,
        actual_quality: float,
        actual_latency_ms: float,
        actual_cost: float,
        actual_reliability: float = 0.99,
    ) -> None:
        """Record the actual observed outcome and compute deltas."""
        self.actual_quality = actual_quality
        self.actual_latency_ms = actual_latency_ms
        self.actual_cost = actual_cost
        self.actual_reliability = actual_reliability
        self.observed_at = datetime.now(timezone.utc)

        self.quality_delta = actual_quality - self.predicted_quality
        self.latency_delta_ms = actual_latency_ms - self.predicted_latency_ms
        self.cost_delta = actual_cost - self.predicted_cost
        self.reliability_delta = actual_reliability - self.predicted_reliability

    @property
    def is_complete(self) -> bool:
        """Check if the outcome has been recorded."""
        return self.observed_at is not None

    @property
    def prediction_error_pct(self) -> dict[str, float]:
        """Compute prediction error as percentages."""
        errors = {}
        if self.actual_quality is not None and self.predicted_quality > 0:
            errors["quality"] = abs(self.quality_delta) / self.predicted_quality * 100
        if self.actual_latency_ms is not None and self.predicted_latency_ms > 0:
            errors["latency"] = (
                abs(self.latency_delta_ms) / self.predicted_latency_ms * 100
            )
        if self.actual_cost is not None and self.predicted_cost > 0:
            errors["cost"] = abs(self.cost_delta) / self.predicted_cost * 100
        return errors


@dataclass
class PolicyStats:
    """Aggregate statistics for a policy from the observation ledger."""

    policy_id: str
    total_decisions: int = 0
    decisions_with_outcomes: int = 0
    mean_quality_delta: float | None = None
    mean_latency_delta_ms: float | None = None
    mean_cost_delta: float | None = None
    constraint_violation_rate: float = 0.0
    fallback_rate: float = 0.0
    safety_pass_rate: float = 0.0


class ObservationLedger:
    """Thread-safe ledger for recording and querying decisions.

    In production, this would be backed by SQLite (nous-state).
    For RC10, it provides the in-memory reference implementation.
    """

    def __init__(self) -> None:
        self._decisions: dict[str, DecisionRecord] = {}
        self._lock = threading.Lock()

    def record_decision(self, decision: DecisionRecord) -> None:
        """Record a new decision in the ledger."""
        with self._lock:
            self._decisions[decision.decision_id] = decision

    def record_outcome(
        self,
        decision_id: str,
        actual_quality: float,
        actual_latency_ms: float,
        actual_cost: float,
        actual_reliability: float = 0.99,
    ) -> DecisionRecord | None:
        """Record the actual outcome for a previously recorded decision."""
        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                return None
            decision.record_outcome(
                actual_quality=actual_quality,
                actual_latency_ms=actual_latency_ms,
                actual_cost=actual_cost,
                actual_reliability=actual_reliability,
            )
            return decision

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Get a specific decision by ID."""
        with self._lock:
            return self._decisions.get(decision_id)

    def find_by_policy(self, policy_id: str) -> list[DecisionRecord]:
        """Find all decisions for a specific policy."""
        with self._lock:
            return [d for d in self._decisions.values() if d.policy_id == policy_id]

    def find_by_workload(self, workload_id: str) -> list[DecisionRecord]:
        """Find all decisions for a specific workload."""
        with self._lock:
            return [d for d in self._decisions.values() if d.workload_id == workload_id]

    def compute_policy_stats(self, policy_id: str) -> PolicyStats:
        """Compute aggregate statistics for a policy."""
        decisions = self.find_by_policy(policy_id)
        stats = PolicyStats(policy_id=policy_id, total_decisions=len(decisions))

        completed = [d for d in decisions if d.is_complete]
        stats.decisions_with_outcomes = len(completed)

        if completed:
            stats.mean_quality_delta = sum(
                d.quality_delta for d in completed if d.quality_delta is not None
            ) / len(completed)
            stats.mean_latency_delta_ms = sum(
                d.latency_delta_ms for d in completed if d.latency_delta_ms is not None
            ) / len(completed)
            stats.mean_cost_delta = sum(
                d.cost_delta for d in completed if d.cost_delta is not None
            ) / len(completed)

        if decisions:
            stats.constraint_violation_rate = sum(
                1 for d in decisions if d.constraint_violations
            ) / len(decisions)
            stats.fallback_rate = sum(
                1 for d in decisions if d.fallback_triggered
            ) / len(decisions)
            stats.safety_pass_rate = sum(1 for d in decisions if d.safety_pass) / len(
                decisions
            )

        return stats

    def compute_features_digest(self, features: dict[str, Any]) -> str:
        """Compute a deterministic digest of feature data."""
        canonical = json.dumps(features, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def export(self) -> list[dict[str, Any]]:
        """Export all decisions as dictionaries for offline analysis."""
        with self._lock:
            return [
                {
                    "decision_id": d.decision_id,
                    "workload_id": d.workload_id,
                    "policy_id": d.policy_id,
                    "decision_type": d.decision_type.value,
                    "selected_candidate_id": d.selected_candidate_id,
                    "predicted_quality": d.predicted_quality,
                    "actual_quality": d.actual_quality,
                    "quality_delta": d.quality_delta,
                    "predicted_latency_ms": d.predicted_latency_ms,
                    "actual_latency_ms": d.actual_latency_ms,
                    "latency_delta_ms": d.latency_delta_ms,
                    "predicted_cost": d.predicted_cost,
                    "actual_cost": d.actual_cost,
                    "cost_delta": d.cost_delta,
                    "fallback_triggered": d.fallback_triggered,
                    "safety_pass": d.safety_pass,
                    "decided_at": d.decided_at.isoformat() if d.decided_at else None,
                    "observed_at": d.observed_at.isoformat() if d.observed_at else None,
                }
                for d in self._decisions.values()
            ]

    def clear(self) -> None:
        """Clear all records (for testing)."""
        with self._lock:
            self._decisions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._decisions)
