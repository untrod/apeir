# -*- coding: utf-8 -*-
"""Outcome Distribution Model — predicts joint outcome distributions for Execution Plans.

Predicts 10 dimensions per plan:
  completion_prob, verified_success_prob, latency_distribution, cost_distribution,
  failure_prob, recovery_prob, hallucination_prob, human_intervention_prob,
  safety_violation_prob, artifact_integrity_prob.

Uses: Bayesian updating, gradient boosting, calibrated classifiers,
quantile regression, survival analysis. No black-box neural networks in v1.
"""

from .model import OutcomeModel, PlanOutcomePrediction
from .updater import BayesianUpdater

__all__ = ["OutcomeModel", "PlanOutcomePrediction", "BayesianUpdater"]
