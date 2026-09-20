# -*- coding: utf-8 -*-
"""Experience Explanation — human-readable reasoning for experience decisions."""

from __future__ import annotations

from nous_runtime.experience.models import ExperiencePattern, ExperienceRecord, Recommendation


def explain_experience(record: ExperienceRecord) -> str:
    """Explain why an experience is relevant."""
    parts = [
        f"Experience: {record.task_summary}",
        f"  Source: {record.source_type}",
        f"  Task type: {record.task_type}",
        f"  Action: {record.action}",
        f"  Result: {record.result}",
        f"  Success: {'✓' if record.success else '✗'}",
        f"  Confidence: {record.confidence:.2f}",
        f"  Status: {record.status}",
        f"  Occurrences: {record.occurrence_count}",
    ]
    if record.failure_reason:
        parts.append(f"  Failure reason: {record.failure_reason}")
    if record.lessons:
        parts.append("  Lessons:")
        for lesson in record.lessons:
            parts.append(f"    • {lesson}")
    return "\n".join(parts)


def explain_pattern(pattern: ExperiencePattern) -> str:
    """Explain a discovered pattern."""
    return "\n".join([
        f"Pattern: {pattern.name}",
        f"  Type: {pattern.pattern_type}",
        f"  Description: {pattern.description}",
        f"  Frequency: {pattern.frequency} occurrences",
        f"  Success rate: {pattern.success_rate:.0%}",
        f"  Confidence: {pattern.confidence:.2f}",
        f"  Source experiences: {len(pattern.source_experiences)}",
    ])


def explain_recommendation(rec: Recommendation) -> str:
    """Explain a recommendation."""
    return "\n".join([
        f"Recommendation: {rec.title}",
        f"  Type: {rec.recommendation_type}",
        f"  Description: {rec.description}",
        f"  Confidence: {rec.confidence:.2f}",
        f"  Reason: {rec.reason}",
        f"  Supporting evidence: {len(rec.supporting_experiences)} experiences",
    ])
