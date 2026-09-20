# -*- coding: utf-8 -*-
"""Evaluation Criteria Engine — defines "what good means."

Dimensions:
  Correctness     0.30 — tests pass, type checks, compilation
  Reliability     0.20 — stability, no flakes, consistent behavior
  Security        0.20 — no vulnerabilities, safe code
  Performance     0.15 — speed, resource usage
  Maintainability 0.15 — code quality, linting, complexity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nous_runtime.evaluation.schema import (
    DEFAULT_QUALITY_WEIGHTS,
    EvaluationDimension,
)

_log = logging.getLogger("nous.evaluation.criteria")



# Criterion definition


@dataclass(frozen=True)
class Criterion:
    """A single evaluation criterion within a dimension."""

    key: str = ""                # Unique key, e.g. "pytest", "ruff", "bandit"
    dimension: str = ""          # EvaluationDimension value
    label: str = ""              # Human-readable label
    description: str = ""        # What this criterion checks
    weight_in_dimension: float = 1.0  # Weight within its dimension
    threshold_pass: float = 0.8       # Minimum score for pass
    threshold_warn: float = 0.5       # Minimum score for warning

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "dimension": self.dimension,
            "label": self.label,
            "description": self.description,
            "weight_in_dimension": self.weight_in_dimension,
            "threshold_pass": self.threshold_pass,
            "threshold_warn": self.threshold_warn,
        }



# Standard criteria set


STANDARD_CRITERIA: dict[str, Criterion] = {
    # -- Correctness --
    "pytest": Criterion(
        key="pytest", dimension=EvaluationDimension.CORRECTNESS.value,
        label="Unit Tests", description="All unit tests pass.",
        weight_in_dimension=0.40, threshold_pass=0.95,
    ),
    "compile": Criterion(
        key="compile", dimension=EvaluationDimension.CORRECTNESS.value,
        label="Compilation", description="Code compiles without errors.",
        weight_in_dimension=0.30, threshold_pass=1.0,
    ),
    "type_check": Criterion(
        key="type_check", dimension=EvaluationDimension.CORRECTNESS.value,
        label="Type Checking", description="Static type analysis passes.",
        weight_in_dimension=0.15, threshold_pass=0.90,
    ),
    "schema_check": Criterion(
        key="schema_check", dimension=EvaluationDimension.CORRECTNESS.value,
        label="Schema Validation", description="Output matches expected schema.",
        weight_in_dimension=0.15, threshold_pass=1.0,
    ),

    # -- Reliability --
    "flake_check": Criterion(
        key="flake_check", dimension=EvaluationDimension.RELIABILITY.value,
        label="Flake Detection", description="No flaky tests detected.",
        weight_in_dimension=0.35, threshold_pass=0.95,
    ),
    "retry_rate": Criterion(
        key="retry_rate", dimension=EvaluationDimension.RELIABILITY.value,
        label="Retry Rate", description="Low retry rate in execution.",
        weight_in_dimension=0.35, threshold_pass=0.90,
    ),
    "consistency": Criterion(
        key="consistency", dimension=EvaluationDimension.RELIABILITY.value,
        label="Consistency", description="Cross-store data consistency.",
        weight_in_dimension=0.30, threshold_pass=0.90,
    ),

    # -- Security --
    "security_scan": Criterion(
        key="security_scan", dimension=EvaluationDimension.SECURITY.value,
        label="Security Scan", description="No HIGH or CRITICAL vulnerabilities.",
        weight_in_dimension=0.50, threshold_pass=0.95,
    ),
    "governance_check": Criterion(
        key="governance_check", dimension=EvaluationDimension.SECURITY.value,
        label="Governance", description="All actions pass governance gate.",
        weight_in_dimension=0.30, threshold_pass=1.0,
    ),
    "permission_check": Criterion(
        key="permission_check", dimension=EvaluationDimension.SECURITY.value,
        label="Permissions", description="No unauthorized access detected.",
        weight_in_dimension=0.20, threshold_pass=1.0,
    ),

    # -- Performance --
    "latency": Criterion(
        key="latency", dimension=EvaluationDimension.PERFORMANCE.value,
        label="Latency", description="Response time within acceptable range.",
        weight_in_dimension=0.40, threshold_pass=0.80,
    ),
    "resource_usage": Criterion(
        key="resource_usage", dimension=EvaluationDimension.PERFORMANCE.value,
        label="Resource Usage", description="Memory/CPU within limits.",
        weight_in_dimension=0.30, threshold_pass=0.80,
    ),
    "benchmark": Criterion(
        key="benchmark", dimension=EvaluationDimension.PERFORMANCE.value,
        label="Benchmark", description="Performance benchmark passes.",
        weight_in_dimension=0.30, threshold_pass=0.90,
    ),

    # -- Maintainability --
    "ruff": Criterion(
        key="ruff", dimension=EvaluationDimension.MAINTAINABILITY.value,
        label="Linting", description="Code passes linter checks.",
        weight_in_dimension=0.35, threshold_pass=1.0,
    ),
    "complexity": Criterion(
        key="complexity", dimension=EvaluationDimension.MAINTAINABILITY.value,
        label="Complexity", description="Code complexity within acceptable range.",
        weight_in_dimension=0.35, threshold_pass=0.80,
    ),
    "documentation": Criterion(
        key="documentation", dimension=EvaluationDimension.MAINTAINABILITY.value,
        label="Documentation", description="Code is adequately documented.",
        weight_in_dimension=0.30, threshold_pass=0.70,
    ),
}



# Criteria Registry


class CriteriaRegistry:
    """Registry of evaluation criteria with dimension grouping.

    Usage::

        registry = CriteriaRegistry()
        dims = registry.get_dimensions()
        criteria = registry.get_criteria_for("correctness")
    """

    def __init__(self, criteria: dict[str, Criterion] | None = None):
        self._criteria = criteria or dict(STANDARD_CRITERIA)

    def get(self, key: str) -> Criterion | None:
        return self._criteria.get(key)

    def list_all(self) -> list[Criterion]:
        return list(self._criteria.values())

    def get_criteria_for(self, dimension: str) -> list[Criterion]:
        """Get all criteria for a given dimension."""
        return [c for c in self._criteria.values() if c.dimension == dimension]

    def get_dimensions(self) -> list[str]:
        """Get all unique dimensions in the registry."""
        return sorted({c.dimension for c in self._criteria.values()})

    def dimension_weights(self) -> dict[str, float]:
        """Return default weights for all dimensions."""
        return {
            dim.value: weight
            for dim, weight in DEFAULT_QUALITY_WEIGHTS.items()
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria": {k: v.to_dict() for k, v in self._criteria.items()},
            "dimension_weights": self.dimension_weights(),
        }
