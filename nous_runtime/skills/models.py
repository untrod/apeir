"""Normalized Skill discovery records for the Work Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SkillRecord:
    """A Skill projection whose metadata never grants execution authority."""

    skill_id: str
    name: str
    description: str
    version: str
    provider: str
    source: str
    source_format: str
    digest: str
    requested_capabilities: tuple[str, ...] = ()
    suggested_tools: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    risk: str = "unknown"
    verification: tuple[str, ...] = ()
    instructions: str = ""
    resources: tuple[str, ...] = ()
    enabled: bool = True
    installed: bool = False
    trust: str = "unverified"
    artifact_ref: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.skill_id.strip():
            raise ValueError("skill_id is required")
        if not self.name.strip():
            raise ValueError("skill name is required")
        if not self.description.strip():
            raise ValueError("skill description is required")
        if not self.version.strip():
            raise ValueError("skill version is required")

    def summary(self) -> dict[str, Any]:
        """Return prompt-safe discovery data without instructions or resources."""

        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "provider": self.provider,
            "source_format": self.source_format,
            "digest": self.digest,
            "requested_capabilities": list(self.requested_capabilities),
            "suggested_tools": list(self.suggested_tools),
            "tags": list(self.tags),
            "risk": self.risk,
            "enabled": self.enabled,
            "installed": self.installed,
            "trust": self.trust,
            "artifact_ref": self.artifact_ref,
            "authority": "none",
        }

    def to_dict(self) -> dict[str, Any]:
        """Return full Skill data only after explicit progressive loading."""

        return {
            **self.summary(),
            "source": self.source,
            "verification": list(self.verification),
            "instructions": self.instructions,
            "resources": list(self.resources),
            "metadata": {**dict(self.metadata), "authority": "none"},
        }


__all__ = ["SkillRecord"]
