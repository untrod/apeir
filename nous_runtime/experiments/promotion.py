# -*- coding: utf-8 -*-
"""Promotion Pipeline — algorithm promotion with evidence gates.

PROPOSED → SANDBOX → BENCHMARKED → ABLATED → REPLICATED →
SHADOW → CANARY → APPROVED → PRODUCTION

Failure: REJECTED or ROLLED_BACK
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .registry import ExperimentState


class PromotionDecision(str, Enum):
    PROMOTE = "promote"
    RETAIN = "retain"
    REJECT = "reject"
    ROLLBACK = "rollback"


VALID_PROMOTIONS = {
    ExperimentState.PROPOSED: [ExperimentState.SANDBOX],
    ExperimentState.SANDBOX: [ExperimentState.BENCHMARKED, ExperimentState.REJECTED],
    ExperimentState.BENCHMARKED: [ExperimentState.ABLATED, ExperimentState.REJECTED],
    ExperimentState.ABLATED: [ExperimentState.REPLICATED, ExperimentState.REJECTED],
    ExperimentState.REPLICATED: [ExperimentState.SHADOW, ExperimentState.REJECTED],
    ExperimentState.SHADOW: [ExperimentState.CANARY, ExperimentState.REJECTED],
    ExperimentState.CANARY: [ExperimentState.APPROVED, ExperimentState.ROLLED_BACK],
    ExperimentState.APPROVED: [ExperimentState.PRODUCTION, ExperimentState.ROLLED_BACK],
    ExperimentState.PRODUCTION: [ExperimentState.ROLLED_BACK],
}


@dataclass
class PromotionGate:
    """Gate that must be passed for promotion."""
    from_state: ExperimentState
    to_state: ExperimentState
    required_evidence: list[str] = field(default_factory=list)
    min_improvement: float = 0.0       # minimum improvement over baseline
    max_regression: float = 0.05       # maximum allowed regression in any metric
    min_sample_size: int = 0
    requires_human_approval: bool = False


PROMOTION_GATES = {
    (ExperimentState.PROPOSED, ExperimentState.SANDBOX): PromotionGate(
        from_state=ExperimentState.PROPOSED, to_state=ExperimentState.SANDBOX,
        required_evidence=["experiment_spec", "hypothesis", "baseline_defined"],
    ),
    (ExperimentState.BENCHMARKED, ExperimentState.ABLATED): PromotionGate(
        from_state=ExperimentState.BENCHMARKED, to_state=ExperimentState.ABLATED,
        required_evidence=["benchmark_results", "statistical_test", "effect_size"],
        min_improvement=0.0, min_sample_size=30,
    ),
    (ExperimentState.SHADOW, ExperimentState.CANARY): PromotionGate(
        from_state=ExperimentState.SHADOW, to_state=ExperimentState.CANARY,
        required_evidence=["shadow_comparisons", "safety_record", "constraint_record"],
        min_sample_size=50, requires_human_approval=True,
    ),
    (ExperimentState.CANARY, ExperimentState.APPROVED): PromotionGate(
        from_state=ExperimentState.CANARY, to_state=ExperimentState.APPROVED,
        required_evidence=["canary_results", "production_metrics", "rollback_plan"],
        min_improvement=0.01, max_regression=0.02, min_sample_size=200,
        requires_human_approval=True,
    ),
    (ExperimentState.APPROVED, ExperimentState.PRODUCTION): PromotionGate(
        from_state=ExperimentState.APPROVED,
        to_state=ExperimentState.PRODUCTION,
        required_evidence=[
            "safety_envelope_version",
            "governance_decision",
            "rollback_plan",
        ],
        min_sample_size=200,
        requires_human_approval=True,
    ),
}


class PromotionPipeline:
    """Manages algorithm promotion through the pipeline."""

    def evaluate(
        self,
        spec: Any,         # ExperimentSpec
        evidence: dict[str, Any],
    ) -> PromotionDecision:
        """Evaluate whether an experiment can be promoted to the next state."""
        current = spec.state
        valid_next = VALID_PROMOTIONS.get(current, [])
        if not valid_next:
            return PromotionDecision.RETAIN

        next_state = valid_next[0]  # primary path
        gate = PROMOTION_GATES.get((current, next_state))

        if gate is None:
            return PromotionDecision.PROMOTE  # no gate, auto-promote

        # Check evidence completeness
        missing = [e for e in gate.required_evidence if e not in evidence]
        if missing:
            return PromotionDecision.RETAIN  # insufficient evidence

        # Check improvement
        improvement = float(evidence.get("improvement", 0) or 0)
        if improvement < gate.min_improvement:
            return PromotionDecision.REJECT

        # Check sample size
        sample_size = int(evidence.get("sample_size", 0) or 0)
        if sample_size < gate.min_sample_size:
            return PromotionDecision.RETAIN  # need more data

        # Human approval gate
        if gate.requires_human_approval and not evidence.get("human_approved"):
            return PromotionDecision.RETAIN

        return PromotionDecision.PROMOTE

    def promote(
        self,
        spec: Any,
        evidence: dict[str, Any] | None = None,
    ) -> ExperimentState:
        """Promote only after the configured evidence gate accepts it."""
        if self.evaluate(spec, dict(evidence or {})) is not PromotionDecision.PROMOTE:
            return spec.state
        valid_next = VALID_PROMOTIONS.get(spec.state, [])
        if valid_next:
            spec.state = valid_next[0]
        return spec.state

    def rollback(self, spec: Any) -> ExperimentState:
        """Rollback experiment. Returns ROLLED_BACK."""
        spec.state = ExperimentState.ROLLED_BACK
        return spec.state
