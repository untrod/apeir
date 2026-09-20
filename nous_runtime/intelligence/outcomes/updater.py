# -*- coding: utf-8 -*-
"""Bayesian Updater — updates outcome predictions from observed traces."""

from __future__ import annotations

import math
from typing import Any

from .model import PlanOutcomePrediction


class BayesianUpdater:
    """Updates outcome predictions using Beta-Binomial Bayesian updating.

    Each probability parameter has a Beta(a, b) prior that gets updated
    as we observe successes/failures from real task executions.
    """

    def __init__(self, prior_strength: float = 10.0) -> None:
        """prior_strength: weight of prior (higher = more conservative updates)."""
        self.prior_strength = prior_strength

    def update(
        self,
        prediction: PlanOutcomePrediction,
        observed: dict[str, Any],
        weight: float = 1.0,
    ) -> PlanOutcomePrediction:
        """Update prediction with observed outcome data.

        observed dict can contain: status, verification_status, latency_ms,
        cost_usd, human_intervention, safety_violation, artifact_count.
        """
        a0 = self.prior_strength * weight
        updated = PlanOutcomePrediction(plan_id=prediction.plan_id)

        # Completion probability
        success_obs = 1.0 if observed.get("status") == "success" else 0.0
        a_prior = prediction.completion_probability * a0
        (1.0 - prediction.completion_probability) * a0
        updated.completion_probability = (a_prior + success_obs * weight) / (a0 + weight)

        # Verified success
        verif_obs = 1.0 if observed.get("verification_status") == "pass" else 0.0
        a_vprior = prediction.verified_success_probability * a0
        (1.0 - prediction.verified_success_probability) * a0
        updated.verified_success_probability = (a_vprior + verif_obs * weight) / (a0 + weight)

        # Failure
        fail_obs = 1.0 if observed.get("status") == "failure" else 0.0
        a_fprior = prediction.failure_probability * a0
        (1.0 - prediction.failure_probability) * a0
        updated.failure_probability = (a_fprior + fail_obs * weight) / (a0 + weight)

        # Human intervention
        hi_obs = 1.0 if observed.get("human_intervention") else 0.0
        a_hiprior = prediction.human_intervention_probability * a0
        (1.0 - prediction.human_intervention_probability) * a0
        updated.human_intervention_probability = (a_hiprior + hi_obs * weight) / (a0 + weight)

        # Safety violation
        sv_obs = 1.0 if observed.get("safety_violation") else 0.0
        a_svprior = prediction.safety_violation_probability * a0
        (1.0 - prediction.safety_violation_probability) * a0
        updated.safety_violation_probability = (a_svprior + sv_obs * weight) / (a0 + weight)

        # Latency (EMA)
        obs_lat = float(observed.get("latency_ms", 0) or 0)
        if obs_lat > 0 and prediction.latency_mean_ms > 0:
            alpha = weight / (a0 + weight)
            updated.latency_mean_ms = (1 - alpha) * prediction.latency_mean_ms + alpha * obs_lat
            updated.latency_std_ms = math.sqrt(
                (1 - alpha) * prediction.latency_std_ms ** 2 +
                alpha * (obs_lat - updated.latency_mean_ms) ** 2
            )
        else:
            updated.latency_mean_ms = prediction.latency_mean_ms
            updated.latency_std_ms = prediction.latency_std_ms

        # Cost (EMA)
        obs_cost = float(observed.get("cost_usd", 0) or 0)
        if obs_cost > 0 and prediction.cost_mean_usd > 0:
            alpha = weight / (a0 + weight)
            updated.cost_mean_usd = (1 - alpha) * prediction.cost_mean_usd + alpha * obs_cost
            updated.cost_std_usd = math.sqrt(
                (1 - alpha) * prediction.cost_std_usd ** 2 +
                alpha * (obs_cost - updated.cost_mean_usd) ** 2
            )
        else:
            updated.cost_mean_usd = prediction.cost_mean_usd
            updated.cost_std_usd = prediction.cost_std_usd

        # Uncertainty reduction
        updated.epistemic_uncertainty = prediction.epistemic_uncertainty * (a0 / (a0 + weight))
        updated.aleatoric_uncertainty = prediction.aleatoric_uncertainty
        updated.sample_size = prediction.sample_size + 1
        updated.prediction_confidence = 1.0 - (updated.epistemic_uncertainty + updated.aleatoric_uncertainty) / 2
        updated.prediction_confidence = max(0.1, min(1.0, updated.prediction_confidence))

        return updated
