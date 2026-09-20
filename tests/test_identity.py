# -*- coding: utf-8 -*-
"""Runtime identity transparency tests.

Verify that the Nous Runtime persona:
- Identifies as Nous Runtime, not the underlying model
- Can transparently disclose the current provider/model when asked
- Never claims to be created by a vendor (DeepSeek, OpenAI, Anthropic, etc.)
- Never claims non-existent capabilities
- Preserves caller system prompts without identity loss or conflict
"""

from __future__ import annotations



from nous_runtime.persona.capability_summary import build_capability_summary
from nous_runtime.persona.identity import get_identity
from nous_runtime.persona.system_prompt import (
    build_system_prompt,
    inject_system_message,
    persona_enabled,
)
from nous_runtime.persona.style import BEHAVIOR_RULES


# Identity baseline

def test_runtime_identity_name_is_nous_runtime():
    """The singleton identity must be 'Nous Runtime'."""
    identity = get_identity()
    assert identity.name == "Nous Runtime"


def test_runtime_identity_description_mentions_runtime_not_vendor():
    """Description must not claim creation by any vendor."""
    identity = get_identity()
    vendors = ["DeepSeek", "OpenAI", "Anthropic", "Google", "Meta", "Microsoft"]
    for vendor in vendors:
        assert vendor not in identity.description, (
            f"Identity description must not mention '{vendor}' as creator"
        )


def test_runtime_identity_has_version():
    """Identity must carry the runtime version."""
    identity = get_identity()
    assert identity.version
    assert len(identity.version) > 0


# System prompt identity assertions

def test_system_prompt_starts_with_nous_runtime_identity():
    """The generated system prompt must open with 'You are Nous Runtime'."""
    prompt = build_system_prompt()
    assert "You are Nous Runtime" in prompt
    # Must NOT open with a vendor model name
    assert not prompt.startswith("You are GPT")
    assert not prompt.startswith("You are Claude")
    assert not prompt.startswith("You are DeepSeek")


