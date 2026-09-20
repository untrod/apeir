# -*- coding: utf-8 -*-
"""Performance Validator — latency, resource usage checks."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension, EvidenceKind

_log = logging.getLogger("nous.evaluation.validators.performance")


class PerformanceValidator:
    """Validates performance: latency, throughput, resource usage."""

    dimension: str = EvaluationDimension.PERFORMANCE.value
    source: str = "performance_validator"

    # Default thresholds
    DEFAULT_LATENCY_P95_MS = 500
    DEFAULT_MEMORY_MB = 512

    def validate(
        self,
        target: Any,
        context: dict[str, Any] | None = None,
    ) -> list[EvaluationEvidence]:
        ctx = context or {}
        evidence: list[EvaluationEvidence] = []

        # 1. Latency check from metrics
        evidence.extend(self._check_latency(ctx))

        # 2. Resource usage
        evidence.extend(self._check_resources(ctx))

        return evidence

    def _check_latency(self, ctx: dict) -> list[EvaluationEvidence]:
        """Check if latency metrics are within thresholds."""
        max_latency = ctx.get("max_latency_ms", self.DEFAULT_LATENCY_P95_MS)
        actual_latency = ctx.get("latency_ms", ctx.get("duration_ms", 0))

        if actual_latency == 0:
            return [EvaluationEvidence(
                kind=EvidenceKind.PERFORMANCE_METRIC.value,
                dimension=self.dimension,
                summary="Latency: no data",
                passed=True, score=0.5, source=self.source,
                detail={"max_allowed_ms": max_latency},
            )]

        passed = actual_latency <= max_latency
        score = 1.0 if passed else max(0.0, 1.0 - (actual_latency - max_latency) / max_latency)

        return [EvaluationEvidence(
            kind=EvidenceKind.PERFORMANCE_METRIC.value,
            dimension=self.dimension,
            summary=f"Latency: {actual_latency}ms (threshold {max_latency}ms)",
            passed=passed, score=score, source=self.source,
            detail={
                "actual_ms": actual_latency,
                "threshold_ms": max_latency,
            },
        )]

    def _check_resources(self, ctx: dict) -> list[EvaluationEvidence]:
        """Check resource usage."""
        max_memory = ctx.get("max_memory_mb", self.DEFAULT_MEMORY_MB)

        try:
            import psutil
            mem = psutil.Process().memory_info()
            used_mb = mem.rss / (1024 * 1024)
            passed = used_mb <= max_memory
            score = 1.0 if passed else max(0.0, 1.0 - (used_mb - max_memory) / max_memory)
            return [EvaluationEvidence(
                kind=EvidenceKind.PERFORMANCE_METRIC.value,
                dimension=self.dimension,
                summary=f"Memory: {used_mb:.0f}MB (threshold {max_memory}MB)",
                passed=passed, score=score, source="psutil",
                detail={"used_mb": round(used_mb, 1), "threshold_mb": max_memory},
            )]
        except ImportError:
            return [EvaluationEvidence(
                kind=EvidenceKind.PERFORMANCE_METRIC.value,
                dimension=self.dimension,
                summary="Memory: psutil not available, skipped",
                passed=True, score=0.5, source=self.source,
                detail={"error": "psutil not installed"},
            )]
