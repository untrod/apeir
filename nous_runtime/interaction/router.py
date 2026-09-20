"""Intent route selection."""

from __future__ import annotations

from nous_runtime.interaction import intent
from nous_runtime.interaction.models import IntentDecision


_ROUTES = {
    intent.CONTINUE: "runtime.pipeline.continue",
    intent.CREATE: "workspace.create",
    intent.EXECUTE: "runtime.pipeline.execute",
    intent.PAUSE: "runtime.session.pause",
    intent.RESUME: "runtime.session.resume",
    intent.CANCEL: "runtime.session.cancel",
    intent.STATUS: "runtime.status",
    intent.EXPLAIN: "runtime.session.explain",
    intent.APPROVE: "governance.approval.approve",
    intent.REJECT: "governance.approval.deny",
    intent.SWITCH_WORKSPACE: "workspace.switch",
}


def route_intent(decision: IntentDecision) -> str:
    return _ROUTES.get(decision.intent, "runtime.confirmation.required")


def list_routes() -> dict[str, str]:
    return dict(_ROUTES)
