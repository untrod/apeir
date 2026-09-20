# -*- coding: utf-8 -*-
"""Evaluation Report — formatted output generation."""

from __future__ import annotations

from typing import Any

from nous_runtime.evaluation.models import EvaluationRecord


def generate_report(record: EvaluationRecord) -> str:
    """Generate a plain-text evaluation report."""
    lines: list[str] = []
    score_pct = int(record.composite_score * 100)

    lines.append("=" * 60)
    lines.append(f"EVALUATION REPORT: {record.id}")
    lines.append("=" * 60)
    lines.append(f"  Target:       {record.target_type}/{record.target_id}")
    lines.append(f"  Status:       {record.status.upper()}")
    lines.append(f"  Score:        {score_pct}/100")
    lines.append(f"  Confidence:   {record.confidence:.2f}")
    lines.append(f"  Recommendation: {record.recommendation}")
    lines.append(f"  Evaluated by: {record.evaluated_by}")
    lines.append(f"  Created:      {record.created_at}")
    lines.append(f"  Duration:     {record.duration_ms}ms")
    lines.append("")

    # Dimension breakdown
    lines.append("  DIMENSIONS:")
    for d in record.dimensions:
        bar = "█" * int(d.score * 10) + "░" * (10 - int(d.score * 10))
        status = "✓" if d.passed else "✗"
        lines.append(f"    {status} {d.dimension:20s} {bar} {int(d.score*100):3d}%  "
                     f"(weight={d.weight:.2f}, evidence={d.evidence_count})")

    lines.append("")

    # Evidence details
    if any(d.evidence_count > 0 for d in record.dimensions):
        lines.append("  EVIDENCE:")
        for d in record.dimensions:
            for e in d.evidence:
                icon = "✓" if e.passed else "✗"
                lines.append(f"    {icon} [{e.source}] {e.summary}")

    lines.append("")

    # Issues
    if record.issues:
        lines.append("  ISSUES:")
        for i in record.issues:
            lines.append(f"    ⚠ {i}")
        lines.append("")

    # Warnings
    if record.warnings:
        lines.append("  WARNINGS:")
        for w in record.warnings:
            lines.append(f"    ⚡ {w}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def generate_json_report(record: EvaluationRecord) -> dict[str, Any]:
    """Generate a structured JSON report."""
    return {
        "evaluation_id": record.id,
        "target": {"type": record.target_type, "id": record.target_id},
        "status": record.status,
        "composite_score": round(record.composite_score, 4),
        "confidence": record.confidence,
        "recommendation": record.recommendation,
        "dimensions": [
            {
                "name": d.dimension,
                "score": round(d.score, 4),
                "weight": d.weight,
                "weighted": d.weighted,
                "passed": d.passed,
                "evidence_count": d.evidence_count,
                "summary": d.summary,
                "evidence": [
                    {
                        "source": e.source,
                        "kind": e.kind,
                        "passed": e.passed,
                        "score": e.score,
                        "summary": e.summary,
                    }
                    for e in d.evidence
                ],
            }
            for d in record.dimensions
        ],
        "issues": list(record.issues),
        "warnings": list(record.warnings),
        "metadata": {
            "evaluated_by": record.evaluated_by,
            "created_at": record.created_at,
            "duration_ms": record.duration_ms,
            "schema_version": record.schema_version,
        },
    }
