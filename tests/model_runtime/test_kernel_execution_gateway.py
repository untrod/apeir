from __future__ import annotations

import asyncio
import json

import pytest

from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import ModelRequest


class RemoteProvider:
    provider_id = "deepseek"
    provider_name = "DeepSeek"
    model = "deepseek-chat"
    endpoint = "https://api.deepseek.com/v1/chat/completions"
    credential_ref = "env:DEEPSEEK_API_KEY"
    locality = "remote"

    @staticmethod
    def list_capabilities() -> list[str]:
        return ["model.reason"]

    @staticmethod
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @staticmethod
    def invoke(capability_id: str, **params):
        raise AssertionError("the direct provider path must not be used")


class RoutedRemoteProvider(RemoteProvider):
    def __init__(self) -> None:
        self.capability_models = {"reasoning": "deepseek-reasoner"}


class MultiModelRemoteProvider(RemoteProvider):
    @staticmethod
    def list_capabilities() -> list[str]:
        return ["model.reason", "model.code"]

    def __init__(self) -> None:
        self.capability_models = {"model.code": "deepseek-coder"}


class LocalOpenAIProvider(RemoteProvider):
    provider_id = "ollama"
    endpoint = "http://127.0.0.1:11434/v1/chat/completions"
    credential_ref = ""
    authentication_required = False


class JsonObjectRemoteProvider(RemoteProvider):
    structured_output_mode = "json_object"


class FakeKernelClient:
    def __init__(
        self,
        *,
        tool_calls: list[dict] | None = None,
        metadata_tool_calls: bool = False,
    ) -> None:
        self.operation: dict | None = None
        self.closed = False
        self.tool_calls = list(tool_calls or [])
        self.metadata_tool_calls = metadata_tool_calls

    async def execute_operation(self, operation, idempotency_key=""):
        self.operation = operation
        return {
            "result": json.dumps(
                {
                    "schema_version": 1,
                    "content": "kernel response",
                    "tool_calls": [] if self.metadata_tool_calls else self.tool_calls,
                    "usage": {"total_tokens": 3},
                    "finish_reason": "stop",
                    "metadata": {
                        "backend": "openai-compatible",
                        "tool_calls": self.tool_calls
                        if self.metadata_tool_calls
                        else [],
                    },
                }
            ),
            "decision_trace": {"selected": "local-remote"},
        }

    async def close(self) -> None:
        self.closed = True


class FakeHealthClient:
    def __init__(self, response: dict) -> None:
        self.response = response

    async def health_check(self, deep=False):
        return self.response


class KernelBalanceError(Exception):
    code = "PROVIDER_ERROR"
    retryable = False

    def __str__(self) -> str:
        return (
            "[PROVIDER_ERROR] provider process error: "
            "NOUS_PROVIDER_BALANCE_EXHAUSTED: HTTP 402 Payment Required"
        )


class BalanceErrorKernelClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_operation(self, operation, idempotency_key=""):
        self.calls += 1
        raise KernelBalanceError()

    async def close(self) -> None:
        return None


