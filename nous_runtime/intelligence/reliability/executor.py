"""Reliability-aware provider execution wrapper."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.intelligence.lifecycle import lifecycle_for_workspace, record_provider_outcome
from nous_runtime.intelligence.models import DecisionContext, DecisionRequest, DecisionType
from nous_runtime.intelligence.engine import RuntimePolicyEngine
from nous_runtime.intelligence.reliability.classifier import classify_failure
from nous_runtime.intelligence.reliability.models import (
    CircuitState,
    CircuitStateRecord,
    FailureCategory,
    FailureSignal,
    FallbackExecution,
    ProviderExecutionResult,
    ProviderHealthSnapshot,
    RetryAttempt,
    RetryPolicy,
    snapshot_hash,
)
from nous_runtime.intelligence.reliability.fallback import (
    FallbackBoundary,
    FallbackCompatibility,
    FallbackExecutionPolicy,
    assess_fallback_safety,
)
from nous_runtime.intelligence.reliability.retry import RetryBudget, RetryController
from nous_runtime.intelligence.reliability.store import JsonlReliabilityStore, ReliabilityStore
from nous_runtime.planner.observation import Observation


def execute_provider_observation(
    provider_id: str,
    capability_id: str,
    *,
    payload: dict[str, Any] | None = None,
    workspace_path: str | Path | None = None,
    store: ReliabilityStore | None = None,
    retry_policy: RetryPolicy | None = None,
) -> Observation:
    result = execute_provider(
        provider_id,
        capability_id,
        payload=payload or {},
        workspace_path=workspace_path,
        store=store,
        retry_policy=retry_policy,
    )
    return observation_from_provider_result(result)


def execute_provider(
    provider_id: str,
    capability_id: str,
    *,
    payload: dict[str, Any],
    workspace_path: str | Path | None = None,
    store: ReliabilityStore | None = None,
    retry_policy: RetryPolicy | None = None,
) -> ProviderExecutionResult:
    workspace = Path(workspace_path) if workspace_path else _workspace()
    reliability_store = store or (JsonlReliabilityStore(workspace) if workspace else None)
    model_id = str(payload.get("model") or "")
    execution_id = snapshot_hash({"provider": provider_id, "capability": capability_id, "payload": payload, "ts": datetime.now(timezone.utc).isoformat()})
    authorization_failure = _authorize_provider_execution(
        provider_id,
        model_id,
        capability_id,
        payload,
        execution_id=execution_id,
        workspace=workspace,
    )
    if authorization_failure is not None:
        _persist_result(authorization_failure, reliability_store, workspace, payload, attempts=())
        return authorization_failure

    circuit_failure = _circuit_failure(provider_id, model_id, capability_id, reliability_store, probe=bool(payload.get("_reliability_probe")))
    if circuit_failure is not None:
        result = ProviderExecutionResult(
            execution_id=execution_id,
            success=False,
            provider_id=provider_id,
            model_id=model_id,
            capability_id=capability_id,
            failure=circuit_failure,
            provider_error_code="NOUS_CIRCUIT_OPEN",
        )
        _persist_result(result, reliability_store, workspace, payload, attempts=())
        return result

    retry = RetryController(
        retry_policy
        or RetryPolicy(policy_id="provider.execution", max_attempts=int(payload.get("_max_attempts") or 2), base_backoff_ms=0.0, jitter_ratio=0.0)
    )
    budget = RetryBudget(max_attempts=retry.policy.max_attempts)
    attempt_results: list[ProviderExecutionResult] = []

    def invoke_once() -> dict[str, Any]:
        attempt_result = _invoke_provider(provider_id, capability_id, payload, execution_id=execution_id)
        attempt_results.append(attempt_result)
        if attempt_result.success:
            return {"ok": True, "result": attempt_result.to_dict()}
        failure = attempt_result.failure
        return {
            "ok": False,
            "error": failure.explanation if failure else "provider execution failed",
            "_failure_signal": failure,
        }

    attempts: list[RetryAttempt] = []

    def on_attempt(attempt: RetryAttempt) -> None:
        attempts.append(attempt)
        if reliability_store is not None:
            reliability_store.append_retry_attempt(attempt)
            if attempt.failure is not None:
                reliability_store.append_signal(attempt.failure)

    raw_result, attempts = retry.execute_with_retry(
        invoke_once,
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        is_idempotent=_is_idempotent(capability_id, payload),
        has_idempotency_key=bool(payload.get("idempotency_key") or payload.get("_idempotency_key")),
        budget=budget,
        on_attempt=on_attempt,
    )
    final = _final_execution_result(
        execution_id,
        provider_id,
        model_id,
        capability_id,
        raw_result,
        attempt_results,
    )
    fallback = _maybe_execute_fallback(final, reliability_store, workspace, payload)
    if fallback is not None:
        final = fallback
    _persist_result(final, reliability_store, workspace, payload, attempts=tuple(attempts), attempt_results=tuple(attempt_results))
    return final


def _authorize_provider_execution(
    provider_id: str,
    model_id: str,
    capability_id: str,
    payload: dict[str, Any],
    *,
    execution_id: str,
    workspace: Path | None,
) -> ProviderExecutionResult | None:
    try:
        from nous_runtime.governance import ActionProposal, AuthorizationContext, get_gate
        from nous_runtime.governance.runtime_mode import should_fail_closed
        import getpass
        import os

        proposal = ActionProposal(
            action_type="provider.execute",
            capability_id=capability_id,
            provider_id=provider_id,
            model_id=model_id,
            target_workspace=str(workspace or ""),
            side_effect_class=_provider_side_effect(capability_id),
            reversibility=_provider_reversibility(capability_id),
            params=_provider_payload(payload),
            estimated_cost_usd=float(payload.get("_estimated_cost_usd") or payload.get("estimated_cost_usd") or 0.0),
            required_permissions=tuple(str(v) for v in (payload.get("_permissions") or ())),
            locality=str(payload.get("_locality") or "local"),
        )
        context = AuthorizationContext(
            subject_type=str(payload.get("_subject_type") or "user"),
            subject_id=str(payload.get("_subject_id") or f"{getpass.getuser()}@{os.environ.get('COMPUTERNAME', 'localhost')}"),
            authn_method=str(payload.get("_authn_method") or "cli_os_user"),
            authn_confidence=float(payload.get("_authn_confidence") or 0.8),
            session_locality=str(payload.get("_session_locality") or "local"),
        )
        decision = get_gate().evaluate(proposal, context)
        fail_closed = should_fail_closed(surface="local_cli")
        if decision.action_mode in {"DENY", "ASK_APPROVAL", "ESCALATE"}:
            if fail_closed or decision.rule_class == "NON_OVERRIDABLE":
                failure = classify_failure(
                    provider_error_code=f"NOUS_GOVERNANCE_{decision.action_mode}",
                    provider_id=provider_id,
                    model_id=model_id,
                    capability_id=capability_id,
                    raw_error=decision.reason_message or decision.reason_code,
                )
                return ProviderExecutionResult(
                    execution_id=execution_id,
                    success=False,
                    provider_id=provider_id,
                    model_id=model_id,
                    capability_id=capability_id,
                    failure=failure,
                    provider_error_code=f"NOUS_GOVERNANCE_{decision.action_mode}",
                )
        return None
    except Exception as exc:
        from nous_runtime.governance.runtime_mode import should_fail_closed

        if should_fail_closed(surface="local_cli"):
            failure = classify_failure(
                provider_error_code="NOUS_GOVERNANCE_UNAVAILABLE",
                provider_id=provider_id,
                model_id=model_id,
                capability_id=capability_id,
                raw_error=str(exc),
            )
            return ProviderExecutionResult(
                execution_id=execution_id,
                success=False,
                provider_id=provider_id,
                model_id=model_id,
                capability_id=capability_id,
                failure=failure,
                provider_error_code="NOUS_GOVERNANCE_UNAVAILABLE",
            )
        return None


def _provider_side_effect(capability_id: str) -> str:
    """Infer side-effect class for provider authorization.

    v0.2.0: Checks capability metadata first, then category map,
    then legacy keyword/prefix patterns.
    """
    # 1. Check declared metadata
    declared = _get_declared_side_effect(capability_id)
    if declared:
        return declared

    # 2. Explicit keyword patterns
    if capability_id in {"system.echo", "system.status"}:
        return "read_only"
    if "delete" in capability_id or "exec" in capability_id or "shell" in capability_id:
        return "destructive"
    if "write" in capability_id:
        return "local_write"

    # 3. Category-based fallback
    category = _get_capability_category(capability_id)
    category_side_effects = {
        "model": "read_only",
        "rag": "read_only",
        "device": "local_write",
        "software": "local_write",
        "agent": "external_write",
        "tool": "local_write",
        "notification": "read_only",
        "automation": "read_only",
        "connector": "external_write",
    }
    if category in category_side_effects:
        return category_side_effects[category]

    # 4. Conservative keyword fallback (no prefix magic)
    if "read" in capability_id or "search" in capability_id:
        return "read_only"
    return "unknown"


def _get_declared_side_effect(capability_id: str) -> str:
    """Return side_effect_class from capability metadata, or ''."""
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            meta = cap.get("metadata", {})
            if isinstance(meta, dict):
                return str(meta.get("side_effect_class", ""))
    except Exception:
        pass
    return ""


def _provider_reversibility(capability_id: str) -> str:
    """Infer reversibility for provider authorization.

    v0.2.0: declared metadata -> keyword signals -> category map -> "unknown".
    Deliberately separate from capability.resolver's maps: the provider layer
    treats model calls as read_only/reversible while the capability layer
    treats them as external side effects.
    """
    # 1. Check declared metadata
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            meta = cap.get("metadata", {})
            if isinstance(meta, dict) and meta.get("reversibility"):
                return str(meta["reversibility"])
    except Exception:
        pass

    # 2. Explicit keyword patterns
    if "exec" in capability_id or "shell" in capability_id or "delete" in capability_id:
        return "irreversible"

    # 3. Category-based fallback
    category = _get_capability_category(capability_id)
    category_reversibility = {
        "model": "reversible",
        "rag": "reversible",
        "notification": "reversible",
        "device": "partially_reversible",
        "software": "partially_reversible",
        "tool": "partially_reversible",
        "agent": "partially_reversible",
        "automation": "partially_reversible",
        "connector": "partially_reversible",
    }
    if category in category_reversibility:
        return category_reversibility[category]

    # 4. Conservative fallback
    return "unknown"


def _get_capability_category(capability_id: str) -> str:
    """Return the category of a registered capability."""
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            return str(cap.get("category", ""))
    except Exception:
        pass
    return ""


def observation_from_provider_result(result: ProviderExecutionResult) -> Observation:
    metadata = {
        "provider_id": result.provider_id,
        "provider_name": result.provider_id,
        "model_id": result.model_id,
        "error_code": "" if result.success else result.provider_error_code or (result.failure.category.value if result.failure else "NOUS_PROVIDER_FAILED"),
        "execution_id": result.execution_id,
        "reliability_wrapped": True,
    }
    if result.success:
        return Observation.success(
            "provider.invoke",
            {"result": result.retry_metadata.get("result", {"ok": True})},
            capability=result.capability_id,
            duration_ms=result.latency_ms,
            metadata=metadata,
        )
    return Observation.failure(
        "provider.invoke",
        [result.failure.explanation if result.failure else "provider execution failed"],
        capability=result.capability_id,
        duration_ms=result.latency_ms,
        metadata=metadata,
    )


def _invoke_provider(provider_id: str, capability_id: str, payload: dict[str, Any], *, execution_id: str) -> ProviderExecutionResult:
    started = time.perf_counter()
    model_id = str(payload.get("model") or "")
    from nous_runtime.model_runtime.compatibility import (
        invoke_provider_via_gateway,
    )

    gateway_result = invoke_provider_via_gateway(
        provider_id,
        capability_id,
        payload,
        execution_id=execution_id,
    )
    return _gateway_mapping_result(
        execution_id,
        provider_id,
        model_id,
        capability_id,
        started,
        gateway_result,
    )


def _gateway_mapping_result(
    execution_id: str,
    provider_id: str,
    model_id: str,
    capability_id: str,
    started: float,
    result: dict[str, Any],
) -> ProviderExecutionResult:
    if bool(result.get("ok", False)):
        validation = result.get("validation_result")
        return ProviderExecutionResult(
            execution_id=execution_id,
            success=True,
            provider_id=provider_id,
            model_id=str(result.get("model") or model_id),
            capability_id=capability_id,
            latency_ms=int(
                result.get("latency_ms") or _elapsed_ms(started)
            ),
            token_usage=dict(result.get("token_usage") or {}),
            cost=(
                float(result["cost"])
                if result.get("cost") is not None
                else None
            ),
            response_id=str(result.get("response_id") or ""),
            validation_result=(
                validation if isinstance(validation, bool) else None
            ),
            retry_metadata={
                "result": result,
                "gateway_routed": True,
            },
        )
    error = str(
        result.get("error")
        or result.get("message")
        or "gateway provider invocation failed"
    )
    error_code = str(
        result.get("_provider_error_code")
        or result.get("error_code")
        or "ModelInvocationError"
    )
    failure = classify_failure(
        provider_error_code=error_code,
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        raw_error=error,
    )
    return ProviderExecutionResult(
        execution_id=execution_id,
        success=False,
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        failure=failure,
        latency_ms=_elapsed_ms(started),
        provider_error_code=error_code,
        retry_metadata={
            "raw_error": error,
            "gateway_routed": True,
        },
    )


def _exception_result(execution_id: str, provider_id: str, model_id: str, capability_id: str, started: float, exc: Exception) -> ProviderExecutionResult:
    failure = classify_failure(
        exception_type=type(exc).__name__,
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        raw_error=str(exc),
    )
    return ProviderExecutionResult(
        execution_id=execution_id,
        success=False,
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        failure=failure,
        latency_ms=_elapsed_ms(started),
        provider_error_code=type(exc).__name__,
    )


def _circuit_failure(
    provider_id: str,
    model_id: str,
    capability_id: str,
    store: ReliabilityStore | None,
    *,
    probe: bool,
) -> FailureSignal | None:
    if store is None:
        return None
    states = [
        store.get_circuit_state(f"{provider_id}:{model_id}") if model_id else None,
        store.get_circuit_state(f"{provider_id}:*"),
    ]
    active = next((state for state in states if state is not None), None)
    if active is None:
        return None
    if active.state in {CircuitState.OPEN, CircuitState.FORCED_OPEN}:
        return _circuit_signal(provider_id, model_id, capability_id, active.state)
    if active.state == CircuitState.HALF_OPEN and not probe:
        return _circuit_signal(provider_id, model_id, capability_id, active.state)
    return None


def _circuit_signal(provider_id: str, model_id: str, capability_id: str, state: CircuitState) -> FailureSignal:
    return FailureSignal(
        signal_id=snapshot_hash({"provider": provider_id, "model": model_id, "state": state.value, "capability": capability_id}),
        provider_id=provider_id,
        model_id=model_id,
        capability_id=capability_id,
        category=FailureCategory.POLICY_REJECTION,
        provider_attributable=True,
        retryable=False,
        circuit_relevant=False,
        explanation=f"Circuit is {state.value}; provider execution is not eligible.",
        evidence={"circuit_state": state.value},
    )


def _persist_result(
    result: ProviderExecutionResult,
    store: ReliabilityStore | None,
    workspace: Path | None,
    payload: dict[str, Any],
    *,
    attempts: tuple[RetryAttempt, ...],
    attempt_results: tuple[ProviderExecutionResult, ...] = (),
) -> None:
    if store is not None:
        if result.failure is not None:
            store.append_signal(result.failure)
        snapshot = ProviderHealthSnapshot(
            snapshot_id=snapshot_hash({"execution": result.execution_id, "provider": result.provider_id, "success": result.success}),
            provider_id=result.provider_id,
            model_id=result.model_id,
            status="ok" if result.success else "degraded",
            circuit_state=CircuitState.CLOSED,
            failure_count=0 if result.success else 1,
            success_count=1 if result.success else 0,
            sample_count=1,
            confidence=0.2,
            latency_p50_ms=result.latency_ms if result.success else None,
            latency_p95_ms=result.latency_ms if result.success else None,
        )
        store.save_health_snapshot(snapshot)
        if result.failure is not None and result.failure.circuit_relevant:
            record = CircuitStateRecord(
                record_id=snapshot_hash({"execution": result.execution_id, "state": "failure"}),
                breaker_key=f"{result.provider_id}:{result.model_id or '*'}",
                state=CircuitState.CLOSED,
                previous_state=CircuitState.CLOSED,
                transition_reason=f"failure:{result.failure.category.value}",
                failure_count=1,
            )
            store.append_circuit_event(record)
    if workspace is not None:
        _record_profile_observations(result, workspace, payload, attempt_results or (result,))
        _record_outcome(result, workspace, payload, attempts)


def _maybe_execute_fallback(
    result: ProviderExecutionResult,
    store: ReliabilityStore | None,
    workspace: Path | None,
    payload: dict[str, Any],
) -> ProviderExecutionResult | None:
    if result.success:
        return None
    candidates = payload.get("_fallback_candidates") or ()
    if not isinstance(candidates, (list, tuple)) or not candidates:
        return None
    depth = int(payload.get("_fallback_depth") or 0)
    visited = tuple(str(v) for v in payload.get("_fallback_visited") or (result.provider_id,))
    boundary = _fallback_boundary(result, payload)
    policy = FallbackExecutionPolicy(max_depth=int(payload.get("_fallback_max_depth") or boundary.max_depth))
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        candidate = _fallback_candidate(raw, result.capability_id)
        assessment = assess_fallback_safety(boundary, candidate, policy=policy, depth=depth, visited=visited)
        fallback_record = FallbackExecution(
            fallback_id=snapshot_hash({"execution": result.execution_id, "candidate": candidate.candidate_provider_id, "depth": depth, "allowed": assessment.allowed}),
            original_execution_id=result.execution_id,
            depth=depth + 1,
            strategy="equivalent_provider" if assessment.allowed else f"blocked:{assessment.reason_code}",
            provider_id=candidate.candidate_provider_id,
            model_id=candidate.candidate_model_id,
            capability_id=candidate.capability_id,
            success=False,
            lost_capabilities=() if candidate.capability_id == result.capability_id else (result.capability_id,),
            privacy_changed=bool(boundary.privacy_level and candidate.privacy_level and boundary.privacy_level != candidate.privacy_level),
            locality_changed=bool(boundary.locality and candidate.locality and boundary.locality != candidate.locality),
            cost_delta=candidate.estimated_cost,
            latency_delta_ms=candidate.estimated_latency_ms,
        )
        if store is not None:
            store.append_fallback(fallback_record)
        if not assessment.allowed:
            continue
        next_payload = dict(payload)
        next_payload["_fallback_depth"] = depth + 1
        next_payload["_fallback_visited"] = (*visited, candidate.candidate_provider_id)
        next_payload["_fallback_candidates"] = []
        if candidate.candidate_model_id:
            next_payload["model"] = candidate.candidate_model_id
        fallback_result = execute_provider(
            candidate.candidate_provider_id,
            result.capability_id,
            payload=next_payload,
            workspace_path=workspace,
            store=store,
        )
        fallback_result = ProviderExecutionResult(
            execution_id=fallback_result.execution_id,
            success=fallback_result.success,
            provider_id=fallback_result.provider_id,
            model_id=fallback_result.model_id,
            capability_id=fallback_result.capability_id,
            failure=fallback_result.failure,
            latency_ms=fallback_result.latency_ms,
            time_to_first_token_ms=fallback_result.time_to_first_token_ms,
            token_usage=fallback_result.token_usage,
            cost=fallback_result.cost,
            provider_error_code=fallback_result.provider_error_code,
            http_status=fallback_result.http_status,
            retry_metadata={**fallback_result.retry_metadata, "fallback_used": True, "fallback_from": result.execution_id},
            validation_result=fallback_result.validation_result,
            response_id=fallback_result.response_id,
            idempotency_key=fallback_result.idempotency_key,
            occurred_at=fallback_result.occurred_at,
            schema_version=fallback_result.schema_version,
        )
        if store is not None:
            store.append_fallback(FallbackExecution(
                fallback_id=snapshot_hash({"execution": result.execution_id, "candidate": candidate.candidate_provider_id, "depth": depth, "final": fallback_result.execution_id}),
                original_execution_id=result.execution_id,
                depth=depth + 1,
                strategy="equivalent_provider",
                provider_id=fallback_result.provider_id,
                model_id=fallback_result.model_id,
                capability_id=fallback_result.capability_id,
                success=fallback_result.success,
            ))
        return fallback_result
    return None


def _fallback_boundary(result: ProviderExecutionResult, payload: dict[str, Any]) -> FallbackBoundary:
    raw = dict(payload.get("_fallback_boundary") or {})
    return FallbackBoundary(
        capability_id=result.capability_id,
        modality=str(raw.get("modality") or payload.get("_modality") or ""),
        privacy_level=str(raw.get("privacy_level") or payload.get("_privacy_level") or ""),
        locality=str(raw.get("locality") or payload.get("_locality") or ""),
        output_guarantees=tuple(str(v) for v in (raw.get("output_guarantees") or payload.get("_output_guarantees") or ())),
        permissions=tuple(str(v) for v in (raw.get("permissions") or payload.get("_permissions") or ())),
        side_effects=tuple(str(v) for v in (raw.get("side_effects") or payload.get("_side_effects") or ())),
        risk_level=str(raw.get("risk_level") or payload.get("_risk_level") or ""),
        cost_budget=float(raw["cost_budget"]) if raw.get("cost_budget") is not None else None,
        latency_budget_ms=float(raw["latency_budget_ms"]) if raw.get("latency_budget_ms") is not None else None,
        max_depth=int(raw.get("max_depth") or payload.get("_fallback_max_depth") or 1),
    )


def _fallback_candidate(raw: dict[str, Any], capability_id: str) -> FallbackCompatibility:
    return FallbackCompatibility(
        candidate_provider_id=str(raw.get("provider_id") or raw.get("candidate_provider_id") or ""),
        candidate_model_id=str(raw.get("model_id") or ""),
        capability_id=str(raw.get("capability_id") or capability_id),
        modality=str(raw.get("modality") or ""),
        privacy_level=str(raw.get("privacy_level") or ""),
        locality=str(raw.get("locality") or ""),
        output_guarantees=tuple(str(v) for v in (raw.get("output_guarantees") or ())),
        permissions=tuple(str(v) for v in (raw.get("permissions") or ())),
        side_effects=tuple(str(v) for v in (raw.get("side_effects") or ())),
        risk_level=str(raw.get("risk_level") or ""),
        estimated_cost=float(raw["estimated_cost"]) if raw.get("estimated_cost") is not None else None,
        estimated_latency_ms=float(raw["estimated_latency_ms"]) if raw.get("estimated_latency_ms") is not None else None,
        profile_confidence=float(raw["profile_confidence"]) if raw.get("profile_confidence") is not None else None,
        circuit_state=str(raw.get("circuit_state") or "closed"),
        scheduler_allowed=bool(raw.get("scheduler_allowed", True)),
    )


def _record_profile_observations(
    result: ProviderExecutionResult,
    workspace: Path,
    payload: dict[str, Any],
    attempts: tuple[ProviderExecutionResult, ...],
) -> None:
    try:
        from nous_runtime.intelligence.profiles.models import PerformanceObservation
        from nous_runtime.intelligence.profiles.store import JsonlProfileStore

        store = JsonlProfileStore(workspace)
        for index, attempt in enumerate(attempts, start=1):
            provider_id = attempt.provider_id or result.provider_id
            model_id = attempt.model_id or result.model_id
            if not provider_id or not model_id:
                continue
            observation = PerformanceObservation(
                observation_id=snapshot_hash({"execution": attempt.execution_id, "attempt": index, "provider": provider_id, "model": model_id}),
                model_id=model_id,
                provider_id=provider_id,
                capability_id=attempt.capability_id,
                success=attempt.success,
                failure_category=attempt.failure.category.value if attempt.failure else "",
                latency_ms=attempt.latency_ms,
                time_to_first_token_ms=attempt.time_to_first_token_ms,
                token_usage=dict(attempt.token_usage),
                cost=attempt.cost,
                output_validated=attempt.validation_result,
                task_type=str(payload.get("_task_type") or ""),
                fallback_used=bool(attempt.retry_metadata.get("fallback_used") or payload.get("_fallback_depth")),
                retry_count=max(index - 1, 0),
                metadata={
                    "execution_id": attempt.execution_id,
                    "response_id": attempt.response_id,
                    "evidence": "provider_execution_result",
                    "provider_error_code": attempt.provider_error_code,
                    "http_status": attempt.http_status,
                },
            )
            store.append_performance_observation(observation)
    except Exception:
        return


def _record_outcome(result: ProviderExecutionResult, workspace: Path, payload: dict[str, Any], attempts: tuple[RetryAttempt, ...]) -> None:
    try:
        decision = RuntimePolicyEngine().decide(
            DecisionRequest(
                task_id=str(payload.get("_task_id") or result.execution_id),
                decision_type=DecisionType.PROVIDER,
                context=DecisionContext(
                    provider_candidates=(
                        {
                            "provider_id": result.provider_id,
                            "model": result.model_id,
                            "health": "ok" if result.success else "degraded",
                            "capabilities": [result.capability_id],
                            "required_capability": result.capability_id,
                        },
                    )
                ),
            )
        )
        service = lifecycle_for_workspace(str(workspace))
        service.record_decision_created(decision)
        record_provider_outcome(
            service,
            decision,
            execution_id=result.execution_id,
            ok=result.success,
            latency_ms=result.latency_ms,
            token_usage=result.token_usage,
            cost=result.cost,
            retry_count=max(len(attempts) - 1, 0),
            error=None if result.failure is None else _outcome_error(result),
            metadata={
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "reliability_execution_id": result.execution_id,
                "failure_category": result.failure.category.value if result.failure else "",
                "fallback_used": bool(result.retry_metadata.get("fallback_used")),
                "frozen_replay_bundle": _frozen_bundle(decision, workspace, result),
            },
        )
    except Exception:
        return


def _frozen_bundle(decision, workspace: Path, result: ProviderExecutionResult) -> dict[str, Any]:
    try:
        from nous_runtime.intelligence.profiles.store import JsonlProfileStore
        from nous_runtime.intelligence.reliability.store import JsonlReliabilityStore
        from nous_runtime.intelligence.replay import build_frozen_replay_bundle

        profiles = JsonlProfileStore(workspace)
        reliability = JsonlReliabilityStore(workspace)
        model = profiles.get_model_profile(result.model_id) if result.model_id else None
        provider = profiles.get_provider_profile(result.provider_id) if result.provider_id else None
        health = reliability.get_current_health(result.provider_id, result.model_id) if result.provider_id else None
        circuit = reliability.get_circuit_state(f"{result.provider_id}:{result.model_id}") if result.provider_id and result.model_id else None
        if circuit is None and result.provider_id:
            circuit = reliability.get_circuit_state(f"{result.provider_id}:*")
        bundle = build_frozen_replay_bundle(
            decision,
            model_profile_snapshot=model.to_dict() if model else _minimal_model_snapshot(result),
            provider_profile_snapshot=provider.to_dict() if provider else _minimal_provider_snapshot(result),
            provider_health_snapshot=health.to_dict() if health else None,
            model_health_snapshot=health.to_dict() if health else None,
            circuit_state=circuit.to_dict() if circuit else {"state": "closed", "breaker_key": f"{result.provider_id}:{result.model_id or '*'}"},
            reliability_window={"execution_id": result.execution_id, "success": result.success, "failure_category": result.failure.category.value if result.failure else ""},
            pricing_snapshot={"cost": result.cost, "known": result.cost is not None},
        )
        return bundle.to_dict()
    except Exception:
        return {"completeness": "UNREPLAYABLE", "missing_components": ["bundle_build_failed"]}


def _minimal_model_snapshot(result: ProviderExecutionResult) -> dict[str, Any]:
    return {"model_id": result.model_id, "source": "provider_execution_result", "complete_profile": False}


def _minimal_provider_snapshot(result: ProviderExecutionResult) -> dict[str, Any]:
    return {"provider_id": result.provider_id, "source": "provider_execution_result", "complete_profile": False}


def _outcome_error(result: ProviderExecutionResult):
    from nous_runtime.intelligence.models import OutcomeError

    failure = result.failure
    return OutcomeError(
        error_type=failure.category.value if failure else "unknown",
        error_code=result.provider_error_code,
        message=failure.explanation if failure else "provider execution failed",
        retryable=failure.retryable if failure else False,
    )


def _final_execution_result(
    execution_id: str,
    provider_id: str,
    model_id: str,
    capability_id: str,
    raw_result: Any,
    attempts: list[ProviderExecutionResult],
) -> ProviderExecutionResult:
    if attempts:
        last = attempts[-1]
        if last.success:
            return last
        return last
    failure = classify_failure(provider_error_code="NOUS_EXECUTION_FAILED", provider_id=provider_id, model_id=model_id, capability_id=capability_id, raw_error=str(raw_result))
    return ProviderExecutionResult(execution_id=execution_id, success=False, provider_id=provider_id, model_id=model_id, capability_id=capability_id, failure=failure)


def _provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _is_idempotent(capability_id: str, payload: dict[str, Any]) -> bool:
    """Determine whether a capability is safe to retry.

    v0.2.0: Checks (1) explicit payload override, (2) declared capability
    metadata, (3) category-based defaults, (4) legacy prefix patterns.
    """
    # 1. Explicit payload override
    if payload.get("_idempotent") is not None:
        return bool(payload.get("_idempotent"))

    # 2. Declared capability metadata (v0.2.0)
    try:
        from nous_runtime.compat.capability import get_capability
        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            meta = cap.get("metadata", {})
            if isinstance(meta, dict) and "idempotent" in meta:
                return bool(meta["idempotent"])
    except Exception:
        pass

    # 3. Category-based defaults (v0.2.0)
    category = _get_capability_category(capability_id)
    idempotent_categories = {"model", "rag", "notification", "device"}
    if category in idempotent_categories:
        # Most read operations in these categories are idempotent
        # but write operations aren't — check capability name
        if "write" in capability_id or "exec" in capability_id or "commit" in capability_id:
            return False
        return True

    # 4. v0.2.0: unknown capabilities are conservatively non-idempotent.
    #    Declare idempotent=True in capability metadata to enable retries.
    return False


def _workspace() -> Path | None:
    try:
        from nous_runtime.project.workspace import find_workspace

        workspace = find_workspace()
    except Exception:
        return None
    return Path(workspace) if workspace else None


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

