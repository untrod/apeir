# -*- coding: utf-8 -*-
"""Evaluation Runtime — AI Quality Verification Layer.

Evaluates: tasks, agents, projects, decisions, capabilities, models, providers.

Pipeline:
  Target → Validators → Evidence → Scorer → EvaluationRecord → History

Connects to Phase 2 Agent Runtime for agent profiles and
Phase 5 Experience Runtime for learning what works.
"""

from nous_runtime.evaluation.exceptions import (
    EvaluationCriteriaError,
    EvaluationError,
    EvaluationRegressionError,
    EvaluationScoringError,
    EvaluationSecurityError,
    EvaluationValidationError,
    EvaluationVerificationError,
)
from nous_runtime.evaluation.models import (
    DimensionScore,
    EvaluationEvidence,
    EvaluationRecord,
)
from nous_runtime.evaluation.schema import (
    EVALUATION_SCHEMA_VERSION,
    EvaluationDimension,
    EvaluationStatus,
    EvidenceKind,
    TargetType,
)


def __getattr__(name: str):
    _deferred = {
        "CriteriaRegistry": "nous_runtime.evaluation.criteria",
        "STANDARD_CRITERIA": "nous_runtime.evaluation.criteria",
        "QualityScorer": "nous_runtime.evaluation.scorer",
        "score_evaluation": "nous_runtime.evaluation.scorer",
        "EvaluationEngine": "nous_runtime.evaluation.evaluator",
        "evaluate_target": "nous_runtime.evaluation.evaluator",
        "RegressionEvaluator": "nous_runtime.evaluation.regression",
        "Baseline": "nous_runtime.evaluation.regression",
        "check_regression": "nous_runtime.evaluation.regression",
        "BenchmarkRunner": "nous_runtime.evaluation.benchmark",
        "BenchmarkTask": "nous_runtime.evaluation.benchmark",
        "BenchmarkResult": "nous_runtime.evaluation.benchmark",
        "AgentBenchmarkProfile": "nous_runtime.evaluation.benchmark",
        "coding_benchmark_suite": "nous_runtime.evaluation.benchmark",
        "BenchmarkSuiteRunner": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkSuite": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkCase": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkRun": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkComparator": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkBaseline": "nous_runtime.evaluation.benchmark_runtime",
        "BenchmarkEvidenceAdapter": "nous_runtime.evaluation.benchmark_runtime",
        "EvaluationHistory": "nous_runtime.evaluation.history",
        "EvaluationGuard": "nous_runtime.evaluation.security",
        "EvaluationAccessRequest": "nous_runtime.evaluation.security",
        "EvaluationAccessDecision": "nous_runtime.evaluation.security",
        "authorize_evaluation_access": "nous_runtime.evaluation.security",
        "QualityGate": "nous_runtime.evaluation.quality",
        "quality_gate_check": "nous_runtime.evaluation.quality",
        "generate_report": "nous_runtime.evaluation.report",
        "generate_json_report": "nous_runtime.evaluation.report",
    }
    if name in _deferred:
        import importlib
        mod = importlib.import_module(_deferred[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'nous_runtime.evaluation' has no attribute {name!r}")


__all__ = [
    # Models
    "EvaluationRecord",
    "DimensionScore",
    "EvaluationEvidence",
    # Schema
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationDimension",
    "EvaluationStatus",
    "EvidenceKind",
    "TargetType",
    # Engine
    "EvaluationEngine",
    "evaluate_target",
    # Criteria
    "CriteriaRegistry",
    "STANDARD_CRITERIA",
    # Scorer
    "QualityScorer",
    "score_evaluation",
    # Regression
    "RegressionEvaluator",
    "Baseline",
    "check_regression",
    # Benchmark
    "BenchmarkRunner",
    "BenchmarkTask",
    "BenchmarkResult",
    "AgentBenchmarkProfile",
    "coding_benchmark_suite",
    "BenchmarkSuiteRunner",
    "BenchmarkSuite",
    "BenchmarkCase",
    "BenchmarkRun",
    "BenchmarkComparator",
    "BenchmarkBaseline",
    "BenchmarkEvidenceAdapter",
    # History
    "EvaluationHistory",
    # Security
    "EvaluationGuard",
    "EvaluationAccessRequest",
    "EvaluationAccessDecision",
    "authorize_evaluation_access",
    # Quality Gate
    "QualityGate",
    "quality_gate_check",
    # Report
    "generate_report",
    "generate_json_report",
    # Exceptions
    "EvaluationError",
    "EvaluationValidationError",
    "EvaluationCriteriaError",
    "EvaluationScoringError",
    "EvaluationVerificationError",
    "EvaluationRegressionError",
    "EvaluationSecurityError",
]
