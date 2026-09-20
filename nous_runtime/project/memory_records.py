# -*- coding: utf-8 -*-
"""Canonical project memory record types."""

from __future__ import annotations

import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime as _dt, timezone as _tz
from typing import Any, Literal

from nous_runtime.schema_registry import MEMORY_RECORDS_SCHEMA_VERSION as SCHEMA_VERSION

MemorySource = Literal["observation", "task", "plan", "user", "runtime", "artifact"]


@dataclass
class MemoryRecord:
    """Base serializable memory record."""

    source_type: MemorySource
    project_id: str = ""
    task_graph_id: str = ""
    task_id: str = ""
    observation_id: str = ""
    capability_id: str = ""
    provider_id: str = ""
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    memory_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.memory_id:
            self.memory_id = f"mem_{_uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.confidence = max(0.0, min(float(self.confidence), 1.0))

    @property
    def record_type(self) -> str:
        return self.__class__.__name__.replace("Memory", "").lower()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.memory_id:
            errors.append("memory_id is required")
        if not self.source_type:
            errors.append("source_type is required")
        if self.confidence < 0 or self.confidence > 1:
            errors.append("confidence must be between 0 and 1")
        return errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["record_type"] = self.record_type
        return data


@dataclass
class MemoryEvent(MemoryRecord):
    event_type: str = ""
    detail: str = ""

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.event_type:
            errors.append("event_type is required")
        return errors


@dataclass
class MemoryFact(MemoryRecord):
    key: str = ""
    value: Any = ""
    stable_key: str = ""
    supersedes: str = ""
    active: bool = True

    def __post_init__(self):
        super().__post_init__()
        if not self.stable_key:
            self.stable_key = self.key

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.key:
            errors.append("key is required")
        return errors


@dataclass
class MemoryDecision(MemoryRecord):
    question: str = ""
    answer: str = ""
    rationale: str = ""

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.question:
            errors.append("question is required")
        if not self.answer:
            errors.append("answer is required")
        return errors


@dataclass
class MemorySummary(MemoryRecord):
    title: str = ""
    content: str = ""

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.content:
            errors.append("content is required")
        return errors


@dataclass
class MemoryExperience(MemoryRecord):
    capability_id: str = ""
    provider_id: str = ""
    outcome: str = ""
    error_code: str = ""
    count: int = 1


@dataclass
class MemoryArtifactRef(MemoryRecord):
    artifact_id: str = ""
    path: str = ""
    kind: str = ""
    description: str = ""
