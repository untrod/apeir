# -*- coding: utf-8 -*-
"""Quality Scoring Engine — unified scoring across all dimensions.

Formula:
  Quality Score = 0.30 × Correctness + 0.20 × Reliability + 0.20 × Security
                + 0.15 × Performance + 0.15 × Maintainability

Outputs: composite score, dimension breakdown, explainable reasoning.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nous_runtime.evaluation.criteria import CriteriaRegistry
from nous_runtime.evaluation.exceptions import EvaluationScoringError
from nous_runtime.evaluation.models import (
    DimensionScore,
    EvaluationEvidence,
    EvaluationRecord,
)
from nous_runtime.evaluation.schema import (
    DEFAULT_QUALITY_WEIGHTS,
    EvaluationDimension,
    EvaluationStatus,
)

_log = logging.getLogger("nous.evaluation.scorer")



# Quality Scorer


class QualityScorer:
    """Computes quality scores from evaluation evidence.

    Usage::

        scorer = QualityScorer()
        record = scorer.score(
            target_type="task",
            target_id="task_001",
            evidence=[...],
        )
        print(f"Score: {record.composite_score:.0%}")
    """

    def __init__(
        self,
        weights: dict[EvaluationDimension, float] | None = None,
        criteria: CriteriaRegistry | None = None,
    ):
        self._weights = weights or dict(DEFAULT_QUALITY_WEIGHTS)
        self._criteria = criteria or CriteriaRegistry()



    def score(
        self,
        *,
        target_type: str,
        target_id: str,
        input_summary: str = "",
        evidence: list[EvaluationEvidence],
        evaluated_by: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationRecord:
        """Compute a full quality score from evidence.

        Args:
            target_type: What is being evaluated (TargetType value).
            target_id: ID of the target.
            input_summary: Human-readable description of what was evaluated.
            evidence: All collected evaluation evidence.
            evaluated_by: Who performed the evaluation.
            metadata: Optional extra metadata.

        Returns:
            EvaluationRecord with composite score and dimension breakdown.

        Raises:
            EvaluationScoringError: If scoring fails.
        """
        t0 = time.perf_counter()

        try:
            # Group evidence by dimension
            by_dimension = self._group_evidence(evidence)

            # Score each dimension
            dimension_scores: list[DimensionScore] = []
            for dim in EvaluationDimension:
                dim_evidence = by_dimension.get(dim.value, [])
                dim_score = self._score_dimension(dim, dim_evidence)
                dimension_scores.append(dim_score)

            # Compute composite
            composite = sum(d.weighted for d in dimension_scores)

            # Determine status
            status = self._determine_status(dimension_scores, composite)

            # Determine recommendation
            recommendation = self._determine_recommendation(status, dimension_scores)

            # Collect issues and warnings
            issues = self._collect_issues(dimension_scores)
            warnings_list = self._collect_warnings(dimension_scores)

            # Confidence: average of evidence confidence + dimension coverage
            confidence = self._compute_confidence(dimension_scores, evidence)

            duration_ms = int((time.perf_counter() - t0) * 1000)

            return EvaluationRecord(
                target_type=target_type,
                target_id=target_id,
                status=status.value,
                input_summary=input_summary,
                criteria=tuple(d.dimension for d in dimension_scores if d.evidence_count > 0),
                dimensions=tuple(dimension_scores),
                composite_score=composite,
                confidence=confidence,
                recommendation=recommendation,
                issues=tuple(issues),
                warnings=tuple(warnings_list),
                evaluated_by=evaluated_by,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )

        except Exception as exc:
            raise EvaluationScoringError(f"Quality scoring failed: {exc}") from exc



    def _group_evidence(self, evidence: list[EvaluationEvidence]) -> dict[str, list[EvaluationEvidence]]:
        groups: dict[str, list[EvaluationEvidence]] = {}
        for e in evidence:
            groups.setdefault(e.dimension, []).append(e)
        return groups

    def _score_dimension(
        self,
        dim: EvaluationDimension,
        evidence: list[EvaluationEvidence],
    ) -> DimensionScore:
        """Score a single dimension from its evidence."""
        if not evidence:
            return DimensionScore(
                dimension=dim.value,
                score=0.0,
                weight=self._weights.get(dim, 0.0),
                passed=False,
                evidence_count=0,
                summary=f"No evidence for {dim.value}.",
            )

        # Average score across evidence, weighted by criterion weights
        total_weight = 0.0
        weighted_sum = 0.0
        for e in evidence:
            criterion = self._criteria.get(e.source)
            w = criterion.weight_in_dimension if criterion else 1.0
            weighted_sum += e.score * w
            total_weight += w

        raw_score = weighted_sum / max(total_weight, 0.001)
        score = max(0.0, min(1.0, raw_score))

        # Determine pass/fail based on criterion thresholds
        all_passed = all(e.passed for e in evidence)
        dim_weight = self._weights.get(dim, 0.0)

        summary_parts = [f"{dim.value}: {score:.2f}"]
        for e in evidence[:3]:
            status = "✓" if e.passed else "✗"
            summary_parts.append(f"  {status} {e.summary}")

        return DimensionScore(
            dimension=dim.value,
            score=score,
            weight=dim_weight,
            passed=all_passed,
            evidence_count=len(evidence),
            summary="\n".join(summary_parts),
            evidence=tuple(evidence),
        )

    def _determine_status(
        self,
        dimension_scores: list[DimensionScore],
        composite: float,
    ) -> EvaluationStatus:
        """Determine overall evaluation status."""
        all_pass = all(d.passed for d in dimension_scores if d.evidence_count > 0)
        any_fail = any(not d.passed for d in dimension_scores if d.evidence_count > 0)

        if composite >= 0.90 and all_pass:
            return EvaluationStatus.PASS
        elif composite >= 0.70 and not any_fail:
            return EvaluationStatus.PASS
        elif composite >= 0.50:
            return EvaluationStatus.WARNING
        elif composite >= 0.30:
            return EvaluationStatus.RETRY_REQUIRED
        elif composite < 0.20 and any_fail:
            return EvaluationStatus.HUMAN_REVIEW
        else:
            return EvaluationStatus.FAIL

    def _determine_recommendation(
        self,
        status: EvaluationStatus,
        dimension_scores: list[DimensionScore],
    ) -> str:
        """Recommend next action."""
        if status == EvaluationStatus.PASS:
            return "accept"
        elif status == EvaluationStatus.WARNING:
            return "improve"
        elif status == EvaluationStatus.RETRY_REQUIRED:
            return "retry"
        elif status in (EvaluationStatus.FAIL, EvaluationStatus.HUMAN_REVIEW):
            return "reject"
        return "review"

    def _collect_issues(self, dimension_scores: list[DimensionScore]) -> list[str]:
        """Collect failed dimensions as issues."""
        issues: list[str] = []
        for d in dimension_scores:
            if not d.passed and d.evidence_count > 0:
                for e in d.evidence:
                    if not e.passed:
                        issues.append(f"[{d.dimension}] {e.summary}")
        return issues

    def _collect_warnings(self, dimension_scores: list[DimensionScore]) -> list[str]:
        """Collect borderline dimensions as warnings."""
        warnings_list: list[str] = []
        for d in dimension_scores:
            if d.passed and d.score < 0.8 and d.evidence_count > 0:
                warnings_list.append(f"[{d.dimension}] borderline: {d.score:.2f}")
        return warnings_list

    def _compute_confidence(
        self,
        dimension_scores: list[DimensionScore],
        evidence: list[EvaluationEvidence],
    ) -> float:
        """Compute confidence as dimension coverage × evidence strength."""
        dims_with_evidence = sum(1 for d in dimension_scores if d.evidence_count > 0)
        dim_coverage = dims_with_evidence / max(len(EvaluationDimension), 1)

        if evidence:
            avg_score_confidence = sum(
                e.detail.get("confidence", 0.8) if isinstance(e.detail, dict) else 0.8
                for e in evidence
            ) / len(evidence)
        else:
            avg_score_confidence = 0.5

        return round(dim_coverage * 0.5 + avg_score_confidence * 0.5, 3)



# Convenience


def score_evaluation(
    target_type: str,
    target_id: str,
    evidence: list[EvaluationEvidence],
    **kwargs: Any,
) -> EvaluationRecord:
    """One-shot quality scoring."""
    return QualityScorer().score(
        target_type=target_type,
        target_id=target_id,
        evidence=evidence,
        **kwargs,
    )
