from __future__ import annotations

from nous_runtime.provider.adapters.anthropic import AnthropicProvider
from nous_runtime.provider.adapters.openai import OpenAIProvider


def test_openai_provider_preserves_gateway_tools_schema_and_usage():
    body = OpenAIProvider._request_body(
        "model.reason",
        "example-model",
        {
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "lookup"},
                }
            ],
            "tool_choice": "required",
            "response_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        },
    )
    parsed = OpenAIProvider._parse_response(
        "model.reason",
        {
            "model": "example-model",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 5},
        },
        "example-model",
    )

    assert body["tools"][0]["function"]["name"] == "lookup"
    assert body["tool_choice"] == "required"
    assert body["response_format"]["type"] == "json_schema"
    assert parsed["tool_calls"][0]["id"] == "call-1"
    assert parsed["usage"]["total_tokens"] == 5


def test_openai_provider_preserves_batch_embeddings():
    parsed = OpenAIProvider._parse_response(
        "model.embed",
        {
            "data": [
                {"index": 1, "embedding": [3, 4]},
                {"index": 0, "embedding": [1, 2]},
            ],
            "usage": {"total_tokens": 2},
        },
        "embedding-model",
    )

    assert parsed["embedding"] == [1, 2]
    assert parsed["embeddings"] == [[1, 2], [3, 4]]


def test_anthropic_provider_normalizes_tools_messages_and_response():
    system, messages = AnthropicProvider._normalize_messages(
        [
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "lookup",
                            "arguments": '{"q": "x"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "result",
            },
        ]
    )
    tools = AnthropicProvider._normalize_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object"},
                },
            }
        ]
    )
    parsed = AnthropicProvider._parse_response(
        {
            "model": "claude-example",
            "content": [
                {"type": "text", "text": "done"},
                {
                    "type": "tool_use",
                    "id": "call-2",
                    "name": "lookup",
                    "input": {"q": "y"},
                },
            ],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        },
        "claude-example",
    )

    assert system == "Be precise."
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["content"][0]["type"] == "tool_result"
    assert tools[0]["input_schema"] == {"type": "object"}
    assert parsed["content"] == "done"
    assert parsed["tool_calls"][0]["id"] == "call-2"
