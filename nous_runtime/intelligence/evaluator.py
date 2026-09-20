"""Policy dry-run helpers."""

from __future__ import annotations

from nous_runtime.intelligence.engine import RuntimePolicyEngine
from nous_runtime.intelligence.models import DecisionRequest, RuntimeDecision


def dry_run(request: DecisionRequest, engine: RuntimePolicyEngine | None = None) -> RuntimeDecision:
    return (engine or RuntimePolicyEngine()).decide(request, dry_run=True)
