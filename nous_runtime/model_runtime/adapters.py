"""Backend adapter protocol and first-party compatibility adapters."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from nous_runtime.model_runtime.errors import (
    ModelAdapterError,
    ModelProviderResponseError,
)
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelInstance,
    ModelRequest,
    ModelResponse,
)


@dataclass(frozen=True)
class AdapterProbe:
    backend_id: str
    healthy: bool
    latency_ms: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ModelBackendAdapter(Protocol):
    backend_id: str

    async def probe(self) -> AdapterProbe: ...

    async def list_models(self) -> list[Mapping[str, Any]]: ...

    async def invoke(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> ModelResponse: ...

    def stream(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> AsyncIterator[Any]: ...

    async def cancel(self, request_id: str) -> None: ...


class ModelAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModelBackendAdapter] = {}

    def register(
        self,
        adapter: ModelBackendAdapter,
        *,
        replace_existing: bool = False,
    ) -> ModelBackendAdapter:
        backend_id = str(getattr(adapter, "backend_id", "") or "").strip()
        if not backend_id:
            raise ModelAdapterError("adapter backend_id is required")
        if not isinstance(adapter, ModelBackendAdapter):
            raise ModelAdapterError(
                "adapter does not implement ModelBackendAdapter"
            )
        if backend_id in self._adapters and not replace_existing:
            raise ModelAdapterError(
                f"adapter already registered: {backend_id}"
            )
        self._adapters[backend_id] = adapter
        return adapter

    def get(self, backend_id: str) -> ModelBackendAdapter | None:
        return self._adapters.get(str(backend_id))

    def require(self, backend_id: str) -> ModelBackendAdapter:
        adapter = self.get(backend_id)
        if adapter is None:
            raise ModelAdapterError(
                f"model backend adapter not found: {backend_id}"
            )
        return adapter

    def list(self) -> tuple[ModelBackendAdapter, ...]:
        return tuple(
            self._adapters[key] for key in sorted(self._adapters)
        )


class MockModelAdapter:
    """Deterministic adapter for tests, demos and offline diagnostics."""

    backend_id = "mock"

    def __init__(
        self,
        *,
        content: Any = "mock response",
        delay_s: float = 0.0,
        failures_before_success: int = 0,
        cost_usd: float = 0.0,
        total_tokens: int = 0,
    ) -> None:
        self.content = content
        self.delay_s = delay_s
        self.failures_before_success = failures_before_success
        self.cost_usd = cost_usd
        self.total_tokens = total_tokens
        self.invocations: list[str] = []
        self.cancelled: set[str] = set()

    async def probe(self) -> AdapterProbe:
        return AdapterProbe(self.backend_id, True, details={"mock": True})

    async def list_models(self) -> list[Mapping[str, Any]]:
        return [{"model_id": "mock", "backend": self.backend_id}]

    async def invoke(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> ModelResponse:
        started = time.perf_counter()
        self.invocations.append(request.request_id)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if len(self.invocations) <= self.failures_before_success:
            raise ModelAdapterError("injected mock adapter failure")
        return ModelResponse(
            request_id=request.request_id,
            model_id=descriptor.model_id,
            instance_id=instance.instance_id,
            content=self.content,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage={
                "input_messages": len(request.messages),
                "total_tokens": self.total_tokens,
            },
            cost_usd=self.cost_usd,
            metadata={"backend": self.backend_id},
        )

    async def stream(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> AsyncIterator[Any]:
        response = await self.invoke(request, descriptor, instance)
        value = response.content
        if isinstance(value, str):
            for token in value.split():
                yield token
        else:
            yield value

    async def cancel(self, request_id: str) -> None:
        self.cancelled.add(request_id)

    async def load(self, instance: ModelInstance) -> None:
        return None

    async def unload(self, instance: ModelInstance) -> None:
        return None


class LegacyProviderAdapter:
    """Expose an existing Nous Provider through the new async boundary."""

    def __init__(
        self,
        provider: Any,
        *,
        backend_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.backend_id = str(
            backend_id
            or getattr(provider, "provider_id", "")
            or "legacy-provider"
        )

    async def probe(self) -> AdapterProbe:
        started = time.perf_counter()
        try:
            health = await asyncio.to_thread(self.provider.health)
        except Exception as exc:
            return AdapterProbe(
                self.backend_id,
                False,
                int((time.perf_counter() - started) * 1000),
                {"error": str(exc)},
            )
        return AdapterProbe(
            self.backend_id,
            str(health.get("status") or "").lower()
            in {"ok", "healthy", "ready"},
            int((time.perf_counter() - started) * 1000),
            dict(health),
        )

    async def list_models(self) -> list[Mapping[str, Any]]:
        model = str(getattr(self.provider, "model", "") or "")
        return [{"model_id": model}] if model else []

    async def invoke(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> ModelResponse:
        started = time.perf_counter()
        capability = self._legacy_capability(request)
        legacy_params = dict(
            request.metadata.get("legacy_params") or {}
        )
        if capability.startswith("model."):
            provider_model = str(
                descriptor.metadata.get("provider_model")
                or getattr(self.provider, "model", "")
                or descriptor.model_id
            )
            params = {
                "model": provider_model,
                "messages": list(request.messages),
                "attachments": list(request.attachments),
                "request_id": request.request_id,
                "tools": list(request.metadata.get("tools") or ()),
                "tool_choice": request.metadata.get("tool_choice"),
                "response_schema": dict(
                    request.metadata.get("response_schema") or {}
                ),
                "max_tokens": int(
                    request.metadata.get("max_tokens") or 4096
                ),
                "workspace": str(
                    request.metadata.get("workspace_path") or ""
                ),
                "agent_mode": str(
                    request.metadata.get("agent_mode") or "agent"
                ),
                **legacy_params,
            }
        else:
            # Non-model legacy capabilities still traverse Gateway, but retain
            # their established parameter contract at the protocol boundary.
            params = legacy_params
        if capability == "model.embed" and request.messages:
            content = request.messages[0].get("content")
            params["input"] = content
            params["text"] = content
        if capability == "model.vision" and request.attachments:
            first = request.attachments[0]
            params["image_url"] = (
                first.get("url") or first.get("image_url") or ""
            )
        try:
            payload = await asyncio.to_thread(
                self.provider.invoke,
                capability,
                **params,
            )
        except Exception as exc:
            raise ModelAdapterError(
                f"legacy provider invocation failed: {exc}"
            ) from exc
        if not isinstance(payload, Mapping) or not payload.get("ok", False):
            message = (
                str(payload.get("error") or "provider invocation failed")
                if isinstance(payload, Mapping)
                else "provider returned an invalid response"
            )
            raise ModelProviderResponseError(
                message,
                provider_error_code=(
                    str(payload.get("error_code") or "")
                    if isinstance(payload, Mapping)
                    else ""
                ),
                http_status=(
                    int(payload["http_status"])
                    if isinstance(payload, Mapping)
                    and payload.get("http_status") is not None
                    else None
                ),
                retryable=(
                    bool(payload["retryable"])
                    if isinstance(payload, Mapping)
                    and payload.get("retryable") is not None
                    else None
                ),
            )
        content = payload.get("content", payload.get("result"))
        if (
            content is None
            and "content" not in payload
            and "result" not in payload
        ):
            content = dict(payload)
        if payload.get("tool_calls"):
            content = {
                "content": content,
                "tool_calls": list(payload["tool_calls"]),
            }
        elif payload.get("embeddings") is not None:
            content = {"embeddings": list(payload["embeddings"])}
        elif payload.get("embedding") is not None:
            content = {
                "embedding": list(payload["embedding"]),
                "embeddings": [list(payload["embedding"])],
            }
        return ModelResponse(
            request_id=request.request_id,
            model_id=descriptor.model_id,
            instance_id=instance.instance_id,
            content=content,
            usage=dict(payload.get("usage") or {}),
            cost_usd=float(payload.get("cost_usd") or 0.0),
            latency_ms=int(
                payload.get("latency_ms")
                or (time.perf_counter() - started) * 1000
            ),
            finish_reason=str(
                payload.get("finish_reason") or "completed"
            ),
            metadata={
                "backend": self.backend_id,
                "legacy_provider": True,
                "provider_model": str(
                    payload.get("model") or descriptor.model_id
                ),
            },
        )

    async def stream(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> AsyncIterator[Any]:
        response = await self.invoke(request, descriptor, instance)
        yield response.content

    async def cancel(self, request_id: str) -> None:
        cancel = getattr(self.provider, "cancel", None)
        if callable(cancel):
            result = cancel(request_id)
            if inspect.isawaitable(result):
                await result

    @staticmethod
    def _legacy_capability(request: ModelRequest) -> str:
        if not request.required_capabilities:
            return "model.reason"
        capability = sorted(request.required_capabilities)[0]
        if capability.startswith("model."):
            return capability
        aliases = {
            "audio": "model.transcribe",
            "chat": "model.reason",
            "code": "model.code",
            "coding": "model.code",
            "completion": "model.reason",
            "embed": "model.embed",
            "embedding": "model.embed",
            "planning": "model.reason",
            "reason": "model.reason",
            "reasoning": "model.reason",
            "rerank": "model.rerank",
            "review": "model.reason",
            "structured": "model.structured",
            "structured_output": "model.structured",
            "tool": "model.tool",
            "tool_calling": "model.tool",
            "verification": "model.reason",
            "vision": "model.vision",
        }
        return aliases.get(capability, capability)


class OpenAICompatibleAdapter(LegacyProviderAdapter):
    """OpenAI-compatible HTTP backend using the existing Provider client."""

    def __init__(
        self,
        *,
        backend_id: str = "openai-compatible",
        endpoint: str,
        model: str,
        credential_ref: str = "",
    ) -> None:
        from nous_runtime.provider.adapters.openai import OpenAIProvider

        super().__init__(
            OpenAIProvider(
                provider_id=backend_id,
                provider_name=backend_id,
                endpoint=endpoint,
                model=model,
                credential_ref=credential_ref,
                capabilities=(
                    "model.reason",
                    "model.code",
                    "model.embed",
                    "model.vision",
                    "model.rerank",
                ),
            ),
            backend_id=backend_id,
        )


class OllamaAdapter(OpenAICompatibleAdapter):
    def __init__(
        self,
        *,
        model: str,
        endpoint: str = "http://127.0.0.1:11434/v1/chat/completions",
    ) -> None:
        super().__init__(
            backend_id="ollama",
            endpoint=endpoint,
            model=model,
        )


class LlamaCppServerAdapter(OpenAICompatibleAdapter):
    def __init__(
        self,
        *,
        model: str,
        endpoint: str = "http://127.0.0.1:8080/v1/chat/completions",
    ) -> None:
        super().__init__(
            backend_id="llama.cpp",
            endpoint=endpoint,
            model=model,
        )


class VLLMAdapter(OpenAICompatibleAdapter):
    def __init__(
        self,
        *,
        model: str,
        endpoint: str,
        credential_ref: str = "",
    ) -> None:
        super().__init__(
            backend_id="vllm",
            endpoint=endpoint,
            model=model,
            credential_ref=credential_ref,
        )


LocalHandler = Callable[
    [ModelRequest, ModelDescriptor, ModelInstance],
    ModelResponse | Awaitable[ModelResponse],
]


class LocalImportedModelAdapter:
    """Safe boundary for a user-imported model supplied by the host."""

    backend_id = "local-imported"

    def __init__(
        self,
        handler: LocalHandler,
        *,
        model_ids: tuple[str, ...] = (),
    ) -> None:
        self.handler = handler
        self.model_ids = model_ids

    async def probe(self) -> AdapterProbe:
        return AdapterProbe(
            self.backend_id,
            callable(self.handler),
            details={"model_count": len(self.model_ids)},
        )

    async def list_models(self) -> list[Mapping[str, Any]]:
        return [{"model_id": item} for item in self.model_ids]

    async def invoke(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> ModelResponse:
        try:
            result = self.handler(request, descriptor, instance)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise ModelAdapterError(
                f"local imported model failed: {exc}"
            ) from exc
        if not isinstance(result, ModelResponse):
            raise ModelAdapterError(
                "local imported handler must return ModelResponse"
            )
        return result

    async def stream(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> AsyncIterator[Any]:
        response = await self.invoke(request, descriptor, instance)
        yield response.content

    async def cancel(self, request_id: str) -> None:
        return None


__all__ = [
    "AdapterProbe",
    "LegacyProviderAdapter",
    "LlamaCppServerAdapter",
    "LocalImportedModelAdapter",
    "MockModelAdapter",
    "ModelAdapterRegistry",
    "ModelBackendAdapter",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "VLLMAdapter",
]
