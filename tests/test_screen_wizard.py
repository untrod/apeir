from __future__ import annotations

import io
from contextlib import contextmanager

import pytest

from nous_runtime.cli import screen_wizard
from nous_runtime.cli.screen_wizard import (
    FullScreenWizard,
    WizardCancelled,
    WizardChoice,
)


@contextmanager
def _raw_mode():
    yield


def _wizard(monkeypatch, keys: list[str]) -> tuple[FullScreenWizard, io.StringIO]:
    stream = io.StringIO()
    wizard = FullScreenWizard("Nous / Test")
    wizard._terminal = stream
    iterator = iter(keys)
    monkeypatch.setattr(screen_wizard, "_raw_input_mode", _raw_mode)
    monkeypatch.setattr(screen_wizard, "_read_key", lambda: next(iterator))
    return wizard, stream


def test_select_uses_arrow_keys_and_enter(monkeypatch):
    wizard, stream = _wizard(monkeypatch, ["DOWN", "ENTER"])

    result = wizard.ask_select(
        "Provider",
        (
            WizardChoice("openai", "OpenAI"),
            WizardChoice("deepseek", "DeepSeek"),
        ),
        "openai",
    )

    assert result == "deepseek"
    assert "DeepSeek" in stream.getvalue()
    assert "Esc Back" in stream.getvalue()


def test_secret_input_is_masked(monkeypatch):
    wizard, stream = _wizard(monkeypatch, ["a", "b", "c", "ENTER"])

    result = wizard.ask_text("API key", secret=True)

    assert result == "abc"
    assert "abc" not in stream.getvalue()
    assert "***" in stream.getvalue()


def test_escape_on_first_step_cancels(monkeypatch):
    wizard, _ = _wizard(monkeypatch, ["ESC"])

    with pytest.raises(WizardCancelled):
        wizard.ask_select("Provider", (WizardChoice("one", "One"),))


def test_back_replays_previous_step_in_same_alternate_screen(monkeypatch):
    stream = io.StringIO()
    keys = iter(("ENTER", "ESC", "DOWN", "ENTER", "n", "e", "w", "ENTER"))
    monkeypatch.setattr(screen_wizard, "_raw_input_mode", _raw_mode)
    monkeypatch.setattr(screen_wizard, "_read_key", lambda: next(keys))
    monkeypatch.setattr(screen_wizard.sys, "stdout", stream)

    def callback():
        wizard = screen_wizard.active_wizard()
        assert wizard is not None
        provider = wizard.ask_select(
            "Provider",
            (
                WizardChoice("openai", "OpenAI"),
                WizardChoice("deepseek", "DeepSeek"),
            ),
        )
        name = wizard.ask_text("Name")
        return provider, name

    result = screen_wizard.run_screen_wizard(callback, title="Nous / Provider")

    assert result == ("deepseek", "new")
    output = stream.getvalue()
    assert "\x1b[?1049h" in output
    assert "\x1b[?1049l" in output


def test_plain_mode_disables_screen_wizard(monkeypatch):
    monkeypatch.setenv("NOUS_TUI", "0")
    monkeypatch.setattr(screen_wizard, "_interactive_editor_supported", lambda: True)

    assert screen_wizard.screen_wizard_supported() is False
