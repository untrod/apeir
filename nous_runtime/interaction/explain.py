"""Human-readable intent explanations."""

from __future__ import annotations

from nous_runtime.interaction.models import IntentDecision


def explain_intent(decision: IntentDecision) -> str:
    confirm = " Confirmation is required." if decision.requires_confirmation else ""
    return (
        f"Intent {decision.intent} confidence={decision.confidence:.2f}; "
        f"route={decision.route or 'unresolved'}. {decision.reason}{confirm}"
    )
