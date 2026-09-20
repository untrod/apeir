# -*- coding: utf-8 -*-
"""Evaluation Runtime core data models.

EvaluationRecord   — top-level evaluation run
DimensionScore     — per-dimension score breakdown
EvaluationEvidence — proof for each dimension
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from nous_runtime.evaluation.schema import (
    EVALUATION_SCHEMA_VERSION,
    EvaluationStatus,
)



# EvaluationEvidence


@dataclass(frozen=True)
class EvaluationEvidence:
    """Proof supporting an evaluation dimension score.

    Example: pytest result, ruff lint output, security scan findings.
    """

    evidence_id: str = ""
    kind: str = ""               # EvidenceKind value
    dimension: str = ""          # EvaluationDimension value
    summary: str = ""            # Human-readable summary
    passed: bool = False
    score: float = 0.0           # 0.0–1.0
    detail: dict[str, Any] = field(default_factory=dict)
    source: str = ""             # e.g. "pytest", "ruff", "bandit"
    created_at: str = ""

    def __post_init__(self):
        if not self.evidence_id:
            object.__setattr__(self, "evidence_id", f"evid_{_uuid.uuid4().hex[:12]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationEvidence":
        d = dict(data)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})



# DimensionScore


@dataclass(frozen=True)
class DimensionScore:
    """Score for a single evaluation dimension."""

    dimension: str = ""          # EvaluationDimension value
    score: float = 0.0           # 0.0–1.0
    weight: float = 0.0          # Weight in composite
    weighted: float = 0.0        # score × weight
    passed: bool = False
    evidence_count: int = 0
    summary: str = ""            # Why this score
    evidence: tuple[EvaluationEvidence, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))
        object.__setattr__(self, "weighted", round(self.score * self.weight, 4))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "weight": self.weight,
            "weighted": self.weighted,
            "passed": self.passed,
            "evidence_count": self.evidence_count,
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DimensionScore":
        d = dict(data)
        raw_evidence = d.pop("evidence", [])
        evidence = tuple(EvaluationEvidence.from_dict(e) for e in raw_evidence)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(evidence=evidence, **{k: v for k, v in d.items() if k in known})



# EvaluationRecord


@dataclass(frozen=True)
class EvaluationRecord:
    """A complete evaluation run against a target.

    Target can be: Agent, Task, Project, Decision, Capability, Model, Provider.
    """

    id: str = ""
    target_type: str = ""        # TargetType value
    target_id: str = ""          # ID of the target being evaluated
    status: str = EvaluationStatus.PENDING.value

    # Input / context
    input_summary: str = ""      # What was evaluated
    criteria: tuple[str, ...] = ()   # Which dimensions were used

    # Results
    dimensions: tuple[DimensionScore, ...] = ()
    composite_score: float = 0.0
    confidence: float = 0.0

    # Decision
    recommendation: str = ""     # accept, reject, retry, improve
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    # Metadata
    created_at: str = ""
    evaluated_by: str = ""       # "system", "agent:<id>", "user:<id>"
    schema_version: str = EVALUATION_SCHEMA_VERSION
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            object.__setattr__(self, "id", f"eval_{_uuid.uuid4().hex[:16]}")
        if not self.created_at:
            object.__setattr__(self, "created_at", _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        object.__setattr__(self, "composite_score", max(0.0, min(1.0, float(self.composite_score))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))

    # computed properties

    @property
    def passed(self) -> bool:
        return self.status == EvaluationStatus.PASS.value

    @property
    def dimension_count(self) -> int:
        return len(self.dimensions)

    def checksum(self) -> str:
        h = hashlib.sha256()
        h.update(self.id.encode())
        h.update(self.target_type.encode())
        h.update(self.target_id.encode())
        h.update(self.status.encode())
        h.update(str(self.composite_score).encode())
        for d in sorted(self.dimensions, key=lambda d: d.dimension):
            h.update(d.dimension.encode())
            h.update(str(d.score).encode())
        return h.hexdigest()

    # serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "status": self.status,
            "input_summary": self.input_summary,
            "criteria": list(self.criteria),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "evaluated_by": self.evaluated_by,
            "schema_version": self.schema_version,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
            "passed": self.passed,
            "checksum": self.checksum(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationRecord":
        d = dict(data)
        raw_dims = d.pop("dimensions", [])
        dimensions = tuple(DimensionScore.from_dict(dim) for dim in raw_dims)
        criteria = tuple(d.pop("criteria", []))
        issues = tuple(d.pop("issues", []))
        warnings = tuple(d.pop("warnings", []))
        for k in ("passed", "checksum"):
            d.pop(k, None)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(
            dimensions=dimensions, criteria=criteria,
            issues=issues, warnings=warnings,
            **{k: v for k, v in d.items() if k in known},
        )

    # mutation (immutable)

    def with_status(self, status: EvaluationStatus) -> "EvaluationRecord":
        return EvaluationRecord(
            id=self.id, target_type=self.target_type, target_id=self.target_id,
            status=status.value,
            input_summary=self.input_summary, criteria=self.criteria,
            dimensions=self.dimensions,
            composite_score=self.composite_score, confidence=self.confidence,
            recommendation=self.recommendation,
            issues=self.issues, warnings=self.warnings,
            created_at=self.created_at, evaluated_by=self.evaluated_by,
            schema_version=self.schema_version, duration_ms=self.duration_ms,
            metadata=dict(self.metadata),
        )
