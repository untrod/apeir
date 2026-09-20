from __future__ import annotations

import pytest

from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayOperation,
    GatewayRequest,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.errors import ModelProviderResponseError
from nous_runtime.model_runtime.gateway import NKIEnabledModelGateway


class ReasoningProvider:
    provider_id = "reasoning-provider"
    provider_name = "Reasoning Provider"
    model = "reasoner"
    locality = "local"

    def __init__(self) -> None:
        self.invocations: list[str] = []
        self.models: list[str] = []
        self.params: list[dict] = []

    @staticmethod
    def list_capabilities() -> list[str]:
        return ["model.reason"]

    @staticmethod
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def invoke(self, capability_id: str, **params):
        self.invocations.append(capability_id)
        self.models.append(params["model"])
        self.params.append(params)
        return {
            "ok": True,
            "content": params["messages"][0]["content"],
        }


class BalanceExhaustedProvider(ReasoningProvider):
    provider_id = "shared-account"
    provider_name = "Shared Account"
    model = "primary"
    capability_models = {"model.code": "secondary"}

    @staticmethod
    def list_capabilities() -> list[str]:
        return ["model.reason", "model.code"]

    def invoke(self, capability_id: str, **params):
        self.invocations.append(capability_id)
        self.models.append(params["model"])
        self.params.append(params)
        return {
            "ok": False,
            "error": "HTTP 402: Payment Required",
            "error_code": "NOUS_PROVIDER_BALANCE_EXHAUSTED",
            "http_status": 402,
            "retryable": False,
        }


@pytest.mark.parametrize(
    "operation",
    (
        GatewayOperation.CHAT,
        GatewayOperation.COMPLETION,
        GatewayOperation.REASONING,
        GatewayOperation.PLANNER,
        GatewayOperation.REVIEWER,
        GatewayOperation.VERIFICATION,
    ),
)
def test_reasoning_provider_supports_gateway_text_operations(operation) -> None:
    provider = ReasoningProvider()
    facade = ModelGatewayFacade(
        build_gateway_from_providers([provider], allow_direct=True)
    )
    try:
        response = facade.invoke_sync(
            GatewayRequest(
                operation=operation,
                execution=GatewayExecutionContext(task_id=operation.value),
                input="hello",
            )
        )
    finally:
        facade.gateway.close_sync_bridge()

    assert response.ok
    assert response.content == "hello"
    assert provider.invocations == ["model.reason"]
    assert provider.models == ["reasoner"]


def test_runtime_defaults_to_strict_kernel_gateway(monkeypatch) -> None:
    monkeypatch.delenv("NOUS_KERNEL_ENDPOINT", raising=False)
    gateway = build_gateway_from_providers([ReasoningProvider()])
    assert isinstance(gateway, NKIEnabledModelGateway)
    assert gateway._strict_nki is True


def test_direct_gateway_requires_explicit_compatibility_opt_in() -> None:
    gateway = build_gateway_from_providers(
        [ReasoningProvider()], allow_direct=True
    )
    assert not isinstance(gateway, NKIEnabledModelGateway)


def test_balance_failure_stops_retries_for_models_sharing_provider() -> None:
    provider = BalanceExhaustedProvider()
    gateway = build_gateway_from_providers([provider], allow_direct=True)
    try:
        with pytest.raises(ModelProviderResponseError) as caught:
            gateway.invoke_sync(
                GatewayRequest(
                    operation=GatewayOperation.CHAT,
                    execution=GatewayExecutionContext(task_id="balance"),
                    input="hello",
                ).to_model_request()
            )
    finally:
        gateway.close_sync_bridge()

    assert caught.value.http_status == 402
    assert caught.value.retryable is False
    assert provider.invocations == ["model.reason"]
    assert {
        record.health.get("category") for record in gateway.registry.list()
    } == {"budget_exceeded"}


def test_facade_exposes_structured_balance_failure() -> None:
    provider = BalanceExhaustedProvider()
    facade = ModelGatewayFacade(
        build_gateway_from_providers([provider], allow_direct=True)
    )
    try:
        response = facade.try_invoke_sync(
            GatewayRequest(
                operation=GatewayOperation.CHAT,
                execution=GatewayExecutionContext(task_id="balance-response"),
                input="hello",
            )
        )
    finally:
        facade.gateway.close_sync_bridge()

    assert not response.ok
    assert response.error["http_status"] == 402
    assert response.error["provider_error_code"] == (
        "NOUS_PROVIDER_BALANCE_EXHAUSTED"
    )
    assert response.error["retryable"] is False


def test_legacy_provider_receives_gateway_tool_definitions() -> None:
    provider = ReasoningProvider()
    facade = ModelGatewayFacade(
        build_gateway_from_providers([provider], allow_direct=True)
    )
    tool = {
        "type": "function",
        "function": {"name": "read_file", "parameters": {"type": "object"}},
    }
    try:
        response = facade.invoke_sync(
            GatewayRequest(
                operation=GatewayOperation.CHAT,
                execution=GatewayExecutionContext(task_id="tool-forwarding"),
                input="inspect the workspace",
                tools=(tool,),
                metadata={
                    "workspace_path": "workspace",
                    "agent_mode": "read_only",
                    "tool_choice": "required",
                },
            )
        )
    finally:
        facade.gateway.close_sync_bridge()

    assert response.ok
    assert provider.params[0]["tools"] == [tool]
    assert provider.params[0]["workspace"] == "workspace"
    assert provider.params[0]["agent_mode"] == "read_only"
    assert provider.params[0]["tool_choice"] == "required"
