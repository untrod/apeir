"""Built-in deterministic verifiers and explicit external boundaries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from nous_runtime.verification.models import (
    IssueSeverity,
    VerificationCandidate,
    VerificationIssue,
    VerifierResult,
)


class Verifier(Protocol):
    name: str

    def verify(
        self,
        candidate: VerificationCandidate,
        context: Mapping[str, Any],
    ) -> VerifierResult: ...


def _result(
    name: str,
    issues: list[VerificationIssue],
    evidence: Mapping[str, Any] | None = None,
) -> VerifierResult:
    blocking = [
        item
        for item in issues
        if item.severity in {IssueSeverity.ERROR, IssueSeverity.CRITICAL}
    ]
    return VerifierResult(
        verifier=name,
        accepted=not blocking,
        score=1.0 if not issues else max(0.0, 1.0 - len(blocking) * 0.25),
        issues=tuple(issues),
        evidence=dict(evidence or {}),
    )


class SchemaVerifier:
    name = "schema"

    def __init__(
        self,
        schema: Mapping[str, type | tuple[type, ...]],
        *,
        allow_extra: bool = True,
    ) -> None:
        self.schema = dict(schema)
        self.allow_extra = allow_extra

    def verify(self, candidate, context) -> VerifierResult:
        issues: list[VerificationIssue] = []
        output = candidate.output
        if not isinstance(output, Mapping):
            issues.append(
                VerificationIssue(
                    "schema.not_mapping",
                    "output must be a mapping",
                    self.name,
                    repairable=True,
                )
            )
            return _result(self.name, issues)
        for key, expected in self.schema.items():
            if key not in output:
                issues.append(
                    VerificationIssue(
                        "schema.missing_field",
                        f"required field is missing: {key}",
                        self.name,
                        path=key,
                    )
                )
            elif not isinstance(output[key], expected):
                issues.append(
                    VerificationIssue(
                        "schema.type_mismatch",
                        f"field has invalid type: {key}",
                        self.name,
                        path=key,
                        metadata={"actual_type": type(output[key]).__name__},
                    )
                )
        if not self.allow_extra:
            for key in sorted(set(output) - set(self.schema)):
                issues.append(
                    VerificationIssue(
                        "schema.extra_field",
                        f"unexpected field: {key}",
                        self.name,
                        severity=IssueSeverity.WARNING,
                        path=str(key),
                    )
                )
        return _result(
            self.name,
            issues,
            {"checked_fields": sorted(self.schema)},
        )


RulePredicate = Callable[[VerificationCandidate, Mapping[str, Any]], bool]


@dataclass(frozen=True)
class VerificationRule:
    rule_id: str
    predicate: RulePredicate
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR
    repairable: bool = True


class RuleVerifier:
    name = "rule"

    def __init__(self, rules: tuple[VerificationRule, ...]) -> None:
        self.rules = rules

    def verify(self, candidate, context) -> VerifierResult:
        issues = []
        for rule in self.rules:
            if not bool(rule.predicate(candidate, context)):
                issues.append(
                    VerificationIssue(
                        f"rule.{rule.rule_id}",
                        rule.message,
                        self.name,
                        severity=rule.severity,
                        repairable=rule.repairable,
                    )
                )
        return _result(
            self.name,
            issues,
            {"rule_count": len(self.rules)},
        )


@dataclass(frozen=True)
class TestOutcome:
    __test__ = False

    passed: bool
    summary: str = ""
    failed_tests: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None


TestRunner = Callable[
    [VerificationCandidate, Mapping[str, Any]],
    TestOutcome,
]


class TestVerifier:
    __test__ = False

    name = "test"

    def __init__(self, runner: TestRunner) -> None:
        self.runner = runner

    def verify(self, candidate, context) -> VerifierResult:
        outcome = self.runner(candidate, context)
        issues = []
        if not outcome.passed:
            issues.append(
                VerificationIssue(
                    "test.failed",
                    outcome.summary or "tests failed",
                    self.name,
                    metadata={"failed_tests": list(outcome.failed_tests)},
                )
            )
        return _result(
            self.name,
            issues,
            {
                "summary": outcome.summary,
                "failed_tests": list(outcome.failed_tests),
                **dict(outcome.metadata or {}),
            },
        )


class ArtifactVerifier:
    name = "artifact"

    def __init__(
        self,
        *,
        required_types: frozenset[str] = frozenset(),
        verify_files: bool = False,
    ) -> None:
        self.required_types = required_types
        self.verify_files = verify_files

    def verify(self, candidate, context) -> VerifierResult:
        issues = []
        types = {item.type for item in candidate.artifacts}
        for artifact_type in sorted(self.required_types - types):
            issues.append(
                VerificationIssue(
                    "artifact.missing_type",
                    f"required artifact type is missing: {artifact_type}",
                    self.name,
                )
            )
        for artifact in candidate.artifacts:
            if not self.verify_files or not artifact.location:
                continue
            path = Path(artifact.location)
            if not path.is_file():
                issues.append(
                    VerificationIssue(
                        "artifact.file_missing",
                        f"artifact file does not exist: {artifact.name}",
                        self.name,
                        path=artifact.location,
                    )
                )
                continue
            expected = str(artifact.metadata.get("checksum") or "")
            if expected:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != expected:
                    issues.append(
                        VerificationIssue(
                            "artifact.checksum_mismatch",
                            f"artifact checksum mismatch: {artifact.name}",
                            self.name,
                            path=artifact.location,
                            repairable=False,
                        )
                    )
        return _result(
            self.name,
            issues,
            {
                "artifact_count": len(candidate.artifacts),
                "artifact_types": sorted(types),
            },
        )


ModelReviewHandler = Callable[
    [VerificationCandidate, Mapping[str, Any]],
    VerifierResult | Mapping[str, Any],
]


class ModelReviewer:
    """Explicit injected boundary; it never calls a model by itself."""

    name = "model_reviewer"

    def __init__(self, handler: ModelReviewHandler) -> None:
        self.handler = handler

    def verify(self, candidate, context) -> VerifierResult:
        raw = self.handler(candidate, context)
        if isinstance(raw, VerifierResult):
            return raw
        accepted = bool(raw.get("accepted", False))
        issues = tuple(
            VerificationIssue.from_dict(item)
            for item in raw.get("issues") or ()
        )
        if not accepted and not issues:
            issues = (
                VerificationIssue(
                    "model_review.rejected",
                    str(raw.get("reason") or "model reviewer rejected output"),
                    self.name,
                ),
            )
        return VerifierResult(
            verifier=self.name,
            accepted=accepted,
            score=float(raw.get("score") or (1.0 if accepted else 0.0)),
            issues=issues,
            evidence=dict(raw.get("evidence") or {}),
        )


__all__ = [
    "ArtifactVerifier",
    "ModelReviewer",
    "RuleVerifier",
    "SchemaVerifier",
    "TestOutcome",
    "TestVerifier",
    "VerificationRule",
    "Verifier",
]
