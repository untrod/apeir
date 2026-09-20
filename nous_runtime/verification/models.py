"""Serializable contracts for verification and bounded repair."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from nous_runtime.artifact import Artifact


class VerificationPhase(str, Enum):
    CREATED = "created"
    GENERATED = "generated"
    VERIFIED = "verified"
    CRITIQUED = "critiqued"
    REPAIRED = "repaired"
    WAITING_APPROVAL = "waiting_approval"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    message: str
    verifier: str
    severity: IssueSeverity = IssueSeverity.ERROR
    path: str = ""
    repairable: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerificationIssue":
        return cls(
            code=str(data["code"]),
            message=str(data["message"]),
            verifier=str(data["verifier"]),
            severity=IssueSeverity(str(data.get("severity") or "error")),
            path=str(data.get("path") or ""),
            repairable=bool(data.get("repairable", True)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class VerifierResult:
    verifier: str
    accepted: bool
    score: float
    issues: tuple[VerificationIssue, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))


@dataclass(frozen=True)
class VerificationReport:
    accepted: bool
    score: float
    results: tuple[VerifierResult, ...]
    issues: tuple[VerificationIssue, ...]


@dataclass(frozen=True)
class VerificationCandidate:
    output: Any
    artifacts: tuple[Artifact, ...] = ()
    version: int = 1
    candidate_id: str = field(
        default_factory=lambda: f"candidate_{uuid.uuid4().hex}"
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Critique:
    summary: str
    issues: tuple[VerificationIssue, ...]
    repair_instructions: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairRecord:
    attempt: int
    source_candidate_id: str
    repaired_candidate_id: str
    critique: Critique


@dataclass(frozen=True)
class HumanApproval:
    decision: ApprovalDecision
    approver_id: str = ""
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class VerificationRun:
    run_id: str = field(
        default_factory=lambda: f"verify_{uuid.uuid4().hex}"
    )
    phase: VerificationPhase = VerificationPhase.CREATED
    candidates: list[VerificationCandidate] = field(default_factory=list)
    reports: list[VerificationReport] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    repairs: list[RepairRecord] = field(default_factory=list)
    phase_history: list[VerificationPhase] = field(
        default_factory=lambda: [VerificationPhase.CREATED]
    )
    approval: HumanApproval | None = None
    accepted_output: Any = None
    error: str = ""

    def transition(self, phase: VerificationPhase) -> None:
        self.phase = phase
        self.phase_history.append(phase)


__all__ = [
    "ApprovalDecision",
    "Critique",
    "HumanApproval",
    "IssueSeverity",
    "RepairRecord",
    "VerificationCandidate",
    "VerificationIssue",
    "VerificationPhase",
    "VerificationReport",
    "VerificationRun",
    "VerifierResult",
]
