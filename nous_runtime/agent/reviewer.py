# -*- coding: utf-8 -*-
"""
Reviewer Agent for Nous Runtime.

Implements §14 Agent Graph (Reviewer role) from the master plan.
The Reviewer independently evaluates plan quality, execution correctness,
and flags issues before verification. It acts as a second pair of eyes.

Reviewer responsibilities:
- Evaluate plan feasibility before approval
- Check execution output for correctness
- Flag risks, missing steps, or logical errors
- Provide confidence scores
- Never self-approve its own output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.agent.reviewer")


@dataclass
class ReviewFinding:
    """A single finding from a review."""
    finding_id: str = field(default_factory=lambda: make_id(prefix="revf"))
    severity: str = "info"               # info | warning | error | critical
    category: str = ""                   # correctness, security, performance, style, risk
    title: str = ""
    description: str = ""
    location: str = ""                   # Which step/file/artifact
    suggestion: str = ""                 # How to fix
    confidence: float = 1.0              # 0.0–1.0


@dataclass
class ReviewReport:
    """Complete review of a plan or execution result."""
    review_id: str = field(default_factory=lambda: make_id(prefix="review"))
    target_type: str = ""                # plan | execution | artifact
    target_id: str = ""                  # plan_id, task_id, or artifact_id
    findings: list[ReviewFinding] = field(default_factory=list)
    overall_assessment: str = ""         # acceptable | needs_improvement | rejected
    confidence_score: float = 0.0        # 0.0–1.0
    reviewer_id: str = ""                # Which reviewer produced this
    model_used: str = ""                 # Which model was the reviewer
    reviewed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    review_duration_ms: int = 0

    @property
    def is_acceptable(self) -> bool:
        return self.overall_assessment == "acceptable"

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("error", "critical"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "findings": [
                {"severity": f.severity, "category": f.category,
                 "title": f.title, "suggestion": f.suggestion}
                for f in self.findings
            ],
            "overall_assessment": self.overall_assessment,
            "confidence_score": self.confidence_score,
            "reviewed_at": self.reviewed_at,
        }


class ReviewerAgent:
    """Independent reviewer that evaluates plans and execution results.

    The Reviewer is a distinct agent with its own budget, context window,
    and termination condition. It never modifies content — only evaluates.
    """

    def __init__(self, reviewer_id: str = "", model_invoke: Callable = None):
        self._reviewer_id = reviewer_id or f"reviewer-{make_id(prefix='rev')}"
        self._model_invoke = model_invoke

    def review_plan(self, plan: dict[str, Any]) -> ReviewReport:
        """Review a proposed execution plan for quality and risks."""
        findings = []

        # Structural checks
        if not plan.get("objective"):
            findings.append(ReviewFinding(
                severity="critical", category="correctness",
                title="Missing objective", description="Plan has no objective defined",
            ))
        if not plan.get("steps"):
            findings.append(ReviewFinding(
                severity="critical", category="correctness",
                title="No steps defined", description="Plan has no execution steps",
            ))

        # Risk checks
        risk_level = plan.get("risk_level", "LOW")
        if risk_level in ("HIGH", "CRITICAL"):
            if not plan.get("rollback"):
                findings.append(ReviewFinding(
                    severity="warning", category="risk",
                    title="No rollback plan",
                    description=f"High-risk plan ({risk_level}) has no rollback strategy",
                    suggestion="Add rollback steps or reduce risk level",
                ))
            if not plan.get("verification"):
                findings.append(ReviewFinding(
                    severity="warning", category="risk",
                    title="No verification plan",
                    description=f"High-risk plan ({risk_level}) has no verification steps",
                    suggestion="Add post-execution verification",
                ))

        # Budget check
        budget = plan.get("budget", {})
        if not budget or budget.get("max_cost_cents", 0) == 0:
            findings.append(ReviewFinding(
                severity="info", category="risk",
                title="No budget limit",
                description="Plan has no cost budget defined",
                suggestion="Set max_cost_cents to prevent runaway costs",
            ))

        # Dependency check
        steps = plan.get("steps", [])
        if len(steps) > 10:
            findings.append(ReviewFinding(
                severity="info", category="style",
                title="Many steps",
                description=f"Plan has {len(steps)} steps — consider breaking into sub-tasks",
                suggestion="Split into multiple smaller plans",
            ))

        return self._assess(findings, target_type="plan", target_id=plan.get("plan_id", ""))

    def review_execution(self, task_result: dict[str, Any],
                         expected: dict[str, Any]) -> ReviewReport:
        """Review execution results against expectations."""
        findings = []

        # Compare output to expected
        actual_output = task_result.get("output", "")
        expected_output = expected.get("output", "")

        if expected_output and not actual_output:
            findings.append(ReviewFinding(
                severity="error", category="correctness",
                title="No output produced", description="Expected output but got nothing",
            ))

        # Check return code
        rc = task_result.get("returncode", -1)
        if rc != 0:
            findings.append(ReviewFinding(
                severity="error" if rc < 0 else "warning",
                category="correctness",
                title=f"Non-zero return code: {rc}",
                description="Execution returned an error code",
            ))

        # Check for error messages in output
        error_indicators = ["error", "exception", "traceback", "failed", "denied"]
        output_lower = str(actual_output).lower()
        for indicator in error_indicators:
            if indicator in output_lower:
                findings.append(ReviewFinding(
                    severity="warning", category="correctness",
                    title=f"Found '{indicator}' in output",
                    description="Output may contain error messages",
                ))
                break

        return self._assess(findings, target_type="execution",
                           target_id=task_result.get("task_id", ""))

    def _assess(self, findings: list[ReviewFinding],
                target_type: str, target_id: str) -> ReviewReport:
        """Evaluate findings and produce an assessment."""
        has_critical = any(f.severity == "critical" for f in findings)
        has_error = any(f.severity == "error" for f in findings)
        has_warning = any(f.severity == "warning" for f in findings)

        if has_critical:
            assessment = "rejected"
            confidence = 0.95
        elif has_error:
            assessment = "needs_improvement"
            confidence = 0.8
        elif has_warning:
            assessment = "needs_improvement"
            confidence = 0.7
        else:
            assessment = "acceptable"
            confidence = 0.9

        return ReviewReport(
            target_type=target_type,
            target_id=target_id,
            findings=findings,
            overall_assessment=assessment,
            confidence_score=confidence,
            reviewer_id=self._reviewer_id,
        )
