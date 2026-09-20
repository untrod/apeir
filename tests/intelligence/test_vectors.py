import math

import pytest

from nous_runtime.core.errors import CapabilityError
from nous_runtime.intelligence.scoring import (
    InvalidRoutingConfigurationError,
    ModelCapabilityVector,
    TaskRequirementVector,
    build_model_vector,
    build_task_vector,
)
from nous_runtime.intelligence.task import analyze_task
from nous_runtime.model import ModelProfile


def test_task_vector_maps_analyzer_dimensions() -> None:
    vector = build_task_vector(analyze_task("Prove a math equation", task_id="m"))

    assert vector.dimensions["mathematics"] == 1.0
    assert vector.dimensions["reasoning"] == 0.8
    assert vector.required_capabilities == frozenset(
        {"mathematics", "reasoning"}
    )


def test_task_vector_maps_complexity_and_risk() -> None:
    analysis = analyze_task("Write code", task_id="c")
    analysis = type(analysis)(
        **{
            **analysis.__dict__,
            "complexity": "high",
            "constraints": {"risk_level": 0.9},
        }
    )

    vector = build_task_vector(analysis)

    assert vector.complexity == 0.85
    assert vector.risk_level == 0.9


def test_model_vector_maps_legacy_profile_fields() -> None:
    profile = ModelProfile(
        "model-a",
        "provider-a",
        ("reasoning", "coding"),
        reasoning_score=0.9,
        coding_score=0.8,
        sample_count={"reasoning": 12},
    )

    vector = build_model_vector(profile)

    assert vector.dimensions["reasoning"] == 0.9
    assert vector.dimensions["coding"] == 0.8
    assert vector.sample_count["reasoning"] == 12
    assert not vector.cold_start


def test_cold_start_model_uses_nonzero_conservative_prior() -> None:
    vector = build_model_vector(
        ModelProfile("brand-new", "new-provider", ("reasoning",))
    )

    assert vector.dimensions["reasoning"] > 0
    assert vector.confidence["reasoning"] > 0
    assert vector.cold_start


def test_custom_model_dimensions_are_preserved_with_warning() -> None:
    vector = build_model_vector(
        ModelProfile(
            "custom",
            "provider",
            ("reasoning",),
            dimensions={"quantum_simulation": 0.77},
        )
    )

    assert vector.dimensions["quantum_simulation"] == 0.77
    assert "unknown_dimension:quantum_simulation" in vector.warnings


def test_vectors_round_trip_through_serializable_dicts() -> None:
    task = build_task_vector(analyze_task("Write code", task_id="task"))
    model = build_model_vector(
        ModelProfile("model", "provider", ("coding", "reasoning"))
    )

    assert TaskRequirementVector.from_dict(task.to_dict()) == task
    assert ModelCapabilityVector.from_dict(model.to_dict()) == model


def test_vector_rejects_invalid_values_and_counts() -> None:
    with pytest.raises(InvalidRoutingConfigurationError):
        TaskRequirementVector({"reasoning": math.inf}, {"reasoning": 1.0})
    with pytest.raises(InvalidRoutingConfigurationError):
        ModelCapabilityVector("model", {"reasoning": 0.5}, sample_count={"reasoning": -1})


def test_profile_rejects_nan() -> None:
    with pytest.raises(CapabilityError):
        ModelProfile("bad", "provider", reasoning_score=math.nan)
