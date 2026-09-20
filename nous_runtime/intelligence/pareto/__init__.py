# -*- coding: utf-8 -*-
"""Multi-Objective Pareto Engine for Execution Plan selection.

Evaluates plans across 9 objectives:
  quality, safety, privacy, latency, cost, reliability,
  reproducibility, resource_usage, human_intervention.

NEVER collapses all objectives into a single scalar score.
Produces: non-dominated plans, dominated plans, dominance explanations,
trade-off summaries, constraint boundaries.
"""

from .engine import ParetoEngine, ParetoResult, dominates

__all__ = ["ParetoEngine", "ParetoResult", "dominates"]
