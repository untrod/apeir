# -*- coding: utf-8 -*-
"""Experience Runtime core data models.

ExperienceRecord   — a single learned experience
ExperiencePattern  — a discovered recurring pattern
PolicyProposal     — a suggested policy improvement
Recommendation     — a user-facing recommendation
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from nous_runtime.experience.schema import (
    EXPERIENCE_SCHEMA_VERSION,
    ExperienceStatus,
)


def _now() -> str:
    return _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



# ExperienceRecord


@dataclass(frozen=True)
class ExperienceRecord:
    """A single learned experience from execution history.

    Captures: what was tried, what happened, what was learned.
    """

    id: str = ""
    source_type: str = ""          # ExperienceSource value
    task_type: str = ""            # e.g. "coding", "deployment", "debugging"
    task_summary: str = ""         # Human-readable task description
    context_hash: str = ""         # Hash of context for similarity matching

    # Action
    action: str = ""               # What was done
    agent_id: str = ""
    provider_id: str = ""
    capability_id: str = ""

    # Result
    result: str = ""               # "success", "failure", "partial"
    evaluation_score: float = 0.0
    success: bool = False
    failure_reason: str = ""       # Why it failed (if applicable)
    error_code: str = ""

    # Learning
    lessons: tuple[str, ...] = ()  # What was learned
    confidence: float = 0.5
    status: str = ExperienceStatus.NEW.value

    # References
    decision_id: str = ""
    evaluation_id: str = ""
    tags: tuple[str, ...] = ()

    # Metadata
    created_at: str = ""
    updated_at: str = ""
    occurrence_count: int = 1
    schema_version: str = EXPERIENCE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"exp_{_uuid.uuid4().hex[:16]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _now())
        if not self.updated_at:
            object.__setattr__(self, "updated_at", _now())
        object.__setattr__(self, "evaluation_score", max(0.0, min(1.0, float(self.evaluation_score))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.task_type:
            errors.append("task_type is required")
        if not self.action:
            errors.append("action is required")
        if self.confidence < 0 or self.confidence > 1:
            errors.append("confidence must be 0.0–1.0")
        return errors

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lessons"] = list(self.lessons)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperienceRecord":
        d = dict(data)
        d["lessons"] = tuple(d.pop("lessons", []))
        d["tags"] = tuple(d.pop("tags", []))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def checksum(self) -> str:
        h = hashlib.sha256()
        h.update(self.id.encode())
        h.update(self.task_type.encode())
        h.update(self.action.encode())
        h.update(self.result.encode())
        h.update(str(self.evaluation_score).encode())
        return h.hexdigest()



# ExperiencePattern


@dataclass(frozen=True)
class ExperiencePattern:
    """A recurring pattern discovered from multiple experiences."""

    id: str = ""
    pattern_type: str = ""         # PatternType value
    name: str = ""                 # Human-readable pattern name
    description: str = ""          # What the pattern describes
    frequency: int = 0             # How many times observed
    success_rate: float = 0.0      # How often it succeeds
    confidence: float = 0.0
    source_experiences: tuple[str, ...] = ()  # ExperienceRecord IDs
    related_patterns: tuple[str, ...] = ()    # Related pattern IDs
    tags: tuple[str, ...] = ()
    created_at: str = ""
    schema_version: str = EXPERIENCE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"pat_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _now())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_experiences"] = list(self.source_experiences)
        d["related_patterns"] = list(self.related_patterns)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperiencePattern":
        d = dict(data)
        d["source_experiences"] = tuple(d.pop("source_experiences", []))
        d["related_patterns"] = tuple(d.pop("related_patterns", []))
        d["tags"] = tuple(d.pop("tags", []))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})



# PolicyProposal


@dataclass(frozen=True)
class PolicyProposal:
    """A suggested policy improvement derived from experience.

    Must pass Governance before being applied.
    """

    id: str = ""
    title: str = ""
    description: str = ""
    target_policy: str = ""        # Which policy to modify
    proposed_change: str = ""      # What to change
    supporting_experiences: tuple[str, ...] = ()  # Experience IDs backing this
    confidence: float = 0.0
    expected_impact: str = ""      # e.g. "+5% success rate"
    status: str = "proposed"       # proposed, approved, rejected, applied
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"pol_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _now())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["supporting_experiences"] = list(self.supporting_experiences)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyProposal":
        d = dict(data)
        d["supporting_experiences"] = tuple(d.pop("supporting_experiences", []))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})



# Recommendation


@dataclass(frozen=True)
class Recommendation:
    """A user-facing recommendation based on experience."""

    id: str = ""
    recommendation_type: str = ""  # RecommendationType value
    title: str = ""
    description: str = ""
    suggested_agent: str = ""
    suggested_provider: str = ""
    suggested_approach: str = ""
    confidence: float = 0.0
    reason: str = ""               # Why this is recommended
    supporting_experiences: tuple[str, ...] = ()
    supporting_patterns: tuple[str, ...] = ()
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"rec_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _now())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["supporting_experiences"] = list(self.supporting_experiences)
        d["supporting_patterns"] = list(self.supporting_patterns)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recommendation":
        d = dict(data)
        d["supporting_experiences"] = tuple(d.pop("supporting_experiences", []))
        d["supporting_patterns"] = tuple(d.pop("supporting_patterns", []))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})
