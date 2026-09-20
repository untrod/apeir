"""Compatibility bridges for Task, Agent and role-based model requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from nous_runtime.model_runtime.gateway import ModelGateway
from nous_runtime.model_runtime.models import (
    ModelModality,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PrivacyClass,
    RoutingMode,
)


@dataclass(frozen=True)
class ModelRoleBinding:
    role: ModelRole
    preferred_models: tuple[str, ...] = ()
    required_capabilities: frozenset[str] = frozenset()
    required_modalities: frozenset[ModelModality] = frozenset()


class ModelRoleBindings:
    """Preferences remain subordinate to gateway hard constraints."""

    def __init__(self) -> None:
        self._bindings: dict[ModelRole, ModelRoleBinding] = {}

    def bind(self, binding: ModelRoleBinding) -> ModelRoleBinding:
        self._bindings[binding.role] = binding
        return binding

    def get(self, role: ModelRole | str) -> ModelRoleBinding | None:
        normalized = role if isinstance(role, ModelRole) else ModelRole(role)
        return self._bindings.get(normalized)

    def apply(self, request: ModelRequest) -> ModelRequest:
        binding = self.get(request.role)
        if binding is None:
            return request
        payload = request.to_dict()
        payload["preferred_models"] = list(
            dict.fromkeys(
                (*request.preferred_models, *binding.preferred_models)
            )
        )
        payload["required_capabilities"] = sorted(
            request.required_capabilities
            | binding.required_capabilities
        )
        payload["required_modalities"] = sorted(
            item.value
            for item in (
                request.required_modalities
                | binding.required_modalities
            )
        )
        if (
            payload["preferred_models"]
            and request.routing_mode is RoutingMode.AUTO
        ):
            payload["routing_mode"] = RoutingMode.PREFERRED.value
        return ModelRequest.from_dict(payload)


def model_request_from_task(
    task: Any,
    *,
    messages: Iterable[Mapping[str, Any]] = (),
    role: ModelRole | str = ModelRole.WORKER,
) -> ModelRequest:
    """Read model requirements from Task metadata without changing Task."""
    metadata = dict(getattr(task, "metadata", {}) or {})
    task_id = str(getattr(task, "id", "") or metadata.get("task_id") or "")
    return ModelRequest(
        task_id=task_id,
        required_capabilities=frozenset(
            metadata.get("required_capabilities") or ()
        ),
        required_modalities=frozenset(
            metadata.get("required_modalities") or ("text",)
        ),
        messages=tuple(messages),
        role=role,
        preferred_models=tuple(metadata.get("preferred_models") or ()),
        forbidden_models=frozenset(
            metadata.get("forbidden_models") or ()
        ),
        routing_mode=str(metadata.get("routing_mode") or "auto"),
        privacy_policy=str(
            metadata.get("privacy_policy")
            or PrivacyClass.STANDARD.value
        ),
        required_location=str(
            metadata.get("required_location") or ""
        ),
        min_context_length=int(
            metadata.get("min_context_length") or 0
        ),
        quality_target=(
            float(metadata["quality_target"])
            if metadata.get("quality_target") is not None
            else 0.5
        ),
        max_latency_ms=metadata.get("max_latency_ms"),
        max_cost_usd=metadata.get("max_cost_usd"),
        timeout_s=(
            float(metadata["model_timeout_s"])
            if metadata.get("model_timeout_s") is not None
            else 60.0
        ),
        metadata={
            "priority": metadata.get("priority", 50),
            "source": "task",
        },
    )


class GatewayAgentModelHandler:
    """Translate an Agent model boundary request into the gateway contract."""

    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def __call__(self, invocation: Any) -> ModelResponse:
        parameters = dict(getattr(invocation, "parameters", {}) or {})
        capability = str(
            getattr(invocation, "capability_id", "")
            or "model.reason"
        )
        normalized_capability = (
            capability.removeprefix("model.")
            if capability.startswith("model.")
            else capability
        )
        preferred = str(getattr(invocation, "target", "") or "")
        request = ModelRequest(
            task_id=str(
                parameters.pop("task_id", "")
                or getattr(invocation, "run_id", "")
            ),
            required_capabilities=frozenset({normalized_capability}),
            required_modalities=frozenset(
                parameters.pop("required_modalities", ("text",))
            ),
            messages=tuple(parameters.pop("messages", ())),
            attachments=tuple(parameters.pop("attachments", ())),
            role=str(parameters.pop("role", ModelRole.WORKER.value)),
            preferred_models=(preferred,) if preferred else (),
            routing_mode=(
                RoutingMode.PREFERRED
                if preferred
                else RoutingMode.AUTO
            ),
            privacy_policy=str(
                parameters.pop(
                    "privacy_policy",
                    PrivacyClass.STANDARD.value,
                )
            ),
            timeout_s=max(
                0.001,
                float(
                    getattr(invocation, "estimated_runtime_ms", 0)
                    or 60_000
                )
                / 1000,
            ),
            metadata=parameters,
        )
        return self.gateway.invoke_sync(request)


__all__ = [
    "GatewayAgentModelHandler",
    "ModelRoleBinding",
    "ModelRoleBindings",
    "model_request_from_task",
]
