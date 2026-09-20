from __future__ import annotations

import json

import pytest

from nous_runtime.experiments import (
    ExperimentRegistry,
    ExperimentRunner,
    ExperimentService,
    ExperimentSpec,
    ExperimentState,
)


def test_registry_persists_across_instances(tmp_path):
    first = ExperimentRegistry(tmp_path)
    spec = ExperimentSpec(
        hypothesis="Candidate improves verified completion",
        baseline_name="baseline",
        candidate_name="candidate",
    )
    experiment_id = first.register(spec)

    restored = ExperimentRegistry(tmp_path).get(experiment_id)

    assert restored is not None
    assert restored.hypothesis == spec.hypothesis
    assert ExperimentRegistry(tmp_path).count() == 1


def test_registry_rejects_path_traversal(tmp_path):
    registry = ExperimentRegistry(tmp_path)
    with pytest.raises(ValueError, match="invalid experiment id"):
        registry.get("../outside")


def test_runner_uses_supplied_measurements_and_writes_summary(tmp_path):
    spec = ExperimentSpec(
        experiment_id="exp_measured",
        hypothesis="Measured candidate is better",
        baseline_name="base",
        candidate_name="candidate",
    )
    result = ExperimentRunner(tmp_path).run_benchmark(
        spec,
        [0.50, 0.55, 0.52, 0.51, 0.54, 0.53],
        [0.70, 0.72, 0.69, 0.71, 0.73, 0.74],
    )

    assert result.baseline_score == pytest.approx(0.525)
    assert result.candidate_score == pytest.approx(0.715)
    assert result.sample_size == 6
    assert result.input_digest
    artifact = tmp_path / "results" / spec.experiment_id / f"{result.run_id}.json"
    assert json.loads(artifact.read_text(encoding="utf-8"))["input_digest"] == result.input_digest


def test_runner_refuses_missing_or_unpaired_evidence(tmp_path):
    runner = ExperimentRunner(tmp_path)
    spec = ExperimentSpec(experiment_id="exp_invalid")
    with pytest.raises(ValueError, match="at least five"):
        runner.run_benchmark(spec, [1.0], [1.1])
    with pytest.raises(ValueError, match="equal length"):
        runner.run_benchmark(spec, [1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6])


def test_service_evaluation_updates_durable_state(tmp_path):
    service = ExperimentService(tmp_path)
    spec = service.create({
        "hypothesis": "Candidate reduces error",
        "baseline_name": "v1",
        "candidate_name": "v2",
    })

    result = service.evaluate(
        spec.experiment_id,
        [0.4, 0.5, 0.6, 0.5, 0.4],
        [0.6, 0.7, 0.8, 0.7, 0.6],
    )
    restored = service.registry.get(spec.experiment_id)

    assert result["state"] == ExperimentState.BENCHMARKED.value
    assert restored is not None
    assert restored.state is ExperimentState.BENCHMARKED
    assert restored.metadata["last_result"]["run_id"] == result["run_id"]