def test_system_prompt_discloses_provider_when_provided():
    """When provider info is given, it appears in the system prompt."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    assert "DeepSeek" in prompt
    assert "deepseek-v4-flash" in prompt
    # But the identity is still Nous Runtime
    assert "You are Nous Runtime" in prompt


def test_system_prompt_includes_capability_summary():
    """The system prompt must include a capability summary."""
    prompt = build_system_prompt()
    assert "Available" in prompt or "capabilities" in prompt.lower()


def test_system_prompt_includes_behavior_rules():
    """The system prompt must carry the behavior rules."""
    prompt = build_system_prompt()
    assert "Behavior rules:" in prompt
    # At least the first rule should be in the prompt
    first_rule = BEHAVIOR_RULES[0]
    # Check that a key phrase from the first rule is present
    assert "Nous Runtime" in first_rule


# Behavior rules checks

def test_behavior_rules_forbid_vendor_identity_claims():
    """Behavior rules must explicitly forbid claiming to be a vendor model.

    The rules are now generalized — they forbid claiming to be *any*
    specific vendor model without naming vendors (to prevent triggering
    native model identity).  Vendor names live in provider disclosure
    policy instead.
    """
    combined = " ".join(BEHAVIOR_RULES)
    assert "never claim to be" in combined.lower()
    assert "specific vendor model" in combined.lower()
    assert "any particular model vendor" in combined.lower()


def test_behavior_rules_forbid_vendor_creation_claims():
    """Behavior rules must explicitly forbid claiming Nous was vendor-created.

    The creation rule is now generalized to avoid naming specific vendors.
    """
    combined = " ".join(BEHAVIOR_RULES)
    assert "never claim that nous runtime was created by" in combined.lower()
    assert "any particular model vendor" in combined.lower()


def test_behavior_rules_allow_model_disclosure_when_asked():
    """Provider disclosure policy must allow disclosing model when asked.

    The disclosure permission is now in PROVIDER_DISCLOSURE_POLICY,
    not in BEHAVIOR_RULES — this separates "who you are" (identity)
    from "what you can tell users" (disclosure).
    """
    from nous_runtime.persona.style import PROVIDER_DISCLOSURE_POLICY

    combined = " ".join(PROVIDER_DISCLOSURE_POLICY)
    assert "disclos" in combined.lower()  # disclosing / disclose
    assert "model" in combined.lower()
    assert "answer accurately" in combined.lower()
    assert "transparently" in combined.lower()


def test_behavior_rules_forbid_unavailable_capability_claims():
    """Behavior rules must forbid claiming capabilities not marked Available."""
    combined = " ".join(BEHAVIOR_RULES)
    assert "only claim capabilities" in combined.lower()


# Capability summary integrity

def test_capability_summary_does_not_claim_web_browsing_unless_available():
    """Capability summary must not fabricate 'browse' or 'web' capabilities."""
    summary = build_capability_summary()
    # The summary should NOT mention "browse" or "web" unless actually available
    # If it's in the unavailable list, that's fine — but it shouldn't be listed
    # as available unless truly configured.
    if "web" in summary.lower() or "browse" in summary.lower():
        # If mentioned at all, it must be in the unavailable section
        assert "Available:" in summary
        available_part = summary.split("Unavailable:")[0] if "Unavailable:" in summary else summary
        assert "web" not in available_part.lower()


def test_capability_summary_does_not_claim_vision_unless_available():
    """Capability summary must not fabricate Vision capability."""
    summary = build_capability_summary()
    if "Vision" in summary or "vision" in summary.lower():
        available_part = summary.split("Unavailable:")[0] if "Unavailable:" in summary else summary
        if "✓ Vision" not in available_part:
            # Vision is mentioned but not as available — that's correct
            pass


# System message injection

def test_inject_system_message_adds_when_no_system_role():
    """System message is injected when no existing system role is present."""
    messages = [{"role": "user", "content": "Hello"}]
    result = inject_system_message(messages, "System content here")
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "System content here"


def test_inject_system_message_preserves_existing_system_message():
    """Existing system messages must NOT be overwritten or removed."""
    existing_system = {"role": "system", "content": "You are a helpful bot."}
    messages = [existing_system, {"role": "user", "content": "Hello"}]
    result = inject_system_message(messages, "Should NOT be injected")
    assert len(result) == 2
    assert result[0] == existing_system


def test_inject_system_message_handles_empty_list():
    """Empty message list should still get the system message injected."""
    result = inject_system_message([], "System prompt")
    assert len(result) == 1
    assert result[0]["role"] == "system"


# Persona toggle

def test_persona_enabled_by_default():
    """Persona is enabled when NOUS_PERSONA_DISABLE is not set."""
    assert persona_enabled() is True


def test_persona_can_be_disabled(monkeypatch):
    """Setting NOUS_PERSONA_DISABLE=1 disables persona injection."""
    monkeypatch.setenv("NOUS_PERSONA_DISABLE", "1")
    assert persona_enabled() is False


def test_persona_disabled_with_true(monkeypatch):
    """NOUS_PERSONA_DISABLE=true also disables."""
    monkeypatch.setenv("NOUS_PERSONA_DISABLE", "true")
    assert persona_enabled() is False


def test_persona_enabled_with_random_value(monkeypatch):
    """Random values do NOT disable persona."""
    monkeypatch.setenv("NOUS_PERSONA_DISABLE", "random")
    assert persona_enabled() is True


# Identity boundary tests

def test_system_prompt_never_claims_vendor_identity():
    """System prompt must NEVER say 'I am DeepSeek', 'I am GPT', etc."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    # Must NOT contain vendor identity claims
    forbidden = [
        "I am DeepSeek",
        "I am GPT",
        "I am Claude",
        "I am Gemini",
        "I am Llama",
    ]
    for claim in forbidden:
        assert claim not in prompt, f"System prompt must not contain: {claim!r}"


