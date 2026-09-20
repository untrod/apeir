import pytest

from nous_runtime.core.errors import CapabilityError
from nous_runtime.model import ModelMatcher, ModelProfile, ModelRegistry


def profile(model_id: str, capabilities: tuple[str, ...]) -> ModelProfile:
    return ModelProfile(model_id, "test", capabilities)


def test_registry_register_get_and_list() -> None:
    registry = ModelRegistry()
    beta = registry.register(profile("beta", ("reasoning",)))
    registry.register(profile("alpha", ("coding",)))

    assert registry.get("beta") is beta
    assert [item.model_id for item in registry.list()] == ["alpha", "beta"]


def test_registry_rejects_duplicate_model() -> None:
    registry = ModelRegistry([profile("same", ("reasoning",))])

    with pytest.raises(CapabilityError):
        registry.register(profile("same", ("coding",)))


def test_profile_validates_scores() -> None:
    with pytest.raises(CapabilityError):
        ModelProfile("bad", "test", reasoning_score=1.1)


def test_matcher_sorts_by_capability_coverage() -> None:
    registry = ModelRegistry([
        profile("general", ("reasoning",)),
        profile("coder", ("coding", "reasoning")),
    ])

    matches = ModelMatcher(registry).match(("coding", "reasoning"))

    assert matches[0].profile.model_id == "coder"
    assert matches[0].score == 1.0
    assert matches[1].score == 0.5


def test_matcher_applies_local_privacy_constraint() -> None:
    registry = ModelRegistry([
        ModelProfile("cloud", "test", ("reasoning",), privacy_level="cloud"),
        ModelProfile("local", "test", ("reasoning",), privacy_level="local"),
    ])

    matches = ModelMatcher(registry).match({"capabilities": ("reasoning",), "privacy": "local"})

    assert matches[0].profile.model_id == "local"
    assert matches[1].score == 0.25
