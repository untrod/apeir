# -*- coding: utf-8 -*-
"""Quality Gate — lightweight pass/fail check before accepting results.

Used as a pre-commit or post-execution quality barrier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.evaluation.models import EvaluationRecord
from nous_runtime.evaluation.schema import EvaluationStatus


@dataclass
class QualityGateResult:
    """Result of a quality gate check."""
    passed: bool = False
    score: float = 0.0
    status: str = ""
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "warnings": self.warnings,
            "message": self.message,
        }


class QualityGate:
    """Quality gate that blocks low-quality results.

    Usage::

        gate = QualityGate(min_score=0.70)
        result = gate.check(evaluation_record)
        if not result.passed:
            print(f"Blocked: {result.message}")
    """

    def __init__(self, min_score: float = 0.70, require_all_dimensions: bool = False):
        self._min_score = min_score
        self._require_all = require_all_dimensions

    def check(self, record: EvaluationRecord) -> QualityGateResult:
        """Check if an evaluation record passes the quality gate."""
        blocked: list[str] = []
        warnings: list[str] = []

        # Composite score check
        if record.composite_score < self._min_score:
            blocked.append(
                f"Composite score {record.composite_score:.2f} below minimum {self._min_score:.2f}"
            )

        # Individual dimension checks
        for d in record.dimensions:
            if not d.passed and d.evidence_count > 0:
                if d.weight >= 0.15:  # High-weight dimensions are blocking
                    blocked.append(f"[{d.dimension}] failed (score={d.score:.2f})")
                else:
                    warnings.append(f"[{d.dimension}] borderline (score={d.score:.2f})")

        # Status check
        if record.status == EvaluationStatus.FAIL.value:
            blocked.append("Evaluation status is FAIL")
        elif record.status == EvaluationStatus.HUMAN_REVIEW.value:
            blocked.append("Human review required")

        passed = len(blocked) == 0
        message = "Quality gate passed." if passed else f"Quality gate blocked: {'; '.join(blocked)}"

        return QualityGateResult(
            passed=passed,
            score=record.composite_score,
            status=record.status,
            blocked_by=blocked,
            warnings=warnings,
            message=message,
        )


def quality_gate_check(record: EvaluationRecord, min_score: float = 0.70) -> QualityGateResult:
    """One-shot quality gate check."""
    return QualityGate(min_score=min_score).check(record)
