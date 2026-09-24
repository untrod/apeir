"""Provider-neutral application facade over the unified ModelGateway."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nous_runtime.model_runtime.errors import (
    ModelInvocationError,
    ModelRuntimeError,
)
from nous_runtime.model_runtime.factory import gateway_service
from nous_runtime.model_runtime.gateway import ModelGateway
from nous_runtime.model_runtime.models import (
    ModelModality,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PrivacyClass,
    RoutingMode,
)


class GatewayOperation(str, Enum):
    CHAT = "chat"
    COMPLETION = "completion"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    VISION = "vision"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    VERIFICATION = "verification"


_OPERATION_CAPABILITIES: dict[GatewayOperation, frozenset[str]] = {
    GatewayOperation.CHAT: frozenset({"chat"}),
    GatewayOperation.COMPLETION: frozenset({"completion"}),
    GatewayOperation.STRUCTURED_OUTPUT: frozenset({"structured_output"}),
    GatewayOperation.TOOL_CALLING: frozenset({"tool_calling"}),
    GatewayOperation.REASONING: frozenset({"reasoning"}),
    GatewayOperation.EMBEDDING: frozenset({"embedding"}),
    GatewayOperation.VISION: frozenset({"vision"}),
    GatewayOperation.PLANNER: frozenset({"planning"}),
    GatewayOperation.REVIEWER: frozenset({"review"}),
    GatewayOperation.VERIFICATION: frozenset({"verification"}),
}

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "private_key",
    "secret",
    "token",
}


@dataclass(frozen=True)
class GatewayBudget:
    max_cost_usd: float | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ModelRuntimeError("budget cost must be non-negative")
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ModelRuntimeError("budget tokens must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class GatewayExecutionContext:
    task_id: str
    agent_id: str = ""
    workspace_id: str = ""
    session_id: str = ""
    priority: int = 50
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.task_id).strip():
            raise ModelRuntimeError("execution task_id is required")
        if not 0 <= int(self.priority) <= 100:
            raise ModelRuntimeError(
                "execution priority must be between 0 and 100"
            )
        _reject_sensitive_data(self.metadata, "execution metadata")
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GatewayTraceContext:
    trace_id: str = ""
    span_id: str = ""
    correlation_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class GatewayFallbackPolicy:
    allowed: bool = True
    max_models: int = 3
    max_retries_per_model: int = 1

    def __post_init__(self) -> None:
        if self.max_models < 1:
            raise ModelRuntimeError(
                "fallback max_models must be positive"
            )
        if self.max_retries_per_model < 0:
            raise ModelRuntimeError(
                "fallback retries must be non-negative"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "max_models": self.max_models,
            "max_retries_per_model": self.max_retries_per_model,
        }


@dataclass(frozen=True)
class GatewayVerificationRequirements:
    required: bool = False
    strategy: str = ""
    minimum_score: float | None = None
    independent_reviewer: bool = False

    def __post_init__(self) -> None:
        if (
            self.minimum_score is not None
            and not 0 <= self.minimum_score <= 1
        ):
            raise ModelRuntimeError(
                "verification minimum_score must be between 0 and 1"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "strategy": self.strategy,
            "minimum_score": self.minimum_score,
            "independent_reviewer": self.independent_reviewer,
        }


@dataclass(frozen=True)
class GatewayRequest:
    operation: GatewayOperation
    execution: GatewayExecutionContext
    input: Any = None
    messages: tuple[Mapping[str, Any], ...] = ()
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    required_modalities: frozenset[ModelModality] = field(
        default_factory=frozenset
    )
    role: ModelRole = ModelRole.WORKER
    preferred_models: tuple[str, ...] = ()
    forbidden_models: frozenset[str] = field(default_factory=frozenset)
    routing_mode: RoutingMode = RoutingMode.AUTO
    privacy_policy: PrivacyClass = PrivacyClass.STANDARD
    timeout_s: float = 60.0
    min_context_length: int = 0
    quality_target: float = 0.5
    max_latency_ms: int | None = None
    budget: GatewayBudget = field(default_factory=GatewayBudget)
    trace: GatewayTraceContext = field(default_factory=GatewayTraceContext)
    fallback: GatewayFallbackPolicy = field(
        default_factory=GatewayFallbackPolicy
    )
    verification: GatewayVerificationRequirements = field(
        default_factory=GatewayVerificationRequirements
    )
    tools: tuple[Mapping[str, Any], ...] = ()
    response_schema: Mapping[str, Any] = field(default_factory=dict)
    attachments: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    stream: bool = False

    def __post_init__(self) -> None:
        operation = (
            self.operation
            if isinstance(self.operation, GatewayOperation)
            else GatewayOperation(str(self.operation))
        )
        object.__setattr__(self, "operation", operation)
        if not isinstance(self.execution, GatewayExecutionContext):
            raise ModelRuntimeError(
                "execution must be GatewayExecutionContext"
            )
        object.__setattr__(
            self,
            "role",
            self.role
            if isinstance(self.role, ModelRole)
            else ModelRole(str(self.role)),
        )
        object.__setattr__(
            self,
            "routing_mode",
            self.routing_mode
            if isinstance(self.routing_mode, RoutingMode)
            else RoutingMode(str(self.routing_mode)),
        )
        object.__setattr__(
            self,
            "privacy_policy",
            self.privacy_policy
            if isinstance(self.privacy_policy, PrivacyClass)
            else PrivacyClass(str(self.privacy_policy)),
        )
        modalities = frozenset(
            item
            if isinstance(item, ModelModality)
            else ModelModality(str(item))
            for item in self.required_modalities
        )
        object.__setattr__(self, "required_modalities", modalities)
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(
                str(item).strip()
                for item in self.required_capabilities
                if str(item).strip()
            ),
        )
        object.__setattr__(
            self,
            "messages",
            tuple(dict(item) for item in self.messages),
        )
        object.__setattr__(
            self,
            "tools",
            tuple(dict(item) for item in self.tools),
        )
        object.__setattr__(
            self,
            "attachments",
            tuple(dict(item) for item in self.attachments),
        )
        _reject_sensitive_data(self.metadata, "request metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "response_schema", dict(self.response_schema))

    def to_model_request(self) -> ModelRequest:
        capabilities = (
            self.required_capabilities
            or _OPERATION_CAPABILITIES[self.operation]
        )
        modalities = self.required_modalities or _default_modalities(
            self.operation
        )
        messages = self.messages
        if not messages and self.input is not None:
            messages = ({"role": "user", "content": self.input},)
        metadata = {
            **dict(self.metadata),
            "gateway_operation": self.operation.value,
            "agent_id": self.execution.agent_id,
            "workspace_id": self.execution.workspace_id,
            "session_id": self.execution.session_id,
            "priority": self.execution.priority,
            "execution_metadata": dict(self.execution.metadata),
            "trace_context": self.trace.to_dict(),
            "fallback_policy": self.fallback.to_dict(),
            "verification_requirements": self.verification.to_dict(),
            "tools": [dict(item) for item in self.tools],
            "response_schema": dict(self.response_schema),
            "max_retries_per_model": self.fallback.max_retries_per_model,
            "max_fallback_models": self.fallback.max_models,
        }
        if self.budget.max_tokens is not None:
            metadata["max_tokens"] = self.budget.max_tokens
        return ModelRequest(
            task_id=self.execution.task_id,
            required_capabilities=capabilities,
            required_modalities=modalities,
            messages=messages,
            attachments=self.attachments,
            role=self.role,
            preferred_models=self.preferred_models,
            forbidden_models=self.forbidden_models,
            routing_mode=self.routing_mode,
            privacy_policy=self.privacy_policy,
            min_context_length=self.min_context_length,
            quality_target=self.quality_target,
            max_latency_ms=self.max_latency_ms,
            max_cost_usd=self.budget.max_cost_usd,
            timeout_s=self.timeout_s,
            stream=self.stream,
            metadata=metadata,
        )


@dataclass(frozen=True)
class GatewayResponse:
    request_id: str
    content: Any = None
    structured_output: Any = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    provider_id: str = ""
    model_id: str = ""
    instance_id: str = ""
    route: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    retry_count: int = 0
    fallback_history: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    verification_metadata: Mapping[str, Any] = field(default_factory=dict)
    trace_context: Mapping[str, Any] = field(default_factory=dict)
    finish_reason: str = "completed"
    error: Mapping[str, Any] = field(default_factory=dict)
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "content": self.content,
            "structured_output": self.structured_output,
            "tool_calls": [dict(item) for item in self.tool_calls],
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "instance_id": self.instance_id,
            "route": dict(self.route),
            "usage": dict(self.usage),
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "fallback_history": list(self.fallback_history),
            "warnings": list(self.warnings),
            "verification_metadata": dict(self.verification_metadata),
            "trace_context": dict(self.trace_context),
            "finish_reason": self.finish_reason,
            "error": dict(self.error),
            "raw_metadata": dict(self.raw_metadata),
        }


class ModelGatewayFacade:
    """Stable business boundary; provider response shapes stop here."""

    def __init__(self, gateway: ModelGateway) -> None:
        if not isinstance(gateway, ModelGateway):
            raise ModelRuntimeError("gateway must be a ModelGateway")
        self.gateway = gateway

    async def invoke(self, request: GatewayRequest) -> GatewayResponse:
        model_request = self._prepare(request)
        response = await self.gateway.invoke(model_request)
        return self._normalize(request, response)

    def invoke_sync(self, request: GatewayRequest) -> GatewayResponse:
        model_request = self._prepare(request)
        response = self.gateway.invoke_sync(model_request)
        return self._normalize(request, response)

    async def try_invoke(self, request: GatewayRequest) -> GatewayResponse:
        try:
            return await self.invoke(request)
        except ModelRuntimeError as exc:
            return _error_response(request, exc)

    def try_invoke_sync(self, request: GatewayRequest) -> GatewayResponse:
        try:
            return self.invoke_sync(request)
        except ModelRuntimeError as exc:
            return _error_response(request, exc)

    async def stream(
        self,
        request: GatewayRequest,
    ) -> AsyncIterator[Any]:
        model_request = self._prepare(request, stream=True)
        async for item in self.gateway.stream(model_request):
            yield item

    async def cancel(self, request_id: str) -> bool:
        return await self.gateway.cancel(request_id)

    def _prepare(
        self,
        request: GatewayRequest,
        *,
        stream: bool | None = None,
    ) -> ModelRequest:
        if not isinstance(request, GatewayRequest):
            raise ModelInvocationError(
                "request must be a GatewayRequest"
            )
        model_request = request.to_model_request()
        if stream is not None and model_request.stream is not stream:
            payload = model_request.to_dict()
            payload["stream"] = stream
            model_request = ModelRequest.from_dict(payload)
        if request.fallback.allowed:
            return model_request
        if model_request.routing_mode is RoutingMode.LOCKED:
            return model_request
        decision = self.gateway.router.route(model_request)
        payload = model_request.to_dict()
        payload["preferred_models"] = [decision.selected_model_id]
        payload["routing_mode"] = RoutingMode.LOCKED.value
        return ModelRequest.from_dict(payload)

    def _normalize(
        self,
        request: GatewayRequest,
        response: ModelResponse,
    ) -> GatewayResponse:
        events = tuple(
            event
            for event in self.gateway.events
            if event.metadata.get("request_id") == response.request_id
        )
        route = next(
            (
                dict(event.payload.get("decision") or {})
                for event in events
                if event.event_type == "model.route.selected"
            ),
            {},
        )
        failures = tuple(
            event
            for event in events
            if event.event_type == "model.invoke.failed"
        )
        fallback_history = tuple(
            str(event.payload.get("model_id") or "")
            for event in failures
            if event.payload.get("model_id")
        )
        record = self.gateway.registry.require(response.model_id)
        content, structured_output, tool_calls = _content_parts(
            response.content,
            request.response_schema,
        )
        warnings = tuple(
            str(item)
            for item in response.metadata.get("warnings", ())
        )
        verification = dict(
            response.metadata.get("verification") or {}
        )
        return GatewayResponse(
            request_id=response.request_id,
            content=content,
            structured_output=structured_output,
            tool_calls=tool_calls,
            provider_id=record.descriptor.provider_id,
            model_id=response.model_id,
            instance_id=response.instance_id,
            route=route,
            usage=response.usage,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            retry_count=len(failures),
            fallback_history=fallback_history,
            warnings=warnings,
            verification_metadata=verification,
            trace_context=request.trace.to_dict(),
            finish_reason=response.finish_reason,
            raw_metadata=response.metadata,
        )


def get_gateway_facade(
    *,
    required: bool = True,
) -> ModelGatewayFacade | None:
    gateway = gateway_service.get(required=required)
    return ModelGatewayFacade(gateway) if gateway is not None else None


def _default_modalities(
    operation: GatewayOperation,
) -> frozenset[ModelModality]:
    if operation is GatewayOperation.EMBEDDING:
        return frozenset({ModelModality.EMBEDDING})
    if operation is GatewayOperation.VISION:
        return frozenset({ModelModality.TEXT, ModelModality.IMAGE})
    return frozenset({ModelModality.TEXT})


def _content_parts(
    raw: Any,
    response_schema: Mapping[str, Any],
) -> tuple[Any, Any, tuple[Mapping[str, Any], ...]]:
    if not isinstance(raw, Mapping):
        return raw, _decode_structured(raw) if response_schema else None, ()
    tool_calls = tuple(
        dict(item) for item in raw.get("tool_calls") or ()
    )
    structured = raw.get("structured_output")
    if structured is None and response_schema:
        structured = raw.get("content", raw)
    content = raw.get("content", raw.get("text", raw))
    return content, structured, tool_calls


def _decode_structured(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    candidate = raw.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return raw


def _error_response(
    request: GatewayRequest,
    error: ModelRuntimeError,
) -> GatewayResponse:
    return GatewayResponse(
        request_id="",
        warnings=("model invocation failed",),
        trace_context=request.trace.to_dict(),
        error={
            "type": type(error).__name__,
            "message": str(error),
            "provider_error_code": str(
                getattr(error, "provider_error_code", "") or ""
            ),
            "http_status": getattr(error, "http_status", None),
            "retryable": getattr(error, "retryable", None),
        },
    )


def _reject_sensitive_data(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or any(
                marker in normalized
                for marker in ("api_key", "password", "secret", "token")
            ):
                raise ModelRuntimeError(
                    f"{path} must use a credential reference, not {key}"
                )
            _reject_sensitive_data(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_data(item, f"{path}[{index}]")


__all__ = [
    "GatewayBudget",
    "GatewayExecutionContext",
    "GatewayFallbackPolicy",
    "GatewayOperation",
    "GatewayRequest",
    "GatewayResponse",
    "GatewayTraceContext",
    "GatewayVerificationRequirements",
    "ModelGatewayFacade",
    "get_gateway_facade",
]
