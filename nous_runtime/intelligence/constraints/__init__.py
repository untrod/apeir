# -*- coding: utf-8 -*-
"""Constraint Engine — hard constraints and soft preferences for Execution Plans.

Hard constraints (never violable):
  privacy, data residency, model capability, license, node architecture,
  available memory/GPU, budget ceiling, deadline, network, tool permission,
  file permission, safety policy, approval requirement.

Soft preferences (weighted, trade-offable):
  cost_preference, latency_preference, quality_preference,
  reliability_preference, reproducibility_preference.

Hard constraints CANNOT be offset by high quality, low cost, or low latency.
"""

from .engine import ConstraintEngine, ConstraintResult, HardConstraint, SoftPreference
from .definitions import HARD_CONSTRAINTS, SOFT_PREFERENCES

__all__ = [
    "ConstraintEngine",
    "ConstraintResult",
    "HardConstraint",
    "SoftPreference",
    "HARD_CONSTRAINTS",
    "SOFT_PREFERENCES",
]
