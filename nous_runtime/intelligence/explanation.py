"""Decision explanation helpers."""

from __future__ import annotations

from nous_runtime.intelligence.models import RuntimeDecision


def explain_decision(decision: RuntimeDecision) -> str:
    lines = [
        f"Decision {decision.decision_id}",
        f"Type: {decision.decision_type.value}",
        f"Selected: {decision.selected}",
        f"Policy: {decision.policy_id} v{decision.policy_version}",
        f"Confidence: {decision.confidence:.2f}",
        "Reasons:",
    ]
    for reason in decision.reasons:
        lines.append(f"- {reason.code}: {reason.message}")
    return "\n".join(lines)
