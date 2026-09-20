"""Measured compatibility bridge for legacy Provider execution paths."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Mapping
from typing import Any

from nous_runtime.core.events import EventEnvelope
from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayFallbackPolicy,
    GatewayOperation,
    GatewayRequest,
    GatewayTraceContext,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.factory import gateway_service
from nous_runtime.model_runtime.models import RoutingMode
from nous_runtime.governance.runtime_mode import mode_policy


_events: deque[EventEnvelope] = deque(maxlen=1000)
_lock = threading.RLock()
_metrics = {
    "gateway_invocations": 0,
    "direct_fallbacks": 0,
    "gateway_failures": 0,
}

def _legacy_gateway_direct_allowed() -> bool:
    """Allow adapter-backed direct execution only in compatibility modes."""
    return mode_policy(surface="local_cli").compatibility_bypass_allowed


_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)


def try_invoke_legacy_provider(
    provider_id: str,
    capability_id: str,
    payload: Mapping[str, Any],
    *,
    execution_id: str,
    allow_direct_fallback: bool = True,
) -> dict[str, Any] | None:
    """Use Gateway when available; return None for measured direct fallback."""
    gateway = gateway_service.get(required=False)
    if not allow_direct_fallback:
        try:
            from nous_runtime.compat.provider import get_provider

            # Legacy Provider registrations are mutable, so refresh gateways
            # composed from that registry. Preserve an explicitly configured
            # gateway when the provider is not part of the global registry.
            if get_provider(provider_id) is not None or gateway is None:
                gateway = gateway_service.configure_from_providers(
                    allow_direct=_legacy_gateway_direct_allowed()
                )
        except Exception as exc:
            return _gateway_unavailable_result(exc)
    if gateway is None:
        _record_fallback(
            provider_id,
            capability_id,
            execution_id,
            "gateway_not_configured",
        )
        return None
    model_id = _resolve_model_id(
        gateway,
        provider_id,
        str(payload.get("model") or ""),
    )
    if not model_id and not allow_direct_fallback:
        # Provider registrations are dynamic in legacy integrations and tests.
        # Refresh the Gateway composition rather than calling Provider.invoke
        # outside its protocol adapter.
        try:
            gateway = gateway_service.configure_from_providers(
                    allow_direct=_legacy_gateway_direct_allowed()
                )
            model_id = _resolve_model_id(
                gateway,
                provider_id,
                str(payload.get("model") or ""),
            )
        except Exception as exc:
            return _gateway_unavailable_result(exc)
    if not model_id:
        if not allow_direct_fallback:
            return {
                "ok": False,
                "error": (
                    f"provider {provider_id} is not registered in "
                    "the unified model gateway"
                ),
                "error_code": "NOUS_PROVIDER_NOT_FOUND",
                "_provider_error_code": "NOUS_PROVIDER_NOT_FOUND",
            }
        _record_fallback(
            provider_id,
            capability_id,
            execution_id,
            "provider_not_registered_in_gateway",
        )
        return None
    facade = ModelGatewayFacade(gateway)
    operation = _operation(capability_id)
    normalized_capability = capability_id.removeprefix("model.")
    messages = tuple(payload.get("messages") or ())
    input_value = (
        payload.get("input")
        if payload.get("input") is not None
        else payload.get("prompt")
    )
    response = facade.try_invoke_sync(
        GatewayRequest(
            operation=operation,
            execution=GatewayExecutionContext(
                task_id=str(payload.get("task_id") or execution_id),
                agent_id=str(payload.get("agent_id") or ""),
                workspace_id=str(payload.get("workspace_id") or ""),
                session_id=str(payload.get("session_id") or ""),
                priority=int(payload.get("priority") or 50),
            ),
            input=input_value,
            messages=messages,
            attachments=tuple(payload.get("attachments") or ()),
            required_capabilities=frozenset({normalized_capability}),
            preferred_models=(model_id,),
            routing_mode=RoutingMode.LOCKED,
            fallback=GatewayFallbackPolicy(
                allowed=False,
                max_models=1,
                max_retries_per_model=0,
            ),
            trace=GatewayTraceContext(
                trace_id=str(payload.get("trace_id") or execution_id),
                correlation_id=execution_id,
            ),
            metadata={"legacy_params": _safe_metadata(payload)},
        )
    )
    if not response.ok:
        _increment("gateway_failures")
        return {
            "ok": False,
            "error": str(
                response.error.get("message") or "gateway invocation failed"
            ),
            "error_code": str(
                response.error.get("type") or "ModelInvocationError"
            ),
            "_provider_error_code": str(
                response.error.get("type") or "ModelInvocationError"
            ),
        }
    _increment("gateway_invocations")
    if isinstance(response.content, Mapping):
        legacy = dict(response.content)
        if "ok" in legacy:
            # Preserve the historical capability result exactly. Gateway
            # routing, retry and trace data remain in canonical events/metrics.
            return legacy
    return {
        "ok": True,
        "result": response.content,
        "content": response.content,
        "model": str(
            response.raw_metadata.get("provider_model")
            or response.model_id
        ),
        "token_usage": dict(response.usage),
        "cost": response.cost_usd,
        "latency_ms": response.latency_ms,
        "response_id": response.request_id,
        "validation_result": response.verification_metadata.get(
            "accepted"
        ),
        "_gateway": {
            "provider_id": response.provider_id,
            "route": dict(response.route),
            "retry_count": response.retry_count,
            "fallback_history": list(response.fallback_history),
        },
    }


def invoke_provider_via_gateway(
    provider_id: str,
    capability_id: str,
    payload: Mapping[str, Any],
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Invoke an existing Provider exclusively through ModelGatewayFacade."""
    result = try_invoke_legacy_provider(
        provider_id,
        capability_id,
        payload,
        execution_id=execution_id,
        allow_direct_fallback=False,
    )
    if result is None:
        return {
            "ok": False,
            "error": "unified model gateway is unavailable",
            "error_code": "ModelRuntimeError",
            "_provider_error_code": "ModelRuntimeError",
        }
    return result


