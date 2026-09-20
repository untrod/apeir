"""Deterministic first-pass intent classification."""

from __future__ import annotations

from nous_runtime.interaction import intent
from nous_runtime.interaction.models import IntentDecision, IntentRequest


class IntentClassifier:
    """Classifies user text into stable runtime intents."""

    _RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (intent.SWITCH_WORKSPACE, ("switch workspace", "change workspace")),
        (intent.CONTINUE, ("continue", "go on", "resume my project", "continue project")),
        (intent.CREATE, ("create", "new project", "init", "initialize")),
        (intent.PAUSE, ("pause", "hold")),
        (intent.RESUME, ("resume", "restart task")),
        (intent.CANCEL, ("cancel", "stop task")),
        (intent.STATUS, ("status", "progress", "health")),
        (intent.EXPLAIN, ("explain", "why")),
        (intent.APPROVE, ("approve", "allow", "yes")),
        (intent.REJECT, ("reject", "deny", "no")),
        (intent.EXECUTE, ("execute", "run", "do it", "start")),
    )
    _DESTRUCTIVE = ("delete", "remove", "rm ", "format", "drop", "destroy", "wipe")
    _CJK_HINTS: tuple[tuple[str, str], ...] = (
        (intent.SWITCH_WORKSPACE, "\u5207\u6362"),
        (intent.CONTINUE, "\u7ee7\u7eed"),
        (intent.CREATE, "\u521b\u5efa"),
        (intent.CREATE, "\u65b0\u5efa"),
        (intent.PAUSE, "\u6682\u505c"),
        (intent.RESUME, "\u6062\u590d"),
        (intent.CANCEL, "\u53d6\u6d88"),
        (intent.STATUS, "\u72b6\u6001"),
        (intent.EXPLAIN, "\u89e3\u91ca"),
        (intent.EXPLAIN, "\u4e3a\u4ec0\u4e48"),
        (intent.APPROVE, "\u540c\u610f"),
        (intent.REJECT, "\u62d2\u7edd"),
        (intent.EXECUTE, "\u6267\u884c"),
        (intent.EXECUTE, "\u5f00\u59cb"),
    )
    _CJK_DESTRUCTIVE = ("\u5220\u9664", "\u6e05\u7a7a", "\u9500\u6bc1")

    def classify(self, request: IntentRequest) -> IntentDecision:
        text = request.input_text.strip()
        lowered = text.lower()
        destructive = any(marker in lowered for marker in self._DESTRUCTIVE) or any(
            marker in text for marker in self._CJK_DESTRUCTIVE
        )

        for name, keywords in self._RULES:
            if any(keyword in lowered for keyword in keywords):
                return self._decision(name, request, destructive)

        for name, marker in self._CJK_HINTS:
            if marker in text:
                return self._decision(name, request, destructive)

        if destructive:
            return IntentDecision(
                intent=intent.EXECUTE,
                confidence=0.55,
                workspace=request.workspace_hint,
                requires_confirmation=True,
                reason="Destructive action hint requires explicit confirmation.",
                metadata={"destructive_hint": True},
            )

        return IntentDecision(
            intent=intent.UNKNOWN,
            confidence=0.25,
            workspace=request.workspace_hint,
            requires_confirmation=True,
            reason="No deterministic intent rule matched.",
        )

    def _decision(self, name: str, request: IntentRequest, destructive: bool) -> IntentDecision:
        confidence = 0.86 if not destructive else 0.62
        return IntentDecision(
            intent=name,
            confidence=confidence,
            workspace=request.workspace_hint,
            requires_confirmation=destructive or confidence < 0.7,
            reason=f"Matched deterministic intent rule for {name}.",
            metadata={"destructive_hint": destructive},
        )


def classify_intent(input_text: str, *, user_id: str = "local", workspace_hint: str = "") -> IntentDecision:
    request = IntentRequest(input_text=input_text, user_id=user_id, workspace_hint=workspace_hint)
    return IntentClassifier().classify(request)
