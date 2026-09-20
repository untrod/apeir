from __future__ import annotations

import hashlib

from nous_runtime.artifact import Artifact, ArtifactType
from nous_runtime.verification import (
    ArtifactVerifier,
    IssueSeverity,
    ModelReviewer,
    RuleVerifier,
    SchemaVerifier,
    TestOutcome,
    TestVerifier,
    VerificationCandidate,
    VerificationRule,
)


def test_schema_verifier_reports_missing_and_invalid_fields() -> None:
    verifier = SchemaVerifier({"name": str, "count": int})
    result = verifier.verify(
        VerificationCandidate(output={"name": 3}),
        {},
    )

    assert not result.accepted
    assert {item.code for item in result.issues} == {
        "schema.type_mismatch",
        "schema.missing_field",
    }


def test_schema_verifier_can_warn_on_extra_fields() -> None:
    result = SchemaVerifier(
        {"name": str},
        allow_extra=False,
    ).verify(VerificationCandidate(output={"name": "ok", "extra": 1}), {})

    assert result.accepted
    assert result.issues[0].severity is IssueSeverity.WARNING


def test_rule_verifier_uses_injected_predicates() -> None:
    rule = VerificationRule(
        "positive",
        lambda candidate, context: candidate.output > context["minimum"],
        "value must be positive",
    )
    verifier = RuleVerifier((rule,))

    assert verifier.verify(VerificationCandidate(output=2), {"minimum": 0}).accepted
    failed = verifier.verify(
        VerificationCandidate(output=-1),
        {"minimum": 0},
    )
    assert failed.issues[0].code == "rule.positive"


def test_test_verifier_never_executes_without_injected_runner() -> None:
    calls = []

    def runner(candidate, context):
        calls.append((candidate.output, context["suite"]))
        return TestOutcome(
            passed=False,
            summary="one failure",
            failed_tests=("test_one",),
        )

    result = TestVerifier(runner).verify(
        VerificationCandidate(output="candidate"),
        {"suite": "unit"},
    )

    assert calls == [("candidate", "unit")]
    assert not result.accepted
    assert result.evidence["failed_tests"] == ["test_one"]


def test_artifact_verifier_checks_type_and_optional_checksum(tmp_path) -> None:
    path = tmp_path / "report.txt"
    path.write_text("report", encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = Artifact(
        type=ArtifactType.REPORT.value,
        name="report",
        location=str(path),
        metadata={"checksum": checksum},
    )
    candidate = VerificationCandidate(output={}, artifacts=(artifact,))

    accepted = ArtifactVerifier(
        required_types=frozenset({"report"}),
        verify_files=True,
    ).verify(candidate, {})
    assert accepted.accepted

    missing = ArtifactVerifier(
        required_types=frozenset({"code"}),
    ).verify(candidate, {})
    assert missing.issues[0].code == "artifact.missing_type"


def test_model_reviewer_is_an_explicit_injected_boundary() -> None:
    calls = []

    def review(candidate, context):
        calls.append((candidate.output, context["risk"]))
        return {"accepted": True, "score": 0.9, "evidence": {"reviewed": True}}

    result = ModelReviewer(review).verify(
        VerificationCandidate(output={"answer": 42}),
        {"risk": "high"},
    )

    assert result.accepted
    assert result.score == 0.9
    assert calls == [({"answer": 42}, "high")]
