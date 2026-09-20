"""Remote Terminal compatibility surface backed only by ModelGatewayFacade."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from nous_runtime.model_runtime.facade import (
    GatewayBudget,
    GatewayExecutionContext,
    GatewayFallbackPolicy,
    GatewayOperation,
    GatewayRequest,
    GatewayResponse,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import RoutingMode
from nous_runtime.provider.adapters.anthropic import AnthropicProvider
from nous_runtime.provider.adapters.openai import OpenAIProvider


_CREDENTIAL_ENV = "NOUS_REMOTE_TERMINAL_GATEWAY_KEY"
_lock = threading.RLock()
_cache: dict[tuple[str, str, str], tuple[ModelGatewayFacade, str]] = {}


@dataclass(frozen=True)
class RemoteModelResult:
    message: Mapping[str, Any]
    usage: Mapping[str, Any]
    model_id: str
    provider_id: str
    latency_ms: int
    structured_output: Mapping[str, Any] | None = None


def invoke_message(
    messages: Sequence[Mapping[str, Any]],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    timeout_s: float,
    tools: Sequence[Mapping[str, Any]] = (),
    vision: bool = False,
    max_tokens: int | None = None,
    structured: bool = False,
    response_schema: Mapping[str, Any] | None = None,
) -> RemoteModelResult:
    facade, model_id = _facade_for(endpoint, api_key, model)
    operation = (
        GatewayOperation.VISION
        if vision
        else (
            GatewayOperation.TOOL_CALLING
            if tools
            else (
                GatewayOperation.STRUCTURED_OUTPUT
                if structured or response_schema
                else GatewayOperation.CHAT
            )
        )
    )
    response = facade.try_invoke_sync(
        GatewayRequest(
            operation=operation,
            execution=GatewayExecutionContext(
                task_id="remote-terminal",
                agent_id="remote-terminal.brain",
            ),
            messages=tuple(messages),
            preferred_models=(model_id,),
            routing_mode=RoutingMode.LOCKED,
            timeout_s=max(0.001, float(timeout_s)),
            budget=GatewayBudget(max_tokens=max_tokens),
            fallback=GatewayFallbackPolicy(
                allowed=False,
                max_models=1,
                max_retries_per_model=2,
            ),
            tools=tuple(tools),
            response_schema=dict(response_schema or {}),
            metadata={"source": "remote_terminal"},
        )
    )
    _raise_for_error(response)
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
    }
    if response.tool_calls:
        message["tool_calls"] = [
            dict(item) for item in response.tool_calls
        ]
    return RemoteModelResult(
        message=message,
        usage=dict(response.usage),
        model_id=response.model_id,
        provider_id=response.provider_id,
        latency_ms=response.latency_ms,
        structured_output=(
            dict(response.structured_output)
            if isinstance(response.structured_output, Mapping)
            else None
        ),
    )


def invoke_embeddings(
    texts: Sequence[str],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    timeout_s: float = 30.0,
) -> list[list[float]]:
    facade, model_id = _facade_for(endpoint, api_key, model)
    response = facade.try_invoke_sync(
        GatewayRequest(
            operation=GatewayOperation.EMBEDDING,
            execution=GatewayExecutionContext(
                task_id="remote-terminal-embedding",
                agent_id="remote-terminal.embedding",
            ),
            input=list(texts),
            preferred_models=(model_id,),
            routing_mode=RoutingMode.LOCKED,
            timeout_s=max(0.001, float(timeout_s)),
            fallback=GatewayFallbackPolicy(
                allowed=False,
                max_models=1,
                max_retries_per_model=2,
            ),
            metadata={"source": "remote_terminal"},
        )
    )
    _raise_for_error(response)
    content = response.content
    if isinstance(content, Mapping):
        vectors = content.get("embeddings")
        if vectors is None and content.get("embedding") is not None:
            vectors = [content["embedding"]]
    else:
        vectors = content
    if not isinstance(vectors, (list, tuple)):
        raise RuntimeError("Gateway embedding response has no vectors")
    return [
        [float(value) for value in vector]
        for vector in vectors
    ]


def reset_bridge() -> None:
    with _lock:
        entries = tuple(_cache.values())
        _cache.clear()
    for facade, _ in entries:
        facade.gateway.close_sync_bridge()


def _facade_for(
    endpoint: str,
    api_key: str,
    model: str,
) -> tuple[ModelGatewayFacade, str]:
    normalized_endpoint = str(endpoint or "").strip()
    normalized_model = str(model or "").strip()
    if not normalized_endpoint or not normalized_model:
        raise RuntimeError("model endpoint and model are required")
    protocol = (
        "anthropic"
        if "anthropic" in normalized_endpoint.casefold()
        or normalized_endpoint.rstrip("/").endswith("/messages")
        else "openai"
    )
    cache_key = (protocol, normalized_endpoint, normalized_model)
    with _lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            if api_key:
                os.environ[_CREDENTIAL_ENV] = api_key
            return cached
        if api_key:
            os.environ[_CREDENTIAL_ENV] = api_key
        credential_ref = f"env:{_CREDENTIAL_ENV}" if api_key else ""
        provider_id = f"remote-terminal-{protocol}"
        if protocol == "anthropic":
            provider = AnthropicProvider(
                provider_id=provider_id,
                provider_name="Remote Terminal Anthropic",
                endpoint=normalized_endpoint,
                model=normalized_model,
                credential_ref=credential_ref,
                capabilities=(
                    "model.chat",
                    "model.completion",
                    "model.structured_output",
                    "model.tool_calling",
                    "model.reason",
                    "model.code",
                    "model.vision",
                ),
            )
        else:
            provider = OpenAIProvider(
                provider_id=provider_id,
                provider_name="Remote Terminal OpenAI Compatible",
                endpoint=normalized_endpoint,
                model=normalized_model,
                credential_ref=credential_ref,
                capabilities=(
                    "model.chat",
                    "model.completion",
                    "model.structured_output",
                    "model.tool_calling",
                    "model.reason",
                    "model.code",
                    "model.embed",
                    "model.vision",
                ),
            )
        gateway = build_gateway_from_providers([provider])
        facade = ModelGatewayFacade(gateway)
        model_id = gateway.registry.list()[0].descriptor.model_id
        value = (facade, model_id)
        _cache[cache_key] = value
        return value


def _raise_for_error(response: GatewayResponse) -> None:
    if response.ok:
        return
    error_type = str(response.error.get("type") or "ModelRuntimeError")
    message = str(
        response.error.get("message") or "model invocation failed"
    )
    raise RuntimeError(f"{error_type}: {message}")


__all__ = [
    "RemoteModelResult",
    "invoke_embeddings",
    "invoke_message",
    "reset_bridge",
]
