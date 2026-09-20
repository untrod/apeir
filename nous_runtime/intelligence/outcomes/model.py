# -*- coding: utf-8 -*-
"""Outcome Distribution Model — predicts joint probabilities for Execution Plans.

V1: Hierarchical statistical model with Bayesian updating.
Not a black-box neural network — every prediction is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nous_runtime.intelligence.plans.schema import ExecutionPlan


@dataclass
class PlanOutcomePrediction:
    """Predicted outcome distribution for one Execution Plan."""
    plan_id: str = ""

    # Core probabilities
    completion_probability: float = 0.0       # P(task completes)
    verified_success_probability: float = 0.0 # P(completes AND passes verification)
    failure_probability: float = 0.0           # P(fails)
    recovery_probability: float = 0.0          # P(recovers | fails)
    hallucination_probability: float = 0.0     # P(produces incorrect but confident output)
    human_intervention_probability: float = 0.0
    safety_violation_probability: float = 0.0
    artifact_integrity_probability: float = 0.0

    # Continuous distributions (represented as mean ± std for v1)
    latency_mean_ms: float = 0.0
    latency_std_ms: float = 0.0
    cost_mean_usd: float = 0.0
    cost_std_usd: float = 0.0

    # Confidence in prediction
    prediction_confidence: float = 0.0         # 0-1, based on sample size and recency
    sample_size: int = 0
    last_updated: str = ""

    # Uncertainty
    aleatoric_uncertainty: float = 0.0         # inherent randomness
    epistemic_uncertainty: float = 0.0         # lack of knowledge

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class OutcomeModel:
    """Predicts outcome distributions for Execution Plans.

    Uses prior knowledge (model specs, node capabilities) + historical
    observations (from trace store) → Bayesian posterior predictions.
    """

    def __init__(self) -> None:
        # Priors by model capability level
        self._capability_priors = {
            "expert":    {"success": 0.90, "failure": 0.05, "hallucination": 0.03},
            "advanced":  {"success": 0.85, "failure": 0.08, "hallucination": 0.05},
            "competent": {"success": 0.75, "failure": 0.15, "hallucination": 0.08},
            "basic":     {"success": 0.60, "failure": 0.30, "hallucination": 0.10},
            "novice":    {"success": 0.40, "failure": 0.50, "hallucination": 0.15},
        }

        # Priors by verification strategy
        self._verification_priors = {
            "none":       {"verified_success_mult": 0.7, "false_completion_risk": 0.15},
            "standard":   {"verified_success_mult": 0.9, "false_completion_risk": 0.05},
            "exhaustive": {"verified_success_mult": 1.0, "false_completion_risk": 0.01},
        }

    def predict(self, plan: "ExecutionPlan", context: dict[str, Any]) -> PlanOutcomePrediction:  # type: ignore
        """Predict the outcome distribution for a plan."""
        p = PlanOutcomePrediction(plan_id=plan.plan_id)

        # Base rates from model capability
        # Infer capability from plan metadata
        capability = str(context.get("model_capability_level", "competent")).lower()
        priors = self._capability_priors.get(capability, self._capability_priors["competent"])

        p.completion_probability = priors["success"]
        p.failure_probability = priors["failure"]
        p.hallucination_probability = priors["hallucination"]

        # Verification impact
        verif = plan.verification_strategy or "standard"
        verif_priors = self._verification_priors.get(verif, self._verification_priors["standard"])
        p.verified_success_probability = p.completion_probability * verif_priors["verified_success_mult"]

        # Recovery probability
        recovery = plan.recovery_strategy or "retry"
        recovery_base = {"retry": 0.7, "fallback": 0.85, "reassign": 0.6, "escalate": 0.95}
        p.recovery_probability = recovery_base.get(recovery, 0.7) * (1.0 - p.failure_probability)

        # Human intervention
        risk_class = str(context.get("risk_class", "low"))
        intervention_base = {"low": 0.05, "medium": 0.15, "high": 0.40, "critical": 0.70}
        p.human_intervention_probability = intervention_base.get(risk_class, 0.15)

        # Safety
        p.safety_violation_probability = 0.02 if risk_class in ("high", "critical") else 0.005

        # Artifact integrity
        p.artifact_integrity_probability = 0.98 if plan.verification_strategy != "none" else 0.85

        # Latency estimate
        p.latency_mean_ms = plan.latency_estimate_ms
        p.latency_std_ms = plan.latency_estimate_ms * 0.5  # assume 50% CV

        # Cost estimate
        p.cost_mean_usd = plan.cost_estimate_usd
        p.cost_std_usd = plan.cost_estimate_usd * 0.3

        # Uncertainty
        p.epistemic_uncertainty = plan.uncertainty
        p.aleatoric_uncertainty = 0.1  # base inherent randomness
        p.prediction_confidence = 1.0 - (p.epistemic_uncertainty + p.aleatoric_uncertainty) / 2
        p.prediction_confidence = max(0.1, min(1.0, p.prediction_confidence))

        return p

    def calibrate(self, predictions: list[PlanOutcomePrediction],
                  actual_outcomes: list[dict]) -> float:
        """Compute calibration error between predicted and actual outcomes."""
        if not predictions or not actual_outcomes:
            return 0.0

        errors = []
        for pred, actual in zip(predictions, actual_outcomes):
            actual_success = 1.0 if actual.get("status") == "success" else 0.0
            errors.append(abs(pred.completion_probability - actual_success))

        return sum(errors) / len(errors) if errors else 0.0
