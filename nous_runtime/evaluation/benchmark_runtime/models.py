"""Serializable Benchmark Runtime contracts."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from nous_runtime.evaluation.benchmark_runtime.errors import (
    BenchmarkConfigurationError,
)


class BenchmarkCaseStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"


class BenchmarkGateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    name: str
    input: Any
    expected: Any = None
    category: str = "general"
    weight: float = 1.0
    timeout_ms: int = 30_000
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id or not self.name:
            raise BenchmarkConfigurationError(
                "benchmark case_id and name are required"
            )
        if self.weight <= 0 or self.timeout_ms <= 0:
            raise BenchmarkConfigurationError(
                "benchmark weight and timeout must be positive"
            )


@dataclass(frozen=True)
class BenchmarkSuite:
    suite_id: str
    name: str
    cases: tuple[BenchmarkCase, ...]
    version: str = "1.0.0"
    repetitions: int = 1
    min_score: float = 0.7
    min_pass_rate: float = 0.8
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.suite_id or not self.name or not self.cases:
            raise BenchmarkConfigurationError(
                "benchmark suite id, name and cases are required"
            )
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise BenchmarkConfigurationError(
                "benchmark case ids must be unique"
            )
        if self.repetitions < 1:
            raise BenchmarkConfigurationError(
                "benchmark repetitions must be positive"
            )
        if not 0 <= self.min_score <= 1 or not 0 <= self.min_pass_rate <= 1:
            raise BenchmarkConfigurationError(
                "benchmark thresholds must be between zero and one"
            )


@dataclass(frozen=True)
class BenchmarkExecution:
    output: Any
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseEvaluation:
    passed: bool
    score: float
    reason: str = ""
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "score",
            max(0.0, min(1.0, float(self.score))),
        )


@dataclass(frozen=True)
class BenchmarkAttempt:
    attempt: int
    status: BenchmarkCaseStatus
    output: Any = None
    score: float = 0.0
    duration_ms: int = 0
    metrics: Mapping[str, float] = field(default_factory=dict)
    reason: str = ""
    error: str = ""


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    category: str
    status: BenchmarkCaseStatus
    score: float
    duration_ms: int
    determinism: float
    attempts: tuple[BenchmarkAttempt, ...]
    metrics: Mapping[str, float] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class BenchmarkRun:
    suite_id: str
    suite_version: str
    target_id: str
    results: tuple[BenchmarkCaseResult, ...]
    score: float
    pass_rate: float
    determinism: float
    duration_ms: int
    metrics: Mapping[str, float]
    passed: bool
    run_id: str = field(
        default_factory=lambda: f"bench_{uuid.uuid4().hex}"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkBaseline:
    suite_id: str
    suite_version: str
    target_id: str
    score: float
    pass_rate: float
    determinism: float
    metrics: Mapping[str, float]
    run_id: str

    @classmethod
    def from_run(cls, run: BenchmarkRun) -> "BenchmarkBaseline":
        return cls(
            suite_id=run.suite_id,
            suite_version=run.suite_version,
            target_id=run.target_id,
            score=run.score,
            pass_rate=run.pass_rate,
            determinism=run.determinism,
            metrics=dict(run.metrics),
            run_id=run.run_id,
        )


@dataclass(frozen=True)
class MetricRegression:
    metric: str
    baseline: float
    current: float
    delta: float
    regressed: bool
    direction: MetricDirection
    tolerance: float


@dataclass(frozen=True)
class BenchmarkComparison:
    baseline_run_id: str
    current_run_id: str
    status: BenchmarkGateStatus
    metrics: tuple[MetricRegression, ...]
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]


__all__ = [
    "BenchmarkAttempt",
    "BenchmarkBaseline",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkCaseStatus",
    "BenchmarkComparison",
    "BenchmarkExecution",
    "BenchmarkGateStatus",
    "BenchmarkRun",
    "BenchmarkSuite",
    "CaseEvaluation",
    "MetricDirection",
    "MetricRegression",
]
