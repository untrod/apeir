"""
Adaptive Model Router — RC10 safe adaptive model selection.

Upgrades fixed model selection to constraint-filtered, multi-strategy
adaptive routing. Hard constraints filter first, then scoring strategies
rank the survivors.

When adaptive_routing is DISABLED: uses DeterministicRouter (multiplication only).
When adaptive_routing is ENABLED: may use Bandit, MOBO, or Pareto strategies
depending on strategy configuration and shadow/canary state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from runtime.adaptive.flags import AdaptiveFlags
from runtime.adaptive.baselines import (
    DeterministicRouter,
    MultiplicationScorer,
    ParetoRanker,
)
from runtime.adaptive.observation import (
    CandidateRecord,
    DecisionRecord,
    DecisionType,
    ObservationLedger,
)
from runtime.adaptive.safety import SafetyEnvelope


class RoutingStrategy(str, Enum):
    """Available routing strategies, ordered by complexity."""

    FIXED = "fixed"  # Always use the same model
    RULE_BASED = "rule_based"  # Deterministic rules
    MULTIPLICATION = "multiplication"  # Gold baseline (LMetric)
    PARETO = "pareto"  # Pareto frontier ranking
    BANDIT = "bandit"  # Contextual bandit (experimental)
    MOBO = "mobo"  # Multi-objective BO (experimental)


@dataclass
class ModelCandidate:
    """A model that could be chosen by the router."""

    model_id: str
    provider_id: str
    estimated_quality: float
    estimated_latency_ms: float
    estimated_cost_per_request: float
    estimated_reliability: float = 0.99
    privacy_level: float = 1.0
    features: dict[str, Any] = field(default_factory=dict)


class AdaptiveModelRouter:
    """Constraint-filtered, multi-strategy adaptive model router.

    Architecture:
    1. Hard constraints filter (safety envelope)
    2. Strategy-specific scoring
    3. Best candidate selection
    4. Decision observation recording
    5. Shadow evaluation (if enabled)
    """

    def __init__(
        self,
        safety_envelope: SafetyEnvelope | None = None,
        ledger: ObservationLedger | None = None,
        default_strategy: RoutingStrategy = RoutingStrategy.MULTIPLICATION,
    ) -> None:
        self._safety_envelope = safety_envelope or SafetyEnvelope.standard()
        self._ledger = ledger or ObservationLedger()
        self._default_strategy = default_strategy
        self._deterministic_router = DeterministicRouter()
        self._multiplication = MultiplicationScorer()
        self._pareto = ParetoRanker()

        # Adaptive strategy state (used only when feature enabled)
        self._bandit_state: dict[str, Any] = {}
        self._mobo_state: dict[str, Any] = {}

    def route(
        self,
        workload_id: str,
        candidates: list[ModelCandidate],
        features: dict[str, Any] | None = None,
        strategy: RoutingStrategy | None = None,
        constraints_override: dict[str, Callable[[dict], bool]] | None = None,
    ) -> tuple[ModelCandidate | None, DecisionRecord]:
        """Route to the best model candidate.

        If adaptive_routing is disabled, uses deterministic multiplication routing.
        If enabled, uses the specified or default adaptive strategy.

        Returns:
            (selected_candidate, decision_record)
            selected_candidate is None if no candidate passes all constraints.
        """
        flags = AdaptiveFlags.global_flags()
        effective_strategy = strategy or self._default_strategy

        if not flags.is_enabled("adaptive_routing"):
            effective_strategy = RoutingStrategy.MULTIPLICATION

        # Build decision record
        decision = DecisionRecord(
            workload_id=workload_id,
            policy_id=f"router-{effective_strategy.value}",
            policy_revision=1,
            decision_type=DecisionType.MODEL_ROUTING,
            feature_snapshot=features or {},
        )

        # Step 1: Filter through safety envelope
        candidate_dicts = [self._candidate_to_dict(c) for c in candidates]
        safe_candidates, envelope_results = self._safety_envelope.filter_candidates(
            candidate_dicts
        )

        # Record candidates and filter results
        decision.candidate_set = [
            CandidateRecord(
                candidate_id=c.model_id,
                candidate_type=c.provider_id,
                estimated_quality=c.estimated_quality,
                estimated_latency_ms=c.estimated_latency_ms,
                estimated_cost=c.estimated_cost_per_request,
                estimated_reliability=c.estimated_reliability,
                constraint_satisfied=any(
                    r.passed
                    for r in envelope_results
                    if candidate_dicts.index(self._candidate_to_dict(c))
                    < len(envelope_results)
                ),
            )
            for c in candidates
        ]

        if not safe_candidates:
            decision.safety_pass = False
            decision.safety_issues = ["No candidate passed safety envelope"]
            decision.fallback_triggered = True
            decision.fallback_reason = "All candidates rejected by safety envelope"
            self._ledger.record_decision(decision)
            return None, decision

        # Step 2: Score candidates
        selected = self._score_and_select(safe_candidates, effective_strategy)

        if selected is None:
            decision.fallback_triggered = True
            decision.fallback_reason = "No candidate selected after scoring"
            self._ledger.record_decision(decision)
            return None, decision

        # Step 3: Find original candidate
        selected_candidate = next(
            (c for c in candidates if c.model_id == selected["id"]), None
        )

        # Step 4: Record decision
        decision.selected_candidate_id = selected["id"]
        decision.predicted_quality = selected.get("quality", 0.0)
        decision.predicted_latency_ms = selected.get("latency_ms", 0.0)
        decision.predicted_cost = selected.get("cost", 0.0)
        decision.safety_pass = True
        self._ledger.record_decision(decision)

        return selected_candidate, decision

    def _score_and_select(
        self,
        safe_candidates: list[dict[str, Any]],
        strategy: RoutingStrategy,
    ) -> dict[str, Any] | None:
        """Score and select the best candidate using the chosen strategy."""
        if strategy == RoutingStrategy.MULTIPLICATION:
            scored = self._multiplication.rank(
                [
                    (
                        c["id"],
                        c.get("quality", 0.5),
                        c.get("latency_ms", 1000.0),
                        c.get("cost", 0.01),
                        c.get("reliability", 0.99),
                        c.get("privacy", 1.0),
                    )
                    for c in safe_candidates
                ]
            )
            if scored:
                best = scored[0]
                return {
                    "id": best.candidate_id,
                    "quality": best.quality_score,
                    "latency_ms": best.latency_score,
                    "cost": best.cost_score,
                    "composite_score": best.composite_score,
                    "strategy": "multiplication",
                }

        elif strategy == RoutingStrategy.PARETO:
            ranked = self._pareto.rank_by_frontier(safe_candidates)
            if ranked:
                # Sort by pareto_layer then by quality
                ranked.sort(
                    key=lambda c: (c.get("pareto_layer", 999), -c.get("quality", 0))
                )
                best = ranked[0]
                return {
                    "id": best.get("id", ""),
                    "quality": best.get("quality", 0.5),
                    "latency_ms": best.get("latency_ms", 1000.0),
                    "cost": best.get("cost", 0.01),
                    "strategy": "pareto",
                }

        elif strategy == RoutingStrategy.FIXED:
            # Just return the first candidate (should be pre-filtered)
            if safe_candidates:
                c = safe_candidates[0]
                return {
                    "id": c.get("id", ""),
                    "quality": c.get("quality", 0.5),
                    "latency_ms": c.get("latency_ms", 1000.0),
                    "cost": c.get("cost", 0.01),
                    "strategy": "fixed",
                }

        elif strategy == RoutingStrategy.RULE_BASED:
            # Simple rule: prefer highest quality among cost-constrained
            affordable = [
                c for c in safe_candidates if c.get("cost", float("inf")) <= 0.05
            ]
            target = affordable or safe_candidates
            best = max(target, key=lambda c: c.get("quality", 0))
            return {
                "id": best.get("id", ""),
                "quality": best.get("quality", 0.5),
                "latency_ms": best.get("latency_ms", 1000.0),
                "cost": best.get("cost", 0.01),
                "strategy": "rule_based",
            }

        elif strategy == RoutingStrategy.BANDIT:
            # Experimental — Epsilon-greedy over multiplication baseline
            # This is a stub; full implementation requires online learning
            import random

            if random.random() < 0.05:  # 5% exploration
                chosen = random.choice(safe_candidates)
                return {
                    "id": chosen.get("id", ""),
                    "quality": chosen.get("quality", 0.5),
                    "latency_ms": chosen.get("latency_ms", 1000.0),
                    "cost": chosen.get("cost", 0.01),
                    "strategy": "bandit_explore",
                }
            else:
                # Exploit: use multiplication baseline
                scored = self._multiplication.rank(
                    [
                        (
                            c["id"],
                            c.get("quality", 0.5),
                            c.get("latency_ms", 1000.0),
                            c.get("cost", 0.01),
                            c.get("reliability", 0.99),
                            c.get("privacy", 1.0),
                        )
                        for c in safe_candidates
                    ]
                )
                if scored:
                    return {
                        "id": scored[0].candidate_id,
                        "quality": scored[0].quality_score,
                        "latency_ms": scored[0].latency_score,
                        "cost": scored[0].cost_score,
                        "strategy": "bandit_exploit",
                    }

        return None

    def record_outcome(
        self,
        decision_id: str,
        actual_quality: float,
        actual_latency_ms: float,
        actual_cost: float,
    ) -> None:
        """Record actual outcome for a routing decision."""
        self._ledger.record_outcome(
            decision_id=decision_id,
            actual_quality=actual_quality,
            actual_latency_ms=actual_latency_ms,
            actual_cost=actual_cost,
        )

    def get_ledger(self) -> ObservationLedger:
        """Get the observation ledger for analysis."""
        return self._ledger

    @staticmethod
    def _candidate_to_dict(candidate: ModelCandidate) -> dict[str, Any]:
        return {
            "id": candidate.model_id,
            "provider_id": candidate.provider_id,
            "quality": candidate.estimated_quality,
            "latency_ms": candidate.estimated_latency_ms,
            "cost": candidate.estimated_cost_per_request,
            "reliability": candidate.estimated_reliability,
            "privacy": candidate.privacy_level,
            "data_classification": candidate.features.get(
                "data_classification", "public"
            ),
            "device_health": candidate.features.get("device_health", "healthy"),
            "estimated_latency_p99_ms": candidate.features.get(
                "estimated_latency_p99_ms",
                candidate.estimated_latency_ms * 2,
            ),
        }