def compatibility_events() -> tuple[EventEnvelope, ...]:
    with _lock:
        return tuple(_events)


def compatibility_metrics() -> dict[str, int]:
    with _lock:
        return dict(_metrics)


def reset_compatibility_observability() -> None:
    with _lock:
        _events.clear()
        for key in _metrics:
            _metrics[key] = 0


def _resolve_model_id(
    gateway: Any,
    provider_id: str,
    requested_model: str,
) -> str:
    candidates = [
        record
        for record in gateway.registry.list()
        if record.descriptor.provider_id == provider_id
    ]
    if requested_model:
        requested = requested_model.casefold()
        exact = next(
            (
                record
                for record in candidates
                if record.descriptor.model_id.casefold() == requested
                or record.descriptor.model_id.casefold().endswith(
                    f"/{requested}"
                )
            ),
            None,
        )
        if exact is not None:
            return exact.descriptor.model_id
    enabled = next(
        (
            record
            for record in candidates
            if record.enabled
        ),
        None,
    )
    return enabled.descriptor.model_id if enabled is not None else ""


def _operation(capability_id: str) -> GatewayOperation:
    normalized = capability_id.casefold()
    if "embed" in normalized:
        return GatewayOperation.EMBEDDING
    if "vision" in normalized or "ocr" in normalized:
        return GatewayOperation.VISION
    if "plan" in normalized:
        return GatewayOperation.PLANNER
    if "review" in normalized:
        return GatewayOperation.REVIEWER
    if "verif" in normalized:
        return GatewayOperation.VERIFICATION
    if "tool" in normalized:
        return GatewayOperation.TOOL_CALLING
    if "chat" in normalized:
        return GatewayOperation.CHAT
    return GatewayOperation.REASONING


def _safe_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {
        "agent_id",
        "attachments",
        "input",
        "messages",
        "model",
        "priority",
        "prompt",
        "session_id",
        "task_id",
        "trace_id",
        "workspace_id",
    }
    return {
        str(key): value
        for key, value in payload.items()
        if str(key) not in excluded
        and not any(
            marker in str(key).casefold()
            for marker in _SENSITIVE_MARKERS
        )
    }


def _record_fallback(
    provider_id: str,
    capability_id: str,
    execution_id: str,
    reason: str,
) -> None:
    event = EventEnvelope(
        event_type="model.compatibility.deprecated",
        source="legacy_provider_compatibility",
        payload={
            "provider_id": provider_id,
            "capability_id": capability_id,
            "reason": reason,
            "replacement": "ModelGatewayFacade",
        },
        metadata={"execution_id": execution_id},
    )
    with _lock:
        _events.append(event)
        _metrics["direct_fallbacks"] += 1


def _gateway_unavailable_result(exc: Exception) -> dict[str, Any]:
    _increment("gateway_failures")
    return {
        "ok": False,
        "error": f"unified model gateway unavailable: {exc}",
        "error_code": type(exc).__name__,
        "_provider_error_code": type(exc).__name__,
    }


def _increment(name: str) -> None:
    with _lock:
        _metrics[name] += 1


__all__ = [
    "compatibility_events",
    "compatibility_metrics",
    "invoke_provider_via_gateway",
    "reset_compatibility_observability",
    "try_invoke_legacy_provider",
]
