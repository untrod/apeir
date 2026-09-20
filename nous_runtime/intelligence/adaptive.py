"""Adaptive routing orchestration built from independently testable stages."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Sequence

from nous_runtime.intelligence.routing_history import (
    DEFAULT_ROUTING_HISTORY,
    RoutingDecisionHistory,
)
from nous_runtime.intelligence.scoring import (
    CandidateScore,
    NoEligibleModelError,
    RoutingConstraints,
    RoutingPolicy,
    build_model_vector,
    build_task_vector,
    default_dimension_registry,
    deterministic_sort,
    estimate_decision_confidence,
    evaluate_constraints,
    pareto_frontier,
    score_candidate,
)
from nous_runtime.intelligence.strategy import select_strategy
from nous_runtime.intelligence.task.models import TaskAnalysis
from nous_runtime.model.profile import ModelProfile


class AdaptiveRoutingEngine:
    """Constraint-first, explainable multi-objective model router."""

    def __init__(
        self,
        *,
        history: RoutingDecisionHistory | None = None,
    ) -> None:
        self.history = history or DEFAULT_ROUTING_HISTORY
        self.dimensions = default_dimension_registry()

    def route(
        self,
        task_analysis: TaskAnalysis,
        candidates: Sequence[ModelProfile],
        constraints: RoutingConstraints | None = None,
        policy: RoutingPolicy | None = None,
    ):
        from nous_runtime.intelligence.routing import RoutingDecision

        started = time.perf_counter()
        active_policy = policy or RoutingPolicy(mode="adaptive")
        task_vector = self.build_task_vector(task_analysis)
        active_constraints = constraints or self.constraints_from_analysis(
            task_analysis,
            task_vector.required_capabilities,
        )
        vectors = {
            profile.model_id: self.build_model_vector(profile)
            for profile in candidates
        }
        constraint_results = {
            profile.model_id: self.evaluate_constraints(
                profile,
                vectors[profile.model_id],
                active_constraints,
            )
            for profile in candidates
        }
        scores: list[CandidateScore] = []
        rejection_map: dict[str, tuple[str, ...]] = {}
        for profile in candidates:
            result = constraint_results[profile.model_id]
            if not result.eligible:
                rejection_map[profile.model_id] = result.rejection_reasons
                scores.append(
                    CandidateScore(
                        model_id=profile.model_id,
                        eligible=False,
                        rejection_reasons=result.rejection_reasons,
                        warnings=result.warnings,
                        reliability=profile.reliability_score,
                        estimated_cost=profile.estimated_cost,
                        latency_ms=profile.latency_ms,
                    )
                )
                continue
            candidate = self.score_candidate(
                task_vector,
                vectors[profile.model_id],
                profile,
                active_policy,
            )
            scores.append(replace(candidate, warnings=result.warnings))
        if not any(candidate.eligible for candidate in scores):
            raise NoEligibleModelError(
                "no model satisfies the routing constraints",
                rejections=rejection_map,
            )

        frontier = self.compute_pareto_frontier(scores)
        scores = [
            candidate.with_pareto(candidate.model_id in frontier)
            for candidate in scores
        ]
        ranked = deterministic_sort(scores)
        confidence = self.estimate_confidence(
            ranked,
            task_vector,
            vectors,
            active_policy,
        )
        strategy = self.select_strategy(
            task_analysis,
            task_vector,
            ranked,
            confidence.confidence,
            confidence.score_margin,
            active_policy,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        profile_versions = sorted(
            {vector.profile_version for vector in vectors.values()}
        )
        selected = next(candidate for candidate in ranked if candidate.eligible)
        decision_id = f"route_{uuid.uuid4().hex}"
        decision = RoutingDecision(
            task_id=task_analysis.task_id,
            candidate_models=tuple(
                candidate.model_id for candidate in ranked if candidate.eligible
            ),
            selected_model=selected.model_id,
            reason=(
                f"adaptive weighted capability match selected "
                f"{selected.model_id}; "
                f"strategy={strategy.strategy.value}; "
                f"confidence={confidence.confidence:.3f}"
            ),
            score=float(selected.score or 0.0),
            decision_id=decision_id,
            selected_model_id=selected.model_id,
            ranked_candidates=tuple(ranked),
            strategy=strategy,
            confidence=confidence.confidence,
            confidence_breakdown=confidence,
            policy_version=active_policy.version,
            profile_version=",".join(profile_versions),
            feedback_version="feedback-v1",
            explanation=self.build_explanation(ranked, strategy.rationale),
            created_at=datetime.now(timezone.utc).isoformat(),
            routing_mode="adaptive",
            duration_ms=elapsed_ms,
            score_margin=confidence.score_margin,
            observability={
                "decision_id": decision_id,
                "task_id": task_analysis.task_id,
                "routing_mode": "adaptive",
                "policy_version": active_policy.version,
                "profile_version": ",".join(profile_versions),
                "selected_model_id": selected.model_id,
                "selected_strategy": strategy.strategy.value,
                "candidate_count": len(candidates),
                "eligible_count": sum(item.eligible for item in ranked),
                "decision_confidence": confidence.confidence,
                "score_margin": confidence.score_margin,
                "fallback_reason": "",
                "duration_ms": elapsed_ms,
            },
        )
        self.history.record(decision)
        return decision

    def build_task_vector(self, analysis: TaskAnalysis):
        return build_task_vector(analysis, registry=self.dimensions)

    def build_model_vector(self, profile: ModelProfile):
        return build_model_vector(profile, registry=self.dimensions)

    @staticmethod
    def constraints_from_analysis(
        analysis: TaskAnalysis,
        required_capabilities: frozenset[str],
    ) -> RoutingConstraints:
        privacy = str(analysis.constraints.get("privacy") or "") or None
        return RoutingConstraints(
            required_capabilities=required_capabilities,
            max_cost=_optional_float(analysis.constraints.get("max_cost")),
            max_latency_ms=_optional_int(
                analysis.constraints.get("max_latency_ms")
            ),
            min_context_window=_optional_int(
                analysis.constraints.get("min_context_window")
            ),
            requires_tools=bool(analysis.constraints.get("requires_tools")),
            requires_vision=bool(analysis.constraints.get("requires_vision")),
            requires_local_execution=privacy == "local",
            requires_structured_output=bool(
                analysis.constraints.get("requires_structured_output")
            ),
            privacy_level=privacy,
        )

    @staticmethod
    def evaluate_constraints(profile, vector, constraints):
        return evaluate_constraints(profile, vector, constraints)

    @staticmethod
    def score_candidate(task, vector, profile, policy):
        return score_candidate(task, vector, profile, policy)

    @staticmethod
    def compute_pareto_frontier(scores):
        return pareto_frontier(scores)

    @staticmethod
    def estimate_confidence(ranked, task, vectors, policy):
        return estimate_decision_confidence(ranked, task, vectors, policy)

    @staticmethod
    def select_strategy(
        analysis,
        task,
        ranked,
        confidence,
        margin,
        policy,
    ):
        return select_strategy(
            task,
            ranked,
            decision_confidence=confidence,
            score_margin=margin,
            thresholds=policy.strategy,
            result_verifiable=bool(
                analysis.metadata.get("result_verifiable")
                or analysis.task_type in {"coding", "math"}
            ),
            availability_required=bool(
                analysis.constraints.get("availability") == "high"
            ),
        )

    @staticmethod
    def build_explanation(
        ranked: Sequence[CandidateScore],
        strategy_rationale: tuple[str, ...],
    ) -> tuple[str, ...]:
        explanations = []
        for candidate in ranked:
            if candidate.eligible:
                explanations.append(
                    f"{candidate.model_id}: score={candidate.score:.6f}, "
                    f"pareto={candidate.pareto_optimal}, "
                    f"confidence={candidate.confidence:.6f}"
                )
            else:
                explanations.append(
                    f"{candidate.model_id}: rejected="
                    + ",".join(candidate.rejection_reasons)
                )
        explanations.extend(f"strategy:{item}" for item in strategy_rationale)
        return tuple(explanations)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


__all__ = ["AdaptiveRoutingEngine"]
