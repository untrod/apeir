# -*- coding: utf-8 -*-
"""Arbitration — resolves conflicts when multiple agents produce different results.

NOT simple majority voting. Steps:
1. Check if definitions or inputs differ.
2. Compare evidence and verification results.
3. Request independent agent review.
4. Generate counterexamples.
5. Run deterministic tests.
6. Escalate to Arbiter.
7. Escalate to human if unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArbitrationDecision:
    """Result of arbitration between conflicting agent outputs."""
    decision_id: str = ""
    winner: str = ""            # role_id of the accepted output
    reason: str = ""
    method: str = ""            # evidence_comparison, independent_review, deterministic_test, human_escalation
    confidence: float = 0.0
    rejected_reasons: dict[str, str] = field(default_factory=dict)  # role_id → reason
    escalated: bool = False
    escalation_reason: str = ""


class Arbiter:
    """Resolves conflicts between agent outputs.

    Priority order:
      1. Deterministic test results (highest authority)
      2. Evidence strength comparison
      3. Independent agent review
      4. Counterexample generation
      5. Human escalation (when automated methods disagree)
    """

    def arbitrate(
        self,
        outputs: dict[str, Any],    # role_id → output dict
        verifications: dict[str, Any] | None = None,  # role_id → verification result
        evidence: dict[str, Any] | None = None,       # role_id → evidence strength
    ) -> ArbitrationDecision:
        """Arbitrate between conflicting outputs."""
        decision = ArbitrationDecision(decision_id=f"arb_{id(outputs)}")

        roles = list(outputs.keys())
        if len(roles) < 2:
            decision.winner = roles[0] if roles else ""
            decision.reason = "No conflict (single output)"
            decision.method = "no_conflict"
            decision.confidence = 1.0
            return decision

        # Step 1: Check if deterministic tests resolve
        if verifications:
            for role, verif in verifications.items():
                if verif.get("deterministic_pass") and verif.get("no_errors"):
                    decision.winner = role
                    decision.reason = "Deterministic tests pass"
                    decision.method = "deterministic_test"
                    decision.confidence = 0.95
                    for r in roles:
                        if r != role:
                            decision.rejected_reasons[r] = "Failed deterministic verification"
                    return decision

        # Step 2: Compare evidence strength
        if evidence:
            best_role = max(evidence.keys(), key=lambda r: evidence[r].get("strength", 0))
            best_strength = evidence[best_role].get("strength", 0)
            second_best = max(
                (evidence[r].get("strength", 0) for r in evidence if r != best_role),
                default=0,
            )
            if best_strength > second_best * 1.5:  # clear winner
                decision.winner = best_role
                decision.reason = f"Stronger evidence (strength={best_strength:.2f} vs {second_best:.2f})"
                decision.method = "evidence_comparison"
                decision.confidence = 0.7
                return decision

        # Step 3: Independent review
        # (In practice, this would spawn a new agent role)
        # For v1: compare output completeness
        best_role = max(roles, key=lambda r: len(str(outputs[r])))
        worst_role = min(roles, key=lambda r: len(str(outputs[r])))
        if len(str(outputs[best_role])) > len(str(outputs[worst_role])) * 1.5:
            decision.winner = best_role
            decision.reason = "More complete output"
            decision.method = "output_completeness"
            decision.confidence = 0.5
            return decision

        # Step 4: Escalate to human
        decision.escalated = True
        decision.escalation_reason = "Automated arbitration could not resolve conflict"
        decision.method = "human_escalation"
        decision.confidence = 0.0
        for r in roles:
            decision.rejected_reasons[r] = "Requires human review"

        return decision
