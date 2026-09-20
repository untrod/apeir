# -*- coding: utf-8 -*-
"""Evaluation Engine — main orchestrator for evaluation runs.

Pipeline:
  Target → Collect Evidence (validators) → Score → Record → Report
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nous_runtime.evaluation.history import EvaluationHistory
from nous_runtime.evaluation.models import EvaluationEvidence, EvaluationRecord
from nous_runtime.evaluation.regression import RegressionEvaluator, RegressionResult
from nous_runtime.evaluation.scorer import QualityScorer
from nous_runtime.evaluation.validators.base import Validator
from nous_runtime.evaluation.validators.code_validator import CodeValidator
from nous_runtime.evaluation.validators.performance_validator import PerformanceValidator
from nous_runtime.evaluation.validators.schema_validator import SchemaValidator
from nous_runtime.evaluation.validators.security_validator import SecurityValidator
from nous_runtime.evaluation.validators.test_validator import TestValidator

_log = logging.getLogger("nous.evaluation.engine")



# Default validators


def _default_validators() -> list[Validator]:
    return [
        TestValidator(),
        CodeValidator(),
        SecurityValidator(),
        PerformanceValidator(),
        SchemaValidator(),
    ]



# Evaluation Engine


class EvaluationEngine:
    """Orchestrates full evaluation runs.

    Usage::

        engine = EvaluationEngine(workspace="/path/to/.nous")
        record = engine.evaluate(
            target_type="task",
            target_id="task_001",
            input_summary="Refactor scheduler module",
        )
        print(f"Score: {record.composite_score:.0%}")
        print(f"Status: {record.status}")
    """

    def __init__(
        self,
        workspace: str = "",
        validators: list[Validator] | None = None,
        scorer: QualityScorer | None = None,
        history: EvaluationHistory | None = None,
    ):
        self._workspace = workspace
        self._validators = validators if validators is not None else _default_validators()
        self._scorer = scorer or QualityScorer()
        self._history = history or EvaluationHistory(workspace)



    def evaluate(
        self,
        *,
        target_type: str,
        target_id: str,
        input_summary: str = "",
        context: dict[str, Any] | None = None,
        persist: bool = True,
        evaluated_by: str = "system",
    ) -> EvaluationRecord:
        """Run a full evaluation against a target.

        Args:
            target_type: What is being evaluated (TargetType value).
            target_id: ID of the target.
            input_summary: Description of what was evaluated.
            context: Optional context for validators (test_path, cwd, etc.).
            persist: Save to evaluation history.
            evaluated_by: Who ran the evaluation.

        Returns:
            EvaluationRecord with score, status, and recommendation.
        """
        t0 = time.perf_counter()
        ctx = context or {}

        # Phase 1 — Collect evidence from all validators
        all_evidence: list[EvaluationEvidence] = []
        for validator in self._validators:
            try:
                evidence = validator.validate(target=None, context=ctx)
                all_evidence.extend(evidence)
            except Exception as exc:
                _log.warning("Validator %s failed: %s", getattr(validator, "source", "?"), exc)

        # Phase 2 — Score
        record = self._scorer.score(
            target_type=target_type,
            target_id=target_id,
            input_summary=input_summary,
            evidence=all_evidence,
            evaluated_by=evaluated_by,
            metadata={"validator_count": len(self._validators), **ctx.get("metadata", {})},
        )

        # Phase 3 — Persist
        if persist:
            self._history.save(record)

        elapsed = int((time.perf_counter() - t0) * 1000)
        _log.info(
            "Evaluation %s: target=%s/%s score=%.2f status=%s (%d ms)",
            record.id, target_type, target_id,
            record.composite_score, record.status, elapsed,
        )

        return record


    # Regression


    def evaluate_with_regression(
        self,
        *,
        target_type: str,
        target_id: str,
        input_summary: str = "",
        context: dict[str, Any] | None = None,
        baseline_record_id: str = "",
    ) -> tuple[EvaluationRecord, RegressionResult | None]:
        """Evaluate and compare against a previous baseline.

        Returns (current_record, regression_result).
        If no baseline found, regression_result is None.
        """
        current = self.evaluate(
            target_type=target_type,
            target_id=target_id,
            input_summary=input_summary,
            context=context,
            persist=True,
        )

        # Find baseline
        if baseline_record_id:
            baseline_record = self._history.get(baseline_record_id)
        else:
            # Use the most recent previous evaluation for this target
            previous = self._history.list(
                target_type=target_type, target_id=target_id, limit=2, order="DESC",
            )
            baseline_record = previous[1] if len(previous) >= 2 else None

        if baseline_record is None:
            _log.info("No baseline found for regression comparison.")
            return current, None

        reg_eval = RegressionEvaluator()
        result = reg_eval.compare_records(baseline_record, current)
        _log.info(
            "Regression: passed=%s delta=%.3f recommendation=%s",
            result.passed, result.delta, result.recommendation,
        )
        return current, result


    # Reporting


    def report(self, record: EvaluationRecord) -> dict[str, Any]:
        """Generate a human-readable report from an evaluation record."""
        return {
            "evaluation_id": record.id,
            "target": f"{record.target_type}/{record.target_id}",
            "status": record.status,
            "composite_score": round(record.composite_score * 100),
            "confidence": record.confidence,
            "recommendation": record.recommendation,
            "dimensions": [
                {
                    "name": d.dimension,
                    "score": round(d.score * 100),
                    "weight": d.weight,
                    "passed": d.passed,
                    "evidence_count": d.evidence_count,
                }
                for d in record.dimensions
            ],
            "issues": list(record.issues),
            "warnings": list(record.warnings),
            "duration_ms": record.duration_ms,
        }



# Convenience


def evaluate_target(
    target_type: str,
    target_id: str,
    workspace: str = "",
    **kwargs: Any,
) -> EvaluationRecord:
    """One-shot evaluation."""
    engine = EvaluationEngine(workspace=workspace)
    return engine.evaluate(target_type=target_type, target_id=target_id, **kwargs)
