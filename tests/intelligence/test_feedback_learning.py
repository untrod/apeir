from datetime import datetime, timedelta, timezone

import pytest

from nous_runtime.intelligence.decisions import (
    BetaPosterior,
    FeedbackLearner,
    FeedbackLearningConfig,
    FeedbackObservation,
)
from nous_runtime.intelligence.scoring import (
    DuplicateFeedbackError,
    InvalidFeedbackError,
)
from nous_runtime.model import ModelProfile


def observation(**overrides) -> FeedbackObservation:
    values = {
        "decision_id": "decision-1",
        "task_id": "task-1",
        "model_id": "model-1",
        "task_type": "coding",
        "capability_dimensions": {"coding": 1.0},
        "success": True,
        "source": "test_execution",
        "feedback_type": "test_result",
    }
    values.update(overrides)
    return FeedbackObservation(**values)


def test_beta_success_and_failure_updates_are_smoothed() -> None:
    prior = BetaPosterior(1, 1)
    success = prior.update(True)
    failure = prior.update(False)

    assert success.expected_success == pytest.approx(2 / 3, abs=1e-6)
    assert failure.expected_success == pytest.approx(1 / 3, abs=1e-6)
    assert success.expected_success < 1.0
    assert failure.expected_success > 0.0


def test_feedback_updates_beta_and_separate_ema_metrics() -> None:
    learner = FeedbackLearner(
        known_decision_ids={"decision-1", "decision-2"}
    )
    state = learner.record_feedback(
        observation(quality_score=0.8, latency_ms=1000, cost=2.0)
    )
    learner.record_feedback(
        observation(
            decision_id="decision-2",
            source="human_explicit",
            feedback_type="rating",
            quality_score=0.4,
            latency_ms=2000,
            cost=4.0,
        )
    )

    updated = learner.state_for("model-1")
    assert state.success_by_dimension["coding"].expected_success > 0.5
    assert updated.quality.value == pytest.approx(0.72)
    assert updated.latency_ms.value == pytest.approx(1200)
    assert updated.cost.value == pytest.approx(2.4)


def test_duplicate_feedback_is_idempotently_rejected() -> None:
    learner = FeedbackLearner()
    item = observation()
    learner.record_feedback(item)

    with pytest.raises(DuplicateFeedbackError):
        learner.record_feedback(item)

    assert learner.state_for("model-1").observation_count == 1


def test_unknown_decision_is_rejected_when_registry_is_enabled() -> None:
    learner = FeedbackLearner(known_decision_ids={"known"})

    with pytest.raises(InvalidFeedbackError):
        learner.record_feedback(observation(decision_id="missing"))


@pytest.mark.parametrize(
    "changes",
    [
        {"model_id": ""},
        {"quality_score": 1.2},
        {"latency_ms": -1},
        {"cost": -0.1},
        {"correction_count": -1},
    ],
)
def test_invalid_feedback_is_rejected(changes) -> None:
    with pytest.raises(InvalidFeedbackError):
        FeedbackLearner().record_feedback(observation(**changes))


def test_future_feedback_is_rejected() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(InvalidFeedbackError):
        FeedbackLearner().record_feedback(observation(timestamp=future))


def test_self_review_cannot_reinforce_same_model() -> None:
    with pytest.raises(InvalidFeedbackError):
        FeedbackLearner().record_feedback(
            observation(
                source="model_reviewer",
                reviewer_model_id="model-1",
            )
        )


def test_time_decay_is_configurable_and_defaults_off() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=30)
    no_decay = FeedbackLearner(
        FeedbackLearningConfig(decay_rate=0.0)
    ).record_feedback(observation(timestamp=old))
    decayed = FeedbackLearner(
        FeedbackLearningConfig(decay_rate=0.000001)
    ).record_feedback(observation(timestamp=old))

    assert (
        no_decay.success_by_dimension["coding"].expected_success
        > decayed.success_by_dimension["coding"].expected_success
    )


def test_feedback_learning_updates_immutable_model_profile() -> None:
    learner = FeedbackLearner()
    learner.record_feedback(
        observation(quality_score=0.9, latency_ms=800, cost=1.5)
    )
    original = ModelProfile("model-1", "provider", ("coding",))

    updated = learner.apply_to_profile(original)

    assert updated is not original
    assert updated.dimensions["coding"] > 0.5
    assert updated.sample_count["coding"] >= 1
    assert updated.profile_version == "feedback-v1"
    assert updated.latency_ms == 800
    assert updated.estimated_cost == 1.5
