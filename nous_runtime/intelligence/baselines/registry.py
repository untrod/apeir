# -*- coding: utf-8 -*-
"""Baseline algorithm registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class BaselinePolicy(Protocol):
    """Protocol that all baselines must implement."""

    name: str
    description: str

    def select_model(
        self,
        task: dict[str, Any],
        available_models: list[dict[str, Any]],
    ) -> dict[str, Any] | None: ...

    def select_node(
        self,
        task: dict[str, Any],
        available_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None: ...

    def should_verify(self, task: dict[str, Any]) -> bool: ...

    def agent_topology(self, task: dict[str, Any]) -> list[str]: ...


@dataclass
class BaselineRecord:
    name: str
    description: str
    category: str          # model_selection, agent_topology, node_assignment, verification, locality
    policy: BaselinePolicy | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaselineRegistry:
    """Registry of all baseline algorithm implementations."""

    def __init__(self) -> None:
        self._baselines: dict[str, BaselineRecord] = {}
        self._load_builtins()

    def register(self, record: BaselineRecord) -> None:
        self._baselines[record.name] = record

    def get(self, name: str) -> BaselineRecord | None:
        return self._baselines.get(name)

    def list_all(self) -> list[BaselineRecord]:
        return sorted(self._baselines.values(), key=lambda b: b.name)

    def list_by_category(self, category: str) -> list[BaselineRecord]:
        return [b for b in self._baselines.values() if b.category == category]

    def _load_builtins(self) -> None:
        """Load all 14 built-in baselines."""
        from .implementations import ALL_BASELINES
        for policy in ALL_BASELINES:
            self.register(BaselineRecord(
                name=policy.name,
                description=policy.description,
                category=self._categorize(policy.name),
                policy=policy,
            ))

    @staticmethod
    def _categorize(name: str) -> str:
        cats = {
            "fixed_strongest": "model_selection",
            "fixed_cheapest": "model_selection",
            "fixed_fastest": "model_selection",
            "random_model": "model_selection",
            "round_robin": "model_selection",
            "manual_rule": "model_selection",
            "weighted_scalar": "model_selection",
            "single_agent": "agent_topology",
            "fixed_planner_worker_reviewer": "agent_topology",
            "fixed_node": "node_assignment",
            "no_verification": "verification",
            "always_verify": "verification",
            "local_only": "locality",
            "cloud_only": "locality",
        }
        return cats.get(name, "unknown")
