"""In-memory registry for compact model routing manifests."""

from __future__ import annotations

from nous_runtime.core.errors import CapabilityError
from nous_runtime.model.profile import ModelProfile


class ModelRegistry:
    def __init__(self, profiles: tuple[ModelProfile, ...] | list[ModelProfile] = ()):
        self._profiles: dict[str, ModelProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ModelProfile) -> ModelProfile:
        if not isinstance(profile, ModelProfile):
            raise CapabilityError("profile must be a ModelProfile")
        if profile.model_id in self._profiles:
            raise CapabilityError(f"model already registered: {profile.model_id}")
        self._profiles[profile.model_id] = profile
        return profile

    def get(self, model_id: str) -> ModelProfile | None:
        return self._profiles.get(str(model_id))

    def list(self) -> list[ModelProfile]:
        return sorted(self._profiles.values(), key=lambda profile: profile.model_id)


def default_model_registry() -> ModelRegistry:
    """Return deterministic family manifests used when no discovery store is supplied."""
    common_confidence = {
        "reasoning": 0.80,
        "coding": 0.78,
        "mathematics": 0.75,
        "vision": 0.75,
    }
    common_samples = {
        "reasoning": 30,
        "coding": 24,
        "mathematics": 20,
        "vision": 18,
    }
    return ModelRegistry(
        [
            ModelProfile(
                "claude",
                "anthropic",
                (
                    "coding",
                    "reasoning",
                    "language",
                    "planning",
                    "verification",
                    "retrieval",
                ),
                0.90,
                0.95,
                0.70,
                0.55,
                0.70,
                0.45,
                confidence=common_confidence,
                sample_count=common_samples,
                reliability_score=0.92,
                context_window=200_000,
                supports_tools=True,
                supports_structured_output=True,
                estimated_cost=6.0,
                latency_ms=1_900,
            ),
            ModelProfile(
                "deepseek",
                "deepseek",
                (
                    "reasoning",
                    "math",
                    "coding",
                    "planning",
                    "structured_output",
                ),
                0.96,
                0.88,
                0.96,
                0.10,
                0.58,
                0.86,
                confidence=common_confidence,
                sample_count=common_samples,
                reliability_score=0.88,
                context_window=128_000,
                supports_tools=True,
                supports_structured_output=True,
                estimated_cost=2.0,
                latency_ms=2_300,
            ),
            ModelProfile(
                "gpt",
                "openai",
                (
                    "reasoning",
                    "coding",
                    "vision",
                    "gpu",
                    "python",
                    "dataset",
                    "language",
                    "retrieval",
                    "tool_use",
                ),
                0.93,
                0.92,
                0.86,
                0.94,
                0.72,
                0.40,
                confidence=common_confidence,
                sample_count=common_samples,
                reliability_score=0.91,
                context_window=128_000,
                supports_tools=True,
                supports_structured_output=True,
                estimated_cost=7.0,
                latency_ms=1_600,
            ),
            ModelProfile(
                "ollama",
                "ollama",
                ("reasoning", "coding", "local_execution"),
                0.68,
                0.65,
                0.55,
                0.15,
                0.62,
                0.98,
                "local",
                confidence={"reasoning": 0.55, "coding": 0.50},
                sample_count={"reasoning": 8, "coding": 5},
                reliability_score=0.72,
                context_window=32_000,
                supports_tools=False,
                estimated_cost=0.0,
                latency_ms=900,
            ),
            ModelProfile(
                "unknown",
                "unknown",
                ("reasoning",),
                0.45,
                0.35,
                0.35,
                0.0,
                0.50,
                0.50,
                "unknown",
                reliability_score=0.45,
            ),
        ]
    )


__all__ = ["ModelRegistry", "default_model_registry"]
