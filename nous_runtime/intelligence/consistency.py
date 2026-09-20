"""Cross-store consistency diagnostics for P5 execution records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nous_runtime.intelligence.profiles.store import JsonlProfileStore
from nous_runtime.intelligence.reliability.store import JsonlReliabilityStore
from nous_runtime.intelligence.store import JsonlDecisionStore


@dataclass(frozen=True)
class StoreConsistencyFinding:
    code: str
    severity: str
    component: str
    message: str
    remediation: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "component": self.component,
            "message": self.message,
            "remediation": self.remediation,
            "metadata": dict(self.metadata or {}),
        }


def verify_cross_store_consistency(workspace_path: str | Path) -> dict[str, Any]:
    workspace = Path(workspace_path)
    decision_store = JsonlDecisionStore(workspace)
    profile_store = JsonlProfileStore(workspace)
    reliability_store = JsonlReliabilityStore(workspace)

    findings: list[StoreConsistencyFinding] = []
    decisions = decision_store.list_decisions(limit=10000)
    outcomes = decision_store.list_outcomes(limit=10000)
    signals = reliability_store.list_signals(limit=10000)
    retries = reliability_store.list_retries(limit=10000)
    health = reliability_store.list_health(limit=10000)
    fallbacks = reliability_store.list_fallbacks(limit=10000)
    perf = profile_store.list_performance_observations(limit=10000)

    decision_ids = {item.decision_id for item in decisions}
    outcome_exec_ids = {item.execution_id for item in outcomes if item.execution_id}
    signal_exec_refs = {str(item.evidence.get("execution_id")) for item in signals if item.evidence.get("execution_id")}
    perf_exec_refs = {str(item.metadata.get("execution_id")) for item in perf if item.metadata.get("execution_id")}
    profile_keys = {(item.provider_id, item.model_id) for item in perf}
    health_keys = {(item.provider_id, item.model_id) for item in health}

    for outcome in outcomes:
        if outcome.decision_id and outcome.decision_id not in decision_ids:
            findings.append(StoreConsistencyFinding(
                "ORPHAN_OUTCOME",
                "warning",
                "decision",
                f"Outcome {outcome.outcome_id} references missing decision {outcome.decision_id}.",
                "Inspect the outcome and rebuild or remove the orphan record.",
                {"outcome_id": outcome.outcome_id, "decision_id": outcome.decision_id},
            ))
        if outcome.execution_id and outcome.execution_id not in perf_exec_refs:
            findings.append(StoreConsistencyFinding(
                "MISSING_PROFILE_OBSERVATION",
                "warning",
                "profile",
                f"Execution {outcome.execution_id} has no linked profile observation.",
                "Re-run profile observation reconciliation if provider/model IDs are available.",
                {"execution_id": outcome.execution_id},
            ))
    for retry in retries:
        if retry.execution_id and retry.execution_id not in outcome_exec_ids and retry.execution_id not in signal_exec_refs:
            findings.append(StoreConsistencyFinding(
                "ORPHAN_RETRY_ATTEMPT",
                "warning",
                "reliability",
                f"Retry attempt {retry.attempt_id} has no linked outcome or signal.",
                "Check whether execution was interrupted before outcome persistence.",
                {"attempt_id": retry.attempt_id, "execution_id": retry.execution_id},
            ))
    for signal in signals:
        if signal.provider_id and (signal.provider_id, signal.model_id) not in health_keys:
            findings.append(StoreConsistencyFinding(
                "MISSING_HEALTH_SNAPSHOT",
                "warning",
                "reliability",
                f"Signal {signal.signal_id} has no matching health snapshot.",
                "Run provider reliability verify after the next provider execution.",
                {"signal_id": signal.signal_id, "provider_id": signal.provider_id, "model_id": signal.model_id},
            ))
    seen_obs: set[str] = set()
    for obs in perf:
        if obs.observation_id in seen_obs:
            findings.append(StoreConsistencyFinding(
                "DUPLICATE_PROFILE_OBSERVATION",
                "error",
                "profile",
                f"Profile observation {obs.observation_id} is duplicated.",
                "Rebuild profile indexes and inspect duplicate writer paths.",
                {"observation_id": obs.observation_id},
            ))
        seen_obs.add(obs.observation_id)
    for fallback in fallbacks:
        if fallback.original_execution_id and fallback.original_execution_id not in outcome_exec_ids:
            findings.append(StoreConsistencyFinding(
                "ORPHAN_FALLBACK",
                "warning",
                "reliability",
                f"Fallback {fallback.fallback_id} references missing execution {fallback.original_execution_id}.",
                "Inspect fallback chain and execution outcome records.",
                {"fallback_id": fallback.fallback_id, "execution_id": fallback.original_execution_id},
            ))

    return {
        "ok": not any(item.severity == "error" for item in findings),
        "findings": [item.to_dict() for item in findings],
        "counts": {
            "decisions": len(decisions),
            "outcomes": len(outcomes),
            "signals": len(signals),
            "retries": len(retries),
            "health_snapshots": len(health),
            "fallbacks": len(fallbacks),
            "profile_observations": len(perf),
            "profile_keys": len(profile_keys),
        },
    }
