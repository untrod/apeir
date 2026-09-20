"""Measured experiment execution and durable result summaries."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import ExperimentSpec, ExperimentState
from .statistics import StatisticalAnalyzer, StatisticalTest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ExperimentResult:
    """Evidence summary for one measured experiment run."""

    experiment_id: str = ""
    run_id: str = ""
    state: ExperimentState = ExperimentState.PROPOSED
    baseline_score: float = 0.0
    candidate_score: float = 0.0
    improvement: float = 0.0
    significant: bool = False
    p_value: float = 0.0
    effect_size: float = 0.0
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    sample_size: int = 0
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    input_digest: str = ""
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class ExperimentRunner:
    """Evaluates supplied measurements; it never manufactures benchmark scores."""

    def __init__(self, storage_dir: str | os.PathLike[str] = "") -> None:
        if storage_dir:
            root = Path(storage_dir)
        else:
            workspace = os.environ.get("NOUS_WORKSPACE_ROOT")
            root = (
                Path(workspace) / ".nous" / "experiments"
                if workspace
                else Path.home() / ".nous" / "experiments"
            )
        self._result_dir = root.expanduser().resolve() / "results"
        self._result_dir.mkdir(parents=True, exist_ok=True)

    def run_benchmark(
        self,
        spec: ExperimentSpec,
        baseline_scores: list[float],
        candidate_scores: list[float],
    ) -> ExperimentResult:
        """Compare paired measurements and persist a reproducible summary."""
        baseline = self._scores(baseline_scores, "baseline_scores")
        candidate = self._scores(candidate_scores, "candidate_scores")
        if len(baseline) != len(candidate):
            raise ValueError("baseline_scores and candidate_scores must have equal length")
        if len(baseline) < 5:
            raise ValueError("at least five paired measurements are required")
        started = _utc_now()
        try:
            test = StatisticalTest(spec.statistical_test)
        except ValueError as exc:
            raise ValueError(f"unsupported statistical test: {spec.statistical_test}") from exc
        analysis = StatisticalAnalyzer().compare(
            baseline,
            candidate,
            test=test,
            alpha=float(spec.acceptance_threshold),
        )
        digest = hashlib.sha256(
            json.dumps(
                {"baseline": baseline, "candidate": candidate},
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result = ExperimentResult(
            experiment_id=spec.experiment_id,
            run_id=f"exprun_{uuid.uuid4().hex[:12]}",
            state=ExperimentState.BENCHMARKED,
            baseline_score=analysis.mean_baseline,
            candidate_score=analysis.mean_candidate,
            improvement=analysis.mean_candidate - analysis.mean_baseline,
            significant=analysis.significant,
            p_value=analysis.p_value,
            effect_size=analysis.effect_size,
            ci_lower=analysis.ci_lower,
            ci_upper=analysis.ci_upper,
            sample_size=analysis.sample_size,
            started_at=started,
            completed_at=_utc_now(),
            input_digest=digest,
        )
        result.artifacts.append(str(self._persist(result)))
        return result

    def list_results(self, experiment_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        root = self._result_dir / experiment_id if experiment_id else self._result_dir
        paths = root.glob("*.json") if experiment_id else root.glob("*/*.json")
        ordered = sorted(paths, key=lambda path: path.stat().st_mtime_ns, reverse=True)
        records: list[dict[str, Any]] = []
        for path in ordered[: max(1, min(int(limit), 200))]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def _persist(self, result: ExperimentResult) -> Path:
        directory = self._result_dir / result.experiment_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{result.run_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return target

    @staticmethod
    def _scores(values: list[float], name: str) -> list[float]:
        if not isinstance(values, list):
            raise ValueError(f"{name} must be a list")
        try:
            scores = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must contain only numbers") from exc
        if any(not (-1_000_000 <= value <= 1_000_000) for value in scores):
            raise ValueError(f"{name} contains an out-of-range value")
        return scores