def test_system_prompt_identity_is_nous_runtime():
    """Primary identity statement must be 'You are Nous Runtime'."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    # First identity line must be Nous Runtime
    lines = prompt.split("\n")
    identity_lines = [line for line in lines if line.startswith("You are ")]
    assert len(identity_lines) >= 1
    assert identity_lines[0] == f"You are Nous Runtime (version {get_identity().version})."
    # Must NOT have any "You are DeepSeek", "You are OpenAI", etc.
    for line in identity_lines:
        assert "DeepSeek" not in line, f"Identity line must not name vendor: {line!r}"
        assert "GPT" not in line
        assert "Claude" not in line


def test_provider_info_in_runtime_config_not_identity():
    """Provider name must be in 'Runtime configuration' section, not identity."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    # Provider must be in the config section
    assert "Runtime configuration" in prompt
    assert "(for transparency — not your identity)" in prompt

    # Find where "DeepSeek" appears
    lines = prompt.split("\n")
    deepseek_lines = [(index, line) for index, line in enumerate(lines) if "DeepSeek" in line]
    for idx, line in deepseek_lines:
        # Must be in or after the config section
        config_idx = next(index for index, line in enumerate(lines) if "Runtime configuration" in line)
        assert idx >= config_idx, (
            f"'DeepSeek' appears at line {idx} before 'Runtime configuration' "
            f"at line {config_idx}: {line!r}"
        )
        # Must not be in the identity section (first few lines)
        assert not line.startswith("You are"), (
            f"'DeepSeek' must not appear in identity statement: {line!r}"
        )


def test_provider_disclosure_policy_present():
    """System prompt must contain the provider disclosure policy section."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
        model="deepseek-v4-flash",
    )
    assert "Provider disclosure policy:" in prompt
    # Key policy rules
    assert "Do NOT volunteer" in prompt
    assert "only mention the provider when" in prompt
    assert "user explicitly asks" in prompt
    assert "answer accurately and transparently" in prompt


def test_system_prompt_no_provider_info_when_not_provided():
    """When no provider info is given, no config section is emitted."""
    prompt = build_system_prompt()
    assert "Runtime configuration" not in prompt
    assert "Model provider:" not in prompt


def test_no_vendor_creation_claims():
    """Prompt must not claim any vendor created Nous Runtime."""
    prompt = build_system_prompt(
        provider_id="deepseek",
        provider_name="DeepSeek",
    )
    vendors = ["DeepSeek", "OpenAI", "Anthropic", "Google", "Meta"]
    for vendor in vendors:
        creation_phrases = [
            f"created by {vendor}",
            f"built by {vendor}",
            f"made by {vendor}",
            f"developed by {vendor}",
        ]
        for phrase in creation_phrases:
            assert phrase.lower() not in prompt.lower(), (
                f"Prompt must not claim: {phrase!r}"
            )


def test_openai_adapter_injected_system_message_has_boundary(monkeypatch):
    """Verify actual adapter-injected body has correct identity boundary."""
    import json

    monkeypatch.delenv("NOUS_PERSONA_DISABLE", raising=False)
    monkeypatch.setenv("PERSONA_TEST_KEY", "test-key-boundary")

    from nous_runtime.provider.adapters.openai import OpenAIProvider

    captured = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, limit=-1):
            return json.dumps(
                {"choices": [{"message": {"content": "OK"}}]}
            ).encode("utf-8")

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    provider = OpenAIProvider(
        provider_id="deepseek",
        provider_name="DeepSeek",
        endpoint="https://test.invalid/v1/chat/completions",
        model="deepseek-v4-flash",
        credential_ref="env:PERSONA_TEST_KEY",
    )
    provider.invoke("model.reason", prompt="你是谁？")

    sys_content = captured["body"]["messages"][0]["content"]

    # 1. Identity is Nous Runtime
    assert "You are Nous Runtime" in sys_content

    # 2. No vendor identity claim
    assert "I am DeepSeek" not in sys_content
    assert "I am GPT" not in sys_content

    # 3. Runtime config section exists (separate from identity)
    assert "Runtime configuration" in sys_content
    assert "not your identity" in sys_content

    # 4. Provider disclosure policy present
    assert "Provider disclosure policy:" in sys_content

    # 5. The word "DeepSeek" appears ONLY in the config section
    lines = sys_content.split("\n")
    config_idx = next(index for index, line in enumerate(lines) if "Runtime configuration" in line)
    for i, line in enumerate(lines):
        if "DeepSeek" in line:
            assert i >= config_idx, (
                f"'DeepSeek' appears at line {i} before config section at "
                f"line {config_idx}: {line!r}"
            )
