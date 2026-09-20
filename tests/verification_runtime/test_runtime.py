from __future__ import annotations

import pytest

from nous_runtime.verification import (
    ApprovalDecision,
    HumanApproval,
    HumanApprovalBoundary,
    HumanApprovalError,
    IssueSeverity,
    RuleVerifier,
    SchemaVerifier,
    VerificationCandidate,
    VerificationIssue,
    VerificationPhase,
    VerificationRepairRuntime,
    VerificationRule,
    VerifierResult,
)


def test_generate_verify_critique_repair_accept_lifecycle() -> None:
    runtime = VerificationRepairRuntime(
        (SchemaVerifier({"answer": int}),),
        max_repairs=2,
    )

    def repair(candidate, critique, attempt):
        assert candidate.output == {"answer": "42"}
        assert critique.issues[0].code == "schema.type_mismatch"
        assert attempt == 1
        return {"answer": 42}

    run = runtime.run(
        generate=lambda: {"answer": "42"},
        repair=repair,
        accept=lambda candidate, report: {
            "accepted": candidate.output,
            "score": report.score,
        },
    )

    assert run.phase is VerificationPhase.ACCEPTED
    assert run.accepted_output == {
        "accepted": {"answer": 42},
        "score": 1.0,
    }
    assert run.phase_history == [
        VerificationPhase.CREATED,
        VerificationPhase.GENERATED,
        VerificationPhase.VERIFIED,
        VerificationPhase.CRITIQUED,
        VerificationPhase.REPAIRED,
        VerificationPhase.VERIFIED,
        VerificationPhase.ACCEPTED,
    ]
    assert run.repairs[0].attempt == 1
    assert run.candidates[-1].version == 2


def test_repair_loop_is_bounded() -> None:
    runtime = VerificationRepairRuntime(
        (SchemaVerifier({"answer": int}),),
        max_repairs=2,
    )
    calls = 0

    def repair(candidate, critique, attempt):
        nonlocal calls
        calls += 1
        return {"answer": "still wrong"}

    run = runtime.run(
        generate=lambda: {"answer": "wrong"},
        repair=repair,
    )

    assert run.phase is VerificationPhase.REJECTED
    assert calls == 2
    assert len(run.reports) == 3


def test_non_repairable_issue_stops_without_repair() -> None:
    class Reject:
        name = "reject"

        def verify(self, candidate, context):
            return VerifierResult(
                verifier=self.name,
                accepted=False,
                score=0,
                issues=(
                    VerificationIssue(
                        "fatal",
                        "cannot repair",
                        self.name,
                        severity=IssueSeverity.CRITICAL,
                        repairable=False,
                    ),
                ),
            )

    called = False

    def repair(candidate, critique, attempt):
        nonlocal called
        called = True

    run = VerificationRepairRuntime((Reject(),), max_repairs=5).run(
        generate=lambda: "candidate",
        repair=repair,
    )

    assert run.phase is VerificationPhase.REJECTED
    assert not called


def test_verifier_exception_fails_closed() -> None:
    class BrokenVerifier:
        name = "broken"

        def verify(self, candidate, context):
            raise RuntimeError("validator crashed")

    run = VerificationRepairRuntime((BrokenVerifier(),)).run(
        generate=lambda: "candidate"
    )

    assert run.phase is VerificationPhase.REJECTED
    assert run.reports[0].issues[0].code == "verifier.exception"
    assert not run.reports[0].issues[0].repairable


def test_human_approval_accept_deny_and_pending() -> None:
    verifier = RuleVerifier(
        (
            VerificationRule(
                "always",
                lambda candidate, context: True,
                "must pass",
            ),
        )
    )
    runtime = VerificationRepairRuntime((verifier,))

    approved = runtime.run(
        generate=lambda: "value",
        approval=HumanApprovalBoundary(
            lambda candidate, report: HumanApproval(
                ApprovalDecision.APPROVED,
                approver_id="human.reviewer",
            ),
            requester_id="agent.worker",
        ),
    )
    assert approved.phase is VerificationPhase.ACCEPTED

    denied = runtime.run(
        generate=lambda: "value",
        approval=HumanApprovalBoundary(
            lambda candidate, report: HumanApproval(
                ApprovalDecision.DENIED,
                approver_id="human.reviewer",
                reason="not ready",
            ),
            requester_id="agent.worker",
        ),
    )
    assert denied.phase is VerificationPhase.REJECTED
    assert denied.error == "not ready"

    pending = runtime.run(
        generate=lambda: "value",
        approval=HumanApprovalBoundary(
            lambda candidate, report: HumanApproval(
                ApprovalDecision.PENDING
            ),
            requester_id="agent.worker",
        ),
    )
    assert pending.phase is VerificationPhase.WAITING_APPROVAL

    resumed = runtime.resume_approval(
        pending,
        HumanApproval(
            ApprovalDecision.APPROVED,
            approver_id="human.reviewer",
        ),
    )
    assert resumed.phase is VerificationPhase.ACCEPTED
    assert resumed.accepted_output == "value"


def test_human_self_approval_fails_closed() -> None:
    runtime = VerificationRepairRuntime((SchemaVerifier({"ok": bool}),))
    run = runtime.run(
        generate=lambda: {"ok": True},
        approval=HumanApprovalBoundary(
            lambda candidate, report: HumanApproval(
                ApprovalDecision.APPROVED,
                approver_id="agent.same",
            ),
            requester_id="agent.same",
        ),
    )

    assert run.phase is VerificationPhase.FAILED
    assert "self approval" in run.error


def test_resume_requires_waiting_state() -> None:
    run = VerificationRepairRuntime((SchemaVerifier({"ok": bool}),)).run(
        generate=lambda: {"ok": True}
    )

    with pytest.raises(HumanApprovalError):
        VerificationRepairRuntime((SchemaVerifier({"ok": bool}),)).resume_approval(
            run,
            HumanApproval(
                ApprovalDecision.APPROVED,
                approver_id="human",
            ),
        )


def test_generated_candidate_preserves_explicit_version() -> None:
    candidate = VerificationCandidate(output={"ok": True}, version=7)
    run = VerificationRepairRuntime((SchemaVerifier({"ok": bool}),)).run(
        generate=lambda: candidate
    )
    assert run.candidates[0] is candidate
