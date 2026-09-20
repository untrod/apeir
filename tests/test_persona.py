from __future__ import annotations

import json

from nous_runtime.persona import (
    BEHAVIOR_RULES,
    RuntimeIdentity,
    build_capability_summary,
    build_system_prompt,
    get_identity,
    inject_system_message,
)
from nous_runtime.provider.adapters.anthropic import AnthropicProvider
from nous_runtime.provider.adapters.openai import OpenAIProvider
from nous_runtime.version import __version__


class _Response:
    status = 200

    def __init__(self, payload: dict | None = None):
        self.payload = payload or {"choices": [{"message": {"content": "OK"}}]}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _openai_provider(**overrides) -> OpenAIProvider:
    options = {
        "provider_id": "persona-example",
        "provider_name": "Persona Example",
        "endpoint": "https://provider.invalid/v1/chat/completions",
        "model": "persona-model",
        "credential_ref": "env:PERSONA_PROVIDER_KEY",
        "capabilities": ("model.reason", "model.code"),
    }
    options.update(overrides)
    return OpenAIProvider(**options)


def test_runtime_identity_defaults():
    identity = get_identity()
    assert identity.name == "Nous Runtime"
    assert identity.version == __version__
    assert "runtime" in identity.description.lower()
    assert RuntimeIdentity().name == "Nous Runtime"


def test_system_prompt_contains_identity_provider_and_rules():
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    assert "You are Nous Runtime" in prompt
    # Provider info is now in the "Runtime configuration" section
    assert "Runtime configuration" in prompt
    assert "DeepSeek" in prompt
    assert "deepseek-v4-flash" in prompt
    assert "not the underlying model" in prompt
    assert "not your identity" in prompt.lower()
    for rule in BEHAVIOR_RULES:
        assert rule in prompt


def test_capability_summary_derives_from_availability(monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.capability.availability.check_availability",
        lambda: {
            "available": [
                {"name": "model.reason", "provider": "deepseek"},
                {"name": "model.code", "provider": "deepseek"},
            ],
            "unavailable": [
                {"name": "model.vision", "reason": "requires vision provider"},
            ],
        },
    )
    summary = build_capability_summary()
    assert "✓ Reasoning" in summary
    assert "✓ Dedicated code-provider route" in summary
    assert "○ Vision" in summary


def test_capability_summary_falls_back_to_provider_registry(monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.capability.availability.check_availability",
        lambda: {"available": [], "unavailable": []},
    )
    monkeypatch.setattr(
        "nous_runtime.compat.provider.list_providers",
        lambda: [
            {
                "provider_id": "registry-example",
                "capabilities": ["model.reason", "model.embed"],
                "health": {"status": "ok"},
            },
            {
                "provider_id": "down-example",
                "capabilities": ["model.vision"],
                "health": {"status": "down"},
            },
        ],
    )
    summary = build_capability_summary()
    assert "✓ Reasoning" in summary
    assert "✓ Embedding" in summary
    assert "○ Vision" in summary


def test_capability_summary_without_any_source_suggests_provider_add(monkeypatch):
    monkeypatch.setattr(
        "nous_runtime.capability.availability.check_availability",
        lambda: {"available": [], "unavailable": []},
    )
    monkeypatch.setattr("nous_runtime.compat.provider.list_providers", lambda: [])
    monkeypatch.setattr(
        "nous_runtime.cli.provider_experience.read_provider_configs",
        lambda workspace=None: {},
    )
    summary = build_capability_summary()
    assert "none" in summary
    assert "nous provider add" in summary


def test_inject_system_message_prepends_once():
    injected = inject_system_message([{"role": "user", "content": "hi"}], "persona")
    assert injected[0] == {"role": "system", "content": "persona"}
    assert injected[1] == {"role": "user", "content": "hi"}

    existing = [{"role": "system", "content": "custom"}, {"role": "user", "content": "hi"}]
    assert inject_system_message(existing, "persona") == existing


def test_openai_adapter_injects_persona_system_message(monkeypatch):
    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    monkeypatch.setenv("PERSONA_PROVIDER_KEY", "persona-key")
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = _openai_provider().invoke("model.reason", prompt="hello")

    assert result["ok"] is True
    messages = captured["body"]["messages"]
    assert messages[0]["role"] == "system"
    assert "Nous Runtime" in messages[0]["content"]
    assert "persona-model" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "hello"}
    assert "persona" not in captured["body"]


def test_openai_adapter_never_double_injects(monkeypatch):
    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    monkeypatch.setenv("PERSONA_PROVIDER_KEY", "persona-key")
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    _openai_provider().invoke(
        "model.reason",
        messages=[
            {"role": "system", "content": "custom system"},
            {"role": "user", "content": "hi"},
        ],
    )

    messages = captured["body"]["messages"]
    assert [item["role"] for item in messages] == ["system", "user"]
    assert messages[0]["content"] == "custom system"


def test_openai_adapter_persona_opt_outs(monkeypatch):
    monkeypatch.setenv("PERSONA_PROVIDER_KEY", "persona-key")
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    monkeypatch.setenv("NOUS_PERSONA_DISABLE", "1")
    _openai_provider().invoke("model.reason", prompt="hello")
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]

    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    _openai_provider().invoke("model.reason", prompt="hello", persona=False)
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert "persona" not in captured["body"]


def test_openai_adapter_embedding_body_stays_clean(monkeypatch):
    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    monkeypatch.setenv("PERSONA_PROVIDER_KEY", "persona-key")
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Response({"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    _openai_provider(capabilities=("model.embed",)).invoke("model.embed", text="hello")

    assert "messages" not in captured["body"]
    assert "system" not in captured["body"]


def test_anthropic_adapter_uses_top_level_system_field(monkeypatch):
    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    monkeypatch.setenv("PERSONA_ANTHROPIC_KEY", "anthropic-key")
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Response({"content": [{"type": "text", "text": "done"}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    provider = AnthropicProvider(
        provider_id="persona-anthropic",
        model="claude-example",
        credential_ref="env:PERSONA_ANTHROPIC_KEY",
    )
    provider.invoke("model.reason", prompt="hello")

    body = captured["body"]
    assert "Nous Runtime" in body["system"]
    assert body["messages"] == [{"role": "user", "content": "hello"}]

    provider.invoke("model.reason", prompt="hello", persona=False)
    assert "system" not in captured["body"]

    provider.invoke("model.reason", prompt="hello", system="custom system")
    assert captured["body"]["system"] == "custom system"
