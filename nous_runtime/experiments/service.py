"""Application service for experiment creation, evaluation, and evidence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .registry import ExperimentRegistry, ExperimentSpec, ExperimentState
from .runner import ExperimentRunner


class ExperimentService:
    """Shared service used by API and future Studio clients."""

    def __init__(self, workspace_root: str | os.PathLike[str] = "") -> None:
        workspace = Path(workspace_root or os.environ.get("NOUS_WORKSPACE_ROOT") or Path.home())
        storage = (
            workspace / ".nous" / "experiments"
            if workspace_root or os.environ.get("NOUS_WORKSPACE_ROOT")
            else Path.home() / ".nous" / "experiments"
        )
        self.registry = ExperimentRegistry(storage)
        self.runner = ExperimentRunner(storage)

    def create(self, values: dict[str, Any]) -> ExperimentSpec:
        hypothesis = str(values.get("hypothesis") or "").strip()
        baseline = str(values.get("baseline_name") or "").strip()
        candidate = str(values.get("candidate_name") or "").strip()
        if not hypothesis or not baseline or not candidate:
            raise ValueError("hypothesis, baseline_name, and candidate_name are required")
        spec = ExperimentSpec(
            hypothesis=hypothesis,
            baseline_name=baseline,
            candidate_name=candidate,
            dataset_id=str(values.get("dataset_id") or "").strip(),
            metrics=[str(item) for item in values.get("metrics", []) if str(item).strip()],
            owner=str(values.get("owner") or "local").strip(),
            statistical_test=str(values.get("statistical_test") or "bootstrap"),
            acceptance_threshold=float(values.get("acceptance_threshold", 0.05)),
            metadata=dict(values.get("metadata") or {}),
        )
        self.registry.register(spec)
        return spec

    def evaluate(
        self,
        experiment_id: str,
        baseline_scores: list[float],
        candidate_scores: list[float],
    ) -> dict[str, Any]:
        spec = self.registry.get(experiment_id)
        if spec is None:
            raise KeyError(experiment_id)
        result = self.runner.run_benchmark(spec, baseline_scores, candidate_scores)
        spec.state = ExperimentState.BENCHMARKED
        spec.sample_size = result.sample_size
        spec.metadata = {
            **spec.metadata,
            "last_result": {
                "run_id": result.run_id,
                "improvement": result.improvement,
                "significant": result.significant,
                "p_value": result.p_value,
            },
        }
        self.registry.save(spec)
        return result.to_dict()

    def snapshot(self) -> dict[str, Any]:
        experiments = self.registry.list()
        return {
            "experiments": [item.to_dict() for item in experiments],
            "results": self.runner.list_results(limit=100),
            "summary": {
                "total": len(experiments),
                "benchmarked": sum(item.state is ExperimentState.BENCHMARKED for item in experiments),
                "production": sum(item.state is ExperimentState.PRODUCTION for item in experiments),
            },
        }


__all__ = ["ExperimentService"]
