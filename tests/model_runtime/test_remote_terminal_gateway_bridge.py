from __future__ import annotations

from nous_runtime.model_runtime.facade import GatewayResponse


class _Facade:
    def __init__(self, response: GatewayResponse):
        self.response = response
        self.requests = []

    def try_invoke_sync(self, request):
        self.requests.append(request)
        return self.response


def test_remote_terminal_chat_uses_gateway_facade(monkeypatch):
    from remote_terminal import model_gateway_bridge as bridge

    facade = _Facade(
        GatewayResponse(
            request_id="req-1",
            content="hello",
            tool_calls=(
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": "{}",
                    },
                },
            ),
            provider_id="provider",
            model_id="provider/model",
            usage={"total_tokens": 4},
            latency_ms=12,
        )
    )
    monkeypatch.setattr(
        bridge,
        "_facade_for",
        lambda *_: (facade, "provider/model"),
    )

    result = bridge.invoke_message(
        [{"role": "user", "content": "hello"}],
        endpoint="https://example.invalid/v1/chat/completions",
        api_key="test-key",
        model="model",
        timeout_s=5,
        tools=[{"type": "function", "function": {"name": "lookup"}}],
    )

    assert result.message["content"] == "hello"
    assert result.message["tool_calls"][0]["id"] == "call-1"
    assert facade.requests[0].operation.value == "tool_calling"
    assert facade.requests[0].metadata == {"source": "remote_terminal"}


def test_remote_terminal_embedding_uses_gateway_facade(monkeypatch):
    from remote_terminal import model_gateway_bridge as bridge

    facade = _Facade(
        GatewayResponse(
            request_id="req-2",
            content={"embeddings": [[1, 2], [3, 4]]},
            provider_id="provider",
            model_id="provider/model",
        )
    )
    monkeypatch.setattr(
        bridge,
        "_facade_for",
        lambda *_: (facade, "provider/model"),
    )

    vectors = bridge.invoke_embeddings(
        ["one", "two"],
        endpoint="https://example.invalid/v1/embeddings",
        api_key="test-key",
        model="model",
    )

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert facade.requests[0].operation.value == "embedding"

def test_remote_terminal_structured_output_uses_gateway_facade(monkeypatch):
    from remote_terminal import model_gateway_bridge as bridge

    facade = _Facade(
        GatewayResponse(
            request_id="req-3",
            content='{"command": "Get-Date", "explanation": "show time"}',
            structured_output={
                "command": "Get-Date",
                "explanation": "show time",
            },
            provider_id="provider",
            model_id="provider/model",
        )
    )
    monkeypatch.setattr(
        bridge,
        "_facade_for",
        lambda *_: (facade, "provider/model"),
    )
    schema = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
    }

    result = bridge.invoke_message(
        [{"role": "user", "content": "show time"}],
        endpoint="https://example.invalid/v1/chat/completions",
        api_key="test-key",
        model="model",
        timeout_s=5,
        structured=True,
        response_schema=schema,
    )

    assert result.structured_output == {
        "command": "Get-Date",
        "explanation": "show time",
    }
    assert facade.requests[0].operation.value == "structured_output"
    assert facade.requests[0].response_schema == schema
