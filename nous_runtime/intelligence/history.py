"""Decision history, replay, and metrics storage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from nous_runtime.intelligence.engine import RuntimePolicyEngine
from nous_runtime.intelligence.lifecycle import DecisionLifecycleService, build_execution_outcome
from nous_runtime.intelligence.models import DecisionRequest, ExecutionOutcome, RuntimeDecision
from nous_runtime.intelligence.store import JsonlDecisionStore


class DecisionHistory:
    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path)
        self.root = Path(workspace_path) / "decisions"
        self.decisions_path = self.root / "decisions.jsonl"
        self.outcomes_path = self.root / "outcomes.jsonl"
        self.metrics_path = self.root / "metrics.jsonl"
        self.store = JsonlDecisionStore(workspace_path)

    def append(self, decision: RuntimeDecision) -> None:
        self._append(self.decisions_path, decision.to_dict())
        DecisionLifecycleService(self.store).record_decision_created(decision, source="history.append")

    def list(self, limit: int = 50) -> list[RuntimeDecision]:
        decisions = [RuntimeDecision.from_dict(item) for item in _read_jsonl(self.decisions_path)]
        return decisions[-limit:]

    def get(self, decision_id: str) -> RuntimeDecision | None:
        for decision in reversed(self.list(limit=10000)):
            if decision.decision_id == decision_id:
                return decision
        return None

    def replay(self, decision_id: str, engine: RuntimePolicyEngine | None = None) -> RuntimeDecision:
        original = self.get(decision_id)
        if original is None:
            raise KeyError(f"decision not found: {decision_id}")
        request = DecisionRequest.from_dict(original.inputs_snapshot)
        replayed = (engine or RuntimePolicyEngine()).decide(request)
        # Replay is an identity-preserving verification of the recorded input.
        # Preserve the original record key while exposing any changed outcome.
        return replace(replayed, decision_id=original.decision_id)

    def append_outcome(self, decision_id: str, outcome: dict[str, Any]) -> None:
        self._append(self.outcomes_path, {"decision_id": decision_id, "outcome": outcome})
        decision = self.get(decision_id)
        if decision is not None:
            status = outcome.get("status") or ("succeeded" if outcome.get("ok") is True else "failed" if outcome.get("ok") is False else "succeeded")
            execution = build_execution_outcome(
                decision,
                execution_id=str(outcome.get("execution_id") or ""),
                status=status,
                metadata=outcome,
            )
            DecisionLifecycleService(self.store).record_execution_completion(
                decision,
                execution_id=execution.execution_id,
                status=execution.status,
                metadata=outcome,
                error=execution.error,
                source="history.append_outcome",
            )

    def list_outcomes(self, limit: int = 50, decision_id: str = "") -> list[ExecutionOutcome]:
        return self.store.list_outcomes(limit=limit, decision_id=decision_id)

    def metrics(self) -> dict[str, Any]:
        outcomes = _read_jsonl(self.outcomes_path)
        decisions = [RuntimeDecision.from_dict(item) for item in _read_jsonl(self.decisions_path)]
        total = len(outcomes)
        success = sum(1 for item in outcomes if item.get("outcome", {}).get("ok") is True)
        fallback = sum(1 for item in outcomes if item.get("outcome", {}).get("fallback") is True)
        retry = sum(1 for item in outcomes if item.get("outcome", {}).get("retry") is True)
        by_type: dict[str, int] = {}
        selected: dict[str, int] = {}
        for decision in decisions:
            by_type[decision.decision_type.value] = by_type.get(decision.decision_type.value, 0) + 1
            key = f"{decision.decision_type.value}:{decision.selected}"
            selected[key] = selected.get(key, 0) + 1
        return {
            "decisions": len(decisions),
            "by_type": by_type,
            "selected": selected,
            "total": total,
            "success_rate": success / total if total else 0.0,
            "fallback_rate": fallback / total if total else 0.0,
            "retry_rate": retry / total if total else 0.0,
        }

    def _append(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows
