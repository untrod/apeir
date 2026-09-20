# -*- coding: utf-8 -*-
"""14 baseline algorithm implementations.

Each baseline is a simple, deterministic, auditable policy.
They serve as comparison points for all new intelligent algorithms.
"""

from __future__ import annotations

import random


class FixedStrongestModel:
    """Always select the model with the highest declared capability score."""
    name = "fixed_strongest"
    description = "Always pick the model with highest declared capability level"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        # Sort by capability level: expert > advanced > competent > basic > novice
        order = {"expert": 5, "advanced": 4, "competent": 3, "basic": 2, "novice": 1}
        return max(available, key=lambda m: order.get(
            str(m.get("capability_level", "basic")).lower(), 0
        ))

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class FixedCheapestModel:
    """Always select the model with the lowest cost per token."""
    name = "fixed_cheapest"
    description = "Always pick the model with lowest declared cost"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        return min(available, key=lambda m: float(m.get("cost_per_1k_tokens", 999)))

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return False

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class FixedFastestModel:
    """Always select the model with the lowest declared latency."""
    name = "fixed_fastest"
    description = "Always pick the model with lowest declared latency"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        return min(available, key=lambda m: float(m.get("avg_latency_ms", 999999)))

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return False

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class RandomModel:
    """Select a model uniformly at random from available models."""
    name = "random_model"
    description = "Select a model uniformly at random"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        return random.choice(available)

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        return random.choice(available)

    def should_verify(self, task: dict) -> bool:
        return random.random() < 0.5

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class RoundRobin:
    """Cycle through available models in round-robin order."""
    name = "round_robin"
    description = "Cycle through models in round-robin order"
    def __init__(self) -> None:
        self._counter = 0

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        idx = self._counter % len(available)
        self._counter += 1
        return available[idx]

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        return available[self._counter % len(available)]

    def should_verify(self, task: dict) -> bool:
        return self._counter % 5 == 0  # verify every 5th task

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class ManualRuleRouter:
    """Route based on simple keyword-matching rules."""
    name = "manual_rule"
    description = "Route based on keyword-matching task-to-model rules"

    RULES = {
        "code": ["gpt", "claude"],
        "image": ["gpt", "claude"],
        "math": ["claude", "gpt"],
        "research": ["claude"],
        "chat": ["deepseek"],
        "local": ["ollama"],
    }

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None
        task_type = str(task.get("task_type", "")).lower()
        task_text = str(task.get("description", "")).lower()

        # Find matching rule
        preferred = []
        for keyword, models in self.RULES.items():
            if keyword in task_type or keyword in task_text:
                preferred.extend(models)

        if preferred:
            for pref in preferred:
                for m in available:
                    if pref in str(m.get("model_id", "")).lower():
                        return m

        return available[0]  # fallback to first available

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return task.get("risk_class", "low") in ("high", "critical")

    def agent_topology(self, task: dict) -> list[str]:
        if task.get("risk_class") in ("high", "critical"):
            return ["planner", "worker", "reviewer"]
        return ["worker"]


class WeightedScalarScore:
    """Compute a weighted scalar score and pick the highest.

    score = w1*quality + w2*(-cost) + w3*(-latency) + w4*reliability
    """
    name = "weighted_scalar"
    description = "Single weighted scalar score: w1*quality + w2*(-cost) + w3*(-latency) + w4*reliability"
    WEIGHTS = {"quality": 0.40, "cost": 0.25, "latency": 0.20, "reliability": 0.15}

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        if not available:
            return None

        # Normalize values to [0, 1]
        costs = [float(m.get("cost_per_1k_tokens", 0.01)) for m in available]
        latencies = [float(m.get("avg_latency_ms", 1000)) for m in available]
        max_cost = max(costs) or 1
        max_lat = max(latencies) or 1

        def score(m: dict) -> float:
            quality = {"expert": 1.0, "advanced": 0.8, "competent": 0.6, "basic": 0.4, "novice": 0.2}.get(
                str(m.get("capability_level", "basic")).lower(), 0.4
            )
            cost_norm = 1.0 - (float(m.get("cost_per_1k_tokens", 0.01)) / max_cost)
            lat_norm = 1.0 - (float(m.get("avg_latency_ms", 1000)) / max_lat)
            reliability = float(m.get("success_rate", 0.8))

            return (
                self.WEIGHTS["quality"] * quality
                + self.WEIGHTS["cost"] * cost_norm
                + self.WEIGHTS["latency"] * lat_norm
                + self.WEIGHTS["reliability"] * reliability
            )

        return max(available, key=score)

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class SingleAgent:
    """Single agent does everything."""
    name = "single_agent"
    description = "Single agent handles all steps (no decomposition)"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return False

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class FixedPlannerWorkerReviewer:
    """Fixed 3-role topology: Planner → Worker → Reviewer."""
    name = "fixed_planner_worker_reviewer"
    description = "Fixed 3-role topology: Planner, Worker, Reviewer"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["planner", "worker", "reviewer"]


class FixedNode:
    """Always assign to the first available node (no load balancing)."""
    name = "fixed_node"
    description = "Always assign to first available node"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class NoVerification:
    """Never run verification."""
    name = "no_verification"
    description = "Never verify task output"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return False

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class AlwaysVerify:
    """Always run full verification."""
    name = "always_verify"
    description = "Always run full verification on every task"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker", "verifier"]


class LocalOnly:
    """Only use local/Ollama models, never cloud."""
    name = "local_only"
    description = "Only use locally-deployed models (Ollama, local provider)"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        local = [m for m in available if str(m.get("endpoint_type", "")).lower() in ("local", "ollama")]
        return local[0] if local else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        local = [n for n in available if str(n.get("platform", "")).lower() != "cloud"]
        return local[0] if local else (available[0] if available else None)

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


class CloudOnly:
    """Only use cloud API models, never local."""
    name = "cloud_only"
    description = "Only use cloud API providers (OpenAI, DeepSeek, etc.)"

    def select_model(self, task: dict, available: list[dict]) -> dict | None:
        cloud = [m for m in available if str(m.get("endpoint_type", "")).lower() not in ("local", "ollama")]
        return cloud[0] if cloud else None

    def select_node(self, task: dict, available: list[dict]) -> dict | None:
        return available[0] if available else None

    def should_verify(self, task: dict) -> bool:
        return True

    def agent_topology(self, task: dict) -> list[str]:
        return ["worker"]


# All baselines in registration order

ALL_BASELINES = [
    FixedStrongestModel(),
    FixedCheapestModel(),
    FixedFastestModel(),
    RandomModel(),
    RoundRobin(),
    ManualRuleRouter(),
    WeightedScalarScore(),
    SingleAgent(),
    FixedPlannerWorkerReviewer(),
    FixedNode(),
    NoVerification(),
    AlwaysVerify(),
    LocalOnly(),
    CloudOnly(),
]
