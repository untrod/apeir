# -*- coding: utf-8 -*-
"""Contextual Bandit — Multi-armed bandit with context for Shadow Mode.

Thompson Sampling: sample from Beta posterior for each arm, pick max.
Contextual UCB: add exploration bonus based on uncertainty.
Constrained: arms violating hard constraints are removed before selection.
Safe exploration: new arms start with pessimistic prior.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BanditConfig:
    """Configuration for contextual bandit."""
    algorithm: str = "thompson_sampling"  # thompson_sampling, ucb, epsilon_greedy
    exploration_weight: float = 2.0       # for UCB
    epsilon: float = 0.1                  # for epsilon-greedy
    prior_strength: float = 10.0          # weight of Beta prior
    decay_rate: float = 0.001             # non-stationary decay per second
    min_samples_for_exploitation: int = 5
    shadow_only: bool = True              # NEVER run in production without explicit approval


@dataclass
class BanditAction:
    """A single action (arm) in the bandit."""
    action_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)  # features describing this action
    alpha: float = 1.0   # Beta prior: successes + 1
    beta: float = 1.0    # Beta prior: failures + 1
    samples: int = 0
    last_seen: float = 0.0  # timestamp


@dataclass
class BanditObservation:
    """Feedback from a bandit action."""
    action_id: str = ""
    reward: float = 0.0     # 0-1
    timestamp: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


class ContextualBandit:
    """Contextual multi-armed bandit for Shadow Mode policy exploration.

    Thompson Sampling: sample from Beta posterior → select max.
    Contextual UCB: expected_reward + exploration_bonus.
    Constrained: filter arms by hard constraints before selection.
    Safe: pessimistic prior (alpha=1, beta=10) for new arms.
    """

    def __init__(self, config: BanditConfig | None = None) -> None:
        self.config = config or BanditConfig()
        self._actions: dict[str, BanditAction] = {}
        self._history: list[BanditObservation] = []

    def register_action(self, action_id: str, context: dict[str, Any] | None = None) -> None:
        """Register a new arm with pessimistic prior."""
        if action_id not in self._actions:
            self._actions[action_id] = BanditAction(
                action_id=action_id,
                context=dict(context or {}),
                alpha=1.0,   # pessimistic: low initial success
                beta=10.0,   # pessimistic: high initial failure
                last_seen=time.monotonic(),
            )

    def remove_action(self, action_id: str) -> None:
        self._actions.pop(action_id, None)

    def select(self, context: dict[str, Any] | None = None) -> str | None:
        """Select the best action given current context."""
        if not self._actions:
            return None

        ctx = context or {}
        eligible = list(self._actions.values())

        # Constraint filter
        eligible = self._filter_by_constraints(eligible, ctx)
        if not eligible:
            return None

        # Decay
        self._apply_decay()

        # Select
        if self.config.algorithm == "thompson_sampling":
            return self._thompson_sample(eligible)
        elif self.config.algorithm == "ucb":
            return self._ucb_select(eligible)
        elif self.config.algorithm == "epsilon_greedy":
            return self._epsilon_greedy(eligible)
        else:
            return self._thompson_sample(eligible)

    def observe(self, observation: BanditObservation) -> None:
        """Update bandit with observed reward."""
        action = self._actions.get(observation.action_id)
        if action is None:
            return

        action.samples += 1
        action.last_seen = time.monotonic()

        # Beta update
        if observation.reward > 0.5:
            action.alpha += observation.reward
        else:
            action.beta += (1.0 - observation.reward)

        self._history.append(observation)

    def get_action_stats(self, action_id: str) -> dict[str, Any]:
        """Get statistics for an action."""
        action = self._actions.get(action_id)
        if action is None:
            return {}
        mean = action.alpha / (action.alpha + action.beta) if (action.alpha + action.beta) > 0 else 0.0
        std = math.sqrt(action.alpha * action.beta / ((action.alpha + action.beta) ** 2 * (action.alpha + action.beta + 1))) if (action.alpha + action.beta) > 0 else 0.0
        return {
            "action_id": action_id,
            "mean_reward": mean,
            "std": std,
            "samples": action.samples,
            "alpha": action.alpha,
            "beta": action.beta,
        }

    # Internal

    def _thompson_sample(self, actions: list[BanditAction]) -> str:
        """Sample from Beta posterior for each action, return max."""
        best_action = None
        best_sample = -1.0
        for a in actions:
            sample = random.betavariate(max(0.01, a.alpha), max(0.01, a.beta))
            if sample > best_sample:
                best_sample = sample
                best_action = a.action_id
        return best_action or actions[0].action_id

    def _ucb_select(self, actions: list[BanditAction]) -> str:
        """Upper Confidence Bound selection."""
        total_n = sum(a.samples for a in actions) + 1
        best_action = None
        best_score = -float("inf")
        for a in actions:
            mean = a.alpha / (a.alpha + a.beta) if (a.samples > 0) else 0.5
            bonus = self.config.exploration_weight * math.sqrt(math.log(total_n) / max(a.samples, 1))
            score = mean + bonus
            if score > best_score:
                best_score = score
                best_action = a.action_id
        return best_action or actions[0].action_id

    def _epsilon_greedy(self, actions: list[BanditAction]) -> str:
        """Epsilon-greedy: explore with probability epsilon."""
        if random.random() < self.config.epsilon:
            return random.choice(actions).action_id
        # Exploit: pick highest mean
        return max(actions, key=lambda a: a.alpha / (a.alpha + a.beta) if a.samples > 0 else 0).action_id

    def _filter_by_constraints(self, actions: list[BanditAction], ctx: dict) -> list[BanditAction]:
        """Filter actions by hard constraints. Unsatisfiable arms are excluded."""
        required_cap = str(ctx.get("min_capability", "") or "")
        max_cost = float(ctx.get("max_cost", 0) or 0)
        eligible = []
        for a in actions:
            a_cap = str(a.context.get("capability_level", "") or "")
            a_cost = float(a.context.get("cost", 0) or 0)
            if required_cap:
                levels = {"expert": 5, "advanced": 4, "competent": 3, "basic": 2, "novice": 1}
                if levels.get(a_cap, 0) < levels.get(required_cap, 0):
                    continue
            if max_cost > 0 and a_cost > max_cost:
                continue
            eligible.append(a)
        return eligible

    def _apply_decay(self) -> None:
        """Apply non-stationary decay to all actions."""
        now = time.monotonic()
        for a in self._actions.values():
            delta_t = now - a.last_seen
            if delta_t > 3600:  # decay after 1 hour of inactivity
                decay = math.exp(-self.config.decay_rate * delta_t)
                a.alpha = 1.0 + (a.alpha - 1.0) * decay
                a.beta = 1.0 + (a.beta - 1.0) * decay
                a.last_seen = now
