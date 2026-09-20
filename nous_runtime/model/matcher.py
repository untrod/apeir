"""Capability matching for model routing manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from nous_runtime.model.profile import ModelProfile
from nous_runtime.model.registry import ModelRegistry


@dataclass(frozen=True)
class ModelMatch:
    profile: ModelProfile
    score: float
    reason: str


class ModelMatcher:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def match(
        self,
        requirement: Sequence[str] | Mapping[str, object],
    ) -> list[ModelMatch]:
        if isinstance(requirement, Mapping):
            capabilities = tuple(str(item) for item in requirement.get("capabilities", ()))
            privacy = str(requirement.get("privacy") or "")
        else:
            capabilities = tuple(str(item) for item in requirement)
            privacy = ""
        matches: list[ModelMatch] = []
        for profile in self.registry.list():
            supported = sum(profile.supports(item) for item in capabilities)
            coverage = supported / len(capabilities) if capabilities else 1.0
            if privacy == "local" and profile.privacy_level != "local":
                coverage *= 0.25
            reason = f"supports {supported}/{len(capabilities)} required capabilities"
            if privacy:
                reason += f"; privacy={profile.privacy_level}"
            matches.append(ModelMatch(profile, round(coverage, 6), reason))
        return sorted(matches, key=lambda item: (-item.score, item.profile.model_id))


__all__ = ["ModelMatch", "ModelMatcher"]
