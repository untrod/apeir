# -*- coding: utf-8 -*-
"""Evaluation Runtime schema — enums, constants, schema version."""

from __future__ import annotations

from enum import Enum

from nous_runtime.schema_registry import EVALUATION_SCHEMA_VERSION  # noqa: F401 - public re-export



class EvaluationStatus(str, Enum):
    """Result of an evaluation run."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    RETRY_REQUIRED = "retry_required"
    HUMAN_REVIEW = "human_review"
    PENDING = "pending"


class EvaluationDimension(str, Enum):
    """Standard evaluation dimensions."""
    CORRECTNESS = "correctness"
    RELIABILITY = "reliability"
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class TargetType(str, Enum):
    """What is being evaluated."""
    AGENT = "agent"
    TASK = "task"
    PROJECT = "project"
    DECISION = "decision"
    CAPABILITY = "capability"
    MODEL = "model"
    PROVIDER = "provider"
    EXECUTION = "execution"


class EvidenceKind(str, Enum):
    """Type of evaluation evidence."""
    TEST_RESULT = "test_result"
    LINT_RESULT = "lint_result"
    SECURITY_SCAN = "security_scan"
    BENCHMARK = "benchmark"
    TYPE_CHECK = "type_check"
    COMPILE_CHECK = "compile_check"
    PERFORMANCE_METRIC = "performance_metric"
    MANUAL_REVIEW = "manual_review"
    AUTOMATED_CHECK = "automated_check"


# Default scoring weights
DEFAULT_QUALITY_WEIGHTS = {
    EvaluationDimension.CORRECTNESS: 0.30,
    EvaluationDimension.RELIABILITY: 0.20,
    EvaluationDimension.SECURITY: 0.20,
    EvaluationDimension.PERFORMANCE: 0.15,
    EvaluationDimension.MAINTAINABILITY: 0.15,
}
