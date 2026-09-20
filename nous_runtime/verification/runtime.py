"""Generate, verify, critique, repair and accept Runtime."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from nous_runtime.verification.errors import (
    HumanApprovalError,
    VerificationConfigurationError,
)
from nous_runtime.verification.models import (
    ApprovalDecision,
    Critique,
    HumanApproval,
    RepairRecord,
    VerificationCandidate,
    VerificationIssue,
    VerificationPhase,
    VerificationReport,
    VerificationRun,
    VerifierResult,
)
from nous_runtime.verification.verifiers import Verifier


GenerateHandler = Callable[[], VerificationCandidate | Any]
CritiqueHandler = Callable[[VerificationCandidate, VerificationReport], Critique]
RepairHandler = Callable[
    [VerificationCandidate, Critique, int],
    VerificationCandidate | Any,
]
AcceptHandler = Callable[[VerificationCandidate, VerificationReport], Any]
ApprovalHandler = Callable[
    [VerificationCandidate, VerificationReport],
    HumanApproval,
]


class HumanApprovalBoundary:
    """Fail-closed approval boundary with self-approval protection."""

    def __init__(
        self,
        handler: ApprovalHandler,
        *,
        requester_id: str,
        prevent_self_approval: bool = True,
    ) -> None:
        self.handler = handler
        self.requester_id = str(requester_id or "")
        self.prevent_self_approval = prevent_self_approval

    def request(
        self,
        candidate: VerificationCandidate,
        report: VerificationReport,
    ) -> HumanApproval:
        approval = self.handler(candidate, report)
        if not isinstance(approval, HumanApproval):
            raise HumanApprovalError(
                "approval handler must return HumanApproval"
            )
        if (
            self.prevent_self_approval
            and approval.decision is ApprovalDecision.APPROVED
            and approval.approver_id == self.requester_id
        ):
            raise HumanApprovalError("self approval is not permitted")
        if (
            approval.decision is ApprovalDecision.APPROVED
            and not approval.approver_id
        ):
            raise HumanApprovalError("approved decision requires approver_id")
        return approval


class VerificationRepairRuntime:
    def __init__(
        self,
        verifiers: tuple[Verifier, ...],
        *,
        max_repairs: int = 1,
    ) -> None:
        if not verifiers:
            raise VerificationConfigurationError(
                "at least one verifier is required"
            )
        if max_repairs < 0:
            raise VerificationConfigurationError(
                "max_repairs must be non-negative"
            )
        self.verifiers = verifiers
        self.max_repairs = max_repairs

    def run(
        self,
        *,
        generate: GenerateHandler,
        repair: RepairHandler | None = None,
        critique: CritiqueHandler | None = None,
        accept: AcceptHandler | None = None,
        approval: HumanApprovalBoundary | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> VerificationRun:
        run = VerificationRun()
        ctx = dict(context or {})
        try:
            candidate = self._candidate(generate(), version=1)
            run.candidates.append(candidate)
            run.transition(VerificationPhase.GENERATED)
            for attempt in range(self.max_repairs + 1):
                report = self._verify(candidate, ctx)
                run.reports.append(report)
                run.transition(VerificationPhase.VERIFIED)
                if report.accepted:
                    if approval is not None:
                        decision = approval.request(candidate, report)
                        run.approval = decision
                        if decision.decision is ApprovalDecision.PENDING:
                            run.transition(VerificationPhase.WAITING_APPROVAL)
                            return run
                        if decision.decision is ApprovalDecision.DENIED:
                            run.error = decision.reason or "human approval denied"
                            run.transition(VerificationPhase.REJECTED)
                            return run
                    run.accepted_output = (
                        accept(candidate, report)
                        if accept is not None
                        else candidate.output
                    )
                    run.transition(VerificationPhase.ACCEPTED)
                    return run
                current_critique = (
                    critique(candidate, report)
                    if critique is not None
                    else self._default_critique(report)
                )
                run.critiques.append(current_critique)
                run.transition(VerificationPhase.CRITIQUED)
                if (
                    attempt >= self.max_repairs
                    or repair is None
                    or not any(item.repairable for item in report.issues)
                ):
                    run.error = "verification rejected candidate"
                    run.transition(VerificationPhase.REJECTED)
                    return run
                repaired = self._candidate(
                    repair(candidate, current_critique, attempt + 1),
                    version=candidate.version + 1,
                )
                run.repairs.append(
                    RepairRecord(
                        attempt=attempt + 1,
                        source_candidate_id=candidate.candidate_id,
                        repaired_candidate_id=repaired.candidate_id,
                        critique=current_critique,
                    )
                )
                candidate = repaired
                run.candidates.append(candidate)
                run.transition(VerificationPhase.REPAIRED)
        except Exception as exc:
            run.error = str(exc)
            run.transition(VerificationPhase.FAILED)
        return run

    def resume_approval(
        self,
        run: VerificationRun,
        approval: HumanApproval,
        *,
        accept: AcceptHandler | None = None,
    ) -> VerificationRun:
        if run.phase is not VerificationPhase.WAITING_APPROVAL:
            raise HumanApprovalError("verification run is not waiting for approval")
        run.approval = approval
        if approval.decision is ApprovalDecision.PENDING:
            return run
        if approval.decision is ApprovalDecision.DENIED:
            run.error = approval.reason or "human approval denied"
            run.transition(VerificationPhase.REJECTED)
            return run
        if not approval.approver_id:
            raise HumanApprovalError("approved decision requires approver_id")
        candidate = run.candidates[-1]
        report = run.reports[-1]
        run.accepted_output = (
            accept(candidate, report)
            if accept is not None
            else candidate.output
        )
        run.transition(VerificationPhase.ACCEPTED)
        return run

    def _verify(
        self,
        candidate: VerificationCandidate,
        context: Mapping[str, Any],
    ) -> VerificationReport:
        results: list[VerifierResult] = []
        issues: list[VerificationIssue] = []
        for verifier in self.verifiers:
            try:
                result = verifier.verify(candidate, context)
            except Exception as exc:
                result = VerifierResult(
                    verifier=getattr(verifier, "name", type(verifier).__name__),
                    accepted=False,
                    score=0.0,
                    issues=(
                        VerificationIssue(
                            "verifier.exception",
                            str(exc),
                            getattr(
                                verifier,
                                "name",
                                type(verifier).__name__,
                            ),
                            repairable=False,
                        ),
                    ),
                )
            results.append(result)
            issues.extend(result.issues)
        accepted = all(item.accepted for item in results)
        score = sum(item.score for item in results) / len(results)
        return VerificationReport(
            accepted=accepted,
            score=round(score, 6),
            results=tuple(results),
            issues=tuple(issues),
        )

    @staticmethod
    def _candidate(
        value: VerificationCandidate | Any,
        *,
        version: int,
    ) -> VerificationCandidate:
        if isinstance(value, VerificationCandidate):
            return value
        return VerificationCandidate(output=value, version=version)

    @staticmethod
    def _default_critique(report: VerificationReport) -> Critique:
        return Critique(
            summary=f"{len(report.issues)} verification issue(s)",
            issues=report.issues,
            repair_instructions=tuple(
                item.message for item in report.issues if item.repairable
            ),
        )


__all__ = [
    "HumanApprovalBoundary",
    "VerificationRepairRuntime",
]
