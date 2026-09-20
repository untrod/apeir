# -*- coding: utf-8 -*-
"""Assignment Engine — assigns agents, models, and nodes to task graph nodes.

Considers: capability fit, model availability, node resources, queue depth,
latency, cost, privacy, communication overhead, context dependency,
correlated failure risk, previous performance, uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Assignment:
    """A single role → (model, node) assignment."""
    role_id: str = ""
    model_id: str = ""
    node_id: str = ""
    score: float = 0.0
    reasoning: str = ""
    alternatives: list[dict] = field(default_factory=list)  # backup assignments


class AssignmentEngine:
    """Assigns models and nodes to agent roles for task execution.

    NOT just ranking models by a single score.
    Considers multi-dimensional fit: capability, cost, latency, privacy,
    availability, previous performance, and correlated failure risk.
    """

    def assign(
        self,
        roles: list[Any],               # AgentRole list
        models: list[dict[str, Any]],
        nodes: list[dict[str, Any]],
        task: dict[str, Any],
    ) -> list[Assignment]:
        """Assign each role to the best (model, node) pair."""
        assignments = []

        for role in roles:
            best = self._best_fit(role, models, nodes, task, assignments)
            assignments.append(best)

        return assignments

    def _best_fit(
        self,
        role: Any,
        models: list[dict],
        nodes: list[dict],
        task: dict,
        previous: list[Assignment],
    ) -> Assignment:
        """Find the best model+node pair for a role."""
        best = Assignment(role_id=getattr(role, "role_id", ""), score=-1.0)
        used_models = {a.model_id for a in previous}
        used_nodes = {a.node_id for a in previous}

        for model in models:
            model_id = str(model.get("model_id", ""))
            for node in nodes:
                node_id = str(node.get("node_id", ""))

                score = self._score_fit(role, model, node, task)

                # Penalize reusing same model (correlated failure risk)
                if model_id in used_models:
                    score *= 0.85
                # Penalize overloading same node
                if node_id in used_nodes:
                    score *= 0.80

                if score > best.score:
                    best = Assignment(
                        role_id=getattr(role, "role_id", ""),
                        model_id=model_id,
                        node_id=node_id,
                        score=score,
                        reasoning=self._explain(role, model, node, score),
                        alternatives=[],
                    )

        # Collect alternatives (next best 2)
        alt_scores = []
        for model in models:
            for node in nodes:
                s = self._score_fit(role, model, node, task)
                alt_scores.append({"model_id": model.get("model_id", ""), "node_id": node.get("node_id", ""), "score": s})

        alt_scores.sort(key=lambda x: -x["score"])
        best.alternatives = alt_scores[1:3]  # next 2 after best

        return best

    def _score_fit(self, role: Any, model: dict, node: dict, task: dict) -> float:
        """Score a role→model→node assignment across 7 dimensions."""
        scores = {}

        # Capability fit (30%)
        role_caps = set(getattr(role, "required_capabilities", []))
        model_caps = set(str(model.get("capabilities", "")).split(","))
        if role_caps:
            scores["capability"] = len(role_caps & model_caps) / len(role_caps)
        else:
            scores["capability"] = 0.8

        # Model availability (15%)
        scores["availability"] = 1.0 if model.get("status") == "healthy" else 0.3

        # Node resources (15%)
        req_mem = int(task.get("min_memory_mb", 512) or 512)
        avail_mem = int(node.get("free_memory_mb", 0) or 0)
        scores["resources"] = min(1.0, avail_mem / max(req_mem, 1))

        # Cost efficiency (10%)
        cost = float(model.get("cost_per_1k_tokens", 0.01) or 0.01)
        budget = float(task.get("budget_usd", 1.0) or 1.0)
        scores["cost"] = max(0.0, 1.0 - cost / max(budget, 0.001))

        # Latency (10%)
        lat = float(model.get("avg_latency_ms", 1000) or 1000)
        deadline = float(task.get("deadline_seconds", 300) or 300) * 1000
        scores["latency"] = max(0.0, 1.0 - lat / max(deadline, 1))

        # Privacy (10%)
        required_privacy = str(task.get("privacy_class", "internal"))
        model_privacy = str(model.get("privacy_class", "internal"))
        scores["privacy"] = 1.0 if model_privacy == required_privacy or required_privacy == "public" else 0.3

        # Performance history (10%)
        scores["history"] = float(model.get("success_rate", 0.8) or 0.8)

        # Weighted sum
        weights = {"capability": 0.30, "availability": 0.15, "resources": 0.15, "cost": 0.10, "latency": 0.10, "privacy": 0.10, "history": 0.10}
        return sum(scores.get(k, 0) * w for k, w in weights.items())

    def _explain(self, role: Any, model: dict, node: dict, score: float) -> str:
        return f"{getattr(role, 'role_id', '?')} → model={model.get('model_id', '?')} node={node.get('node_id', '?')} (score={score:.3f})"