def test_model_execution_uses_kernel_operation(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([RemoteProvider()])
    client = FakeKernelClient()

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    response = asyncio.run(
        gateway.invoke(
            ModelRequest(
                task_id="task",
                messages=({"role": "user", "content": "hello"},),
                metadata={
                    "max_tokens": 128,
                    "temperature": 0.2,
                    "tools": [{"type": "function", "function": {"name": "lookup"}}],
                    "tool_choice": "required",
                    "response_schema": {
                        "type": "object",
                        "properties": {"ready": {"type": "boolean"}},
                    },
                },
            )
        )
    )

    assert response.content == "kernel response"
    assert response.usage["total_tokens"] == 3
    assert response.metadata["execution_path"] == "kernel"
    assert client.closed is True
    assert client.operation is not None
    assert client.operation["backend"] == "openai-compatible"
    assert client.operation["endpoint"] == "https://api.deepseek.com/v1"
    assert client.operation["credential_env"] == "DEEPSEEK_API_KEY"
    model_input = json.loads(client.operation["input"])
    assert model_input["messages"][0]["content"] == "hello"
    assert model_input["max_output_tokens"] == 128
    assert model_input["tools"][0]["function"]["name"] == "lookup"
    assert model_input["response_format"]["type"] == "json_schema"
    assert model_input["response_format"]["json_schema"]["schema"] == {
        "type": "object",
        "properties": {"ready": {"type": "boolean"}},
    }


def test_kernel_operation_uses_the_routed_provider_model(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([RoutedRemoteProvider()])
    client = FakeKernelClient()

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    asyncio.run(
        gateway.invoke(
            ModelRequest(
                task_id="reasoning-task",
                required_capabilities=frozenset({"reasoning"}),
                preferred_models=("deepseek/deepseek-reasoner",),
                messages=({"role": "user", "content": "reason"},),
            )
        )
    )

    assert client.operation is not None
    assert client.operation["model"] == "deepseek-reasoner"


def test_kernel_operation_uses_provider_structured_output_mode(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([JsonObjectRemoteProvider()])
    client = FakeKernelClient()

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    asyncio.run(
        gateway.invoke(
            ModelRequest(
                task_id="json-object-task",
                messages=({"role": "user", "content": "return json"},),
                metadata={
                    "response_schema": {
                        "type": "object",
                        "properties": {"ready": {"type": "boolean"}},
                    }
                },
            )
        )
    )

    assert client.operation is not None
    model_input = json.loads(client.operation["input"])
    assert model_input["response_format"] == {"type": "json_object"}


def test_kernel_402_stops_same_provider_model_retries(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([MultiModelRemoteProvider()])
    client = BalanceErrorKernelClient()

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    with pytest.raises(Exception) as caught:
        asyncio.run(
            gateway.invoke(
                ModelRequest(
                    task_id="balance-task",
                    messages=({"role": "user", "content": "hello"},),
                )
            )
        )

    assert getattr(caught.value, "http_status", None) == 402
    assert getattr(caught.value, "retryable", None) is False
    assert client.calls == 1
    assert {record.health.get("category") for record in gateway.registry.list()} == {
        "budget_exceeded"
    }


def test_kernel_execution_preserves_provider_tool_calls(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"path":"workspace.json"}',
        },
    }
    gateway = build_gateway_from_providers([RemoteProvider()])
    client = FakeKernelClient(tool_calls=[tool_call])

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    response = asyncio.run(
        gateway.invoke(
            ModelRequest(
                task_id="tool-task",
                messages=({"role": "user", "content": "inspect"},),
                metadata={"tools": [{"type": "function"}]},
            )
        )
    )

    assert response.content["content"] == "kernel response"
    assert response.content["tool_calls"] == [tool_call]


def test_kernel_execution_normalizes_v1_metadata_tool_calls(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    tool_call = {
        "id": "call-v1",
        "type": "function",
        "function": {"name": "write_file", "arguments": "{}"},
    }
    gateway = build_gateway_from_providers([RemoteProvider()])
    client = FakeKernelClient(tool_calls=[tool_call], metadata_tool_calls=True)

    async def available() -> bool:
        return True

    async def new_client():
        return client

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client

    response = asyncio.run(
        gateway.invoke(
            ModelRequest(
                task_id="metadata-tool-task",
                messages=({"role": "user", "content": "write"},),
            )
        )
    )

    assert response.content["tool_calls"] == [tool_call]


def test_loopback_openai_endpoint_uses_edge_backend() -> None:
    assert (
        build_gateway_from_providers([RemoteProvider()])._kernel_backend(
            "local", "http://127.0.0.1:8080/v1"
        )
        == "edge-openai-compatible"
    )


def test_ollama_openai_endpoint_uses_edge_backend() -> None:
    gateway = build_gateway_from_providers([RemoteProvider()])
    assert (
        gateway._kernel_backend("ollama", "http://127.0.0.1:11434/v1")
        == "edge-openai-compatible"
    )
    assert gateway._kernel_backend("ollama", "http://127.0.0.1:11434") == "ollama"


def test_loopback_openai_provider_can_explicitly_disable_authentication() -> None:
    gateway = build_gateway_from_providers([LocalOpenAIProvider()])
    provider = LocalOpenAIProvider()
    assert (
        gateway._kernel_credential_reference(provider, "edge-openai-compatible") == ""
    )
    assert gateway._kernel_credential_reference(
        RemoteProvider(), "openai-compatible"
    ) == ("DEEPSEEK_API_KEY")


def test_strict_kernel_gateway_refuses_direct_fallback(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([RemoteProvider()])

    async def unavailable() -> bool:
        return False

    gateway._ensure_nki_available = unavailable

    async def invoke() -> None:
        try:
            await gateway.invoke(
                ModelRequest(
                    task_id="task",
                    messages=({"role": "user", "content": "hello"},),
                )
            )
        except Exception as error:
            assert "direct provider execution is disabled" in str(error)
        else:
            raise AssertionError("strict kernel execution unexpectedly fell back")

    asyncio.run(invoke())


def test_gateway_accepts_runtime_ready_nki_health_contract(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([RemoteProvider()])
    client = FakeHealthClient(
        {
            "state": "READY",
            "node": {"connection": "CONNECTED"},
            "contracts": {"foundation": 1},
        }
    )

    async def get_client():
        return client

    gateway._get_nki_client = get_client

    assert asyncio.run(gateway._ensure_nki_available()) is True


def test_gateway_rejects_disconnected_runtime_ready_contract(monkeypatch) -> None:
    monkeypatch.setenv("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771")
    gateway = build_gateway_from_providers([RemoteProvider()])
    client = FakeHealthClient(
        {"state": "READY", "node": {"connection": "DISCONNECTED"}}
    )

    async def get_client():
        return client

    gateway._get_nki_client = get_client

    assert asyncio.run(gateway._ensure_nki_available()) is False
