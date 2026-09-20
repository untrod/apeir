# -*- coding: utf-8 -*-
"""Contextual Bandit — safe exploration in Shadow Mode only.

V1 algorithms:
  Contextual UCB, Thompson Sampling, constrained bandit,
  safe exploration, delayed rewards, censored outcomes,
  non-stationary decay, provider/model drift.

Bandit MUST NOT bypass hard constraints or Policy Gates.
Runs in Shadow Mode by default.
"""

from .bandit import ContextualBandit, BanditConfig, BanditAction, BanditObservation

__all__ = ["ContextualBandit", "BanditConfig", "BanditAction", "BanditObservation"]
