# -*- coding: utf-8 -*-
"""Shadow Experiment — full shadow deployment for algorithm comparison.

Distinct from intelligence shadow mode (which shadows single decisions).
This shadows entire experiment configurations: baseline vs candidate
across full task sets, collecting comprehensive metrics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShadowExperimentResult:
    experiment_id: str = ""
    shadow_id: str = ""
    total_tasks: int = 0
    baseline_results: dict[str, Any] = field(default_factory=dict)
    candidate_results: dict[str, Any] = field(default_factory=dict)
    metrics_diff: dict[str, float] = field(default_factory=dict)
    safety_violations_candidate: int = 0
    constraint_violations_candidate: int = 0
    recommendation: str = ""  # promote, investigate, reject
    evidence_artifacts: list[str] = field(default_factory=list)


class ShadowExperimentRunner:
    """Runs shadow experiments comparing baseline vs candidate at scale."""

    def run(self, experiment_spec: Any, task_set: list[dict], baseline_fn: Any, candidate_fn: Any) -> ShadowExperimentResult:
        result = ShadowExperimentResult(
            experiment_id=getattr(experiment_spec, "experiment_id", ""),
            shadow_id=f"shadow_exp_{uuid.uuid4().hex[:12]}",
            total_tasks=len(task_set),
        )

        baseline_scores = []
        candidate_scores = []
        safety_count = 0
        constraint_count = 0

        for task in task_set:
            try:
                b_result = baseline_fn(task)
                c_result = candidate_fn(task)
                baseline_scores.append(b_result.get("score", 0))
                candidate_scores.append(c_result.get("score", 0))
                if c_result.get("safety_violation"):
                    safety_count += 1
                if c_result.get("constraint_violation"):
                    constraint_count += 1
            except Exception:
                candidate_scores.append(0)

        result.baseline_results = {"avg_score": sum(baseline_scores) / max(len(baseline_scores), 1)}
        result.candidate_results = {"avg_score": sum(candidate_scores) / max(len(candidate_scores), 1)}
        result.metrics_diff = {"score_delta": result.candidate_results["avg_score"] - result.baseline_results["avg_score"]}
        result.safety_violations_candidate = safety_count
        result.constraint_violations_candidate = constraint_count

        if safety_count > 0:
            result.recommendation = "reject"
        elif result.metrics_diff["score_delta"] < -0.02:
            result.recommendation = "investigate"
        else:
            result.recommendation = "promote"

        return result
