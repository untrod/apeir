"""Full-screen, replayable terminal wizard primitives.

The wizard uses the terminal alternate screen so intermediate steps do not
pollute shell history. It intentionally depends only on the Runtime's existing
cross-platform key reader and falls back to the plain CLI outside a TTY.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager, redirect_stdout
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Iterator, Sequence, TypeVar

from nous_runtime.cli.terminal_ui import (
    _interactive_editor_supported,
    _raw_input_mode,
    _read_key,
    _term_width,
)

T = TypeVar("T")


class WizardCancelled(RuntimeError):
    """Raised when an interactive wizard is cancelled."""


class _WizardRestart(RuntimeError):
    """Internal control flow used to replay a wizard after Back."""


@dataclass(frozen=True)
class WizardChoice:
    """One selectable wizard value."""

    value: str
    label: str
    description: str = ""


_ACTIVE_WIZARD: ContextVar[FullScreenWizard | None] = ContextVar(
    "nous_active_screen_wizard",
    default=None,
)
_NUMBERED_LINE = re.compile(r"^\s*\d+\.\s+")


def screen_wizard_supported() -> bool:
    """Return whether the current terminal should use full-screen interaction."""
    setting = os.environ.get("NOUS_TUI", "auto").strip().lower()
    if setting in {"0", "false", "off", "plain"}:
        return False
    if setting in {"1", "true", "on", "screen"}:
        return _interactive_editor_supported()
    if os.environ.get("CI"):
        return False
    return _interactive_editor_supported()


def active_wizard() -> FullScreenWizard | None:
    """Return the wizard bound to the current interactive command."""
    return _ACTIVE_WIZARD.get()


def run_screen_wizard(
    callback: Callable[[], T],
    *,
    title: str,
) -> T:
    """Run a callback in one alternate-screen session with Back replay."""
    wizard = FullScreenWizard(title)
    token = _ACTIVE_WIZARD.set(wizard)
    try:
        with wizard, redirect_stdout(wizard):
            while True:
                wizard.begin_pass()
                try:
                    return callback()
                except _WizardRestart:
                    continue
    finally:
        _ACTIVE_WIZARD.reset(token)


class FullScreenWizard:
    """A small stateful alternate-screen form renderer."""

    def __init__(self, title: str) -> None:
        self.title = title
        self._terminal = sys.stdout
        self._messages: list[str] = []
        self._answers: list[str] = []
        self._cursor = 0

    def __enter__(self) -> FullScreenWizard:
        self._terminal.write("\x1b[?1049h\x1b[2J\x1b[H\x1b[?25l")
        self._terminal.flush()
        return self

    def __exit__(self, *_: object) -> None:
        self._terminal.write("\x1b[?25h\x1b[?1049l")
        self._terminal.flush()

    def write(self, value: str) -> int:
        """Collect legacy print output for the next screen without displaying it."""
        for line in str(value).splitlines():
            clean = line.rstrip()
            if clean:
                self._messages.append(clean)
        return len(value)

    def flush(self) -> None:
        """Implement the text stream protocol used by redirect_stdout."""

    def begin_pass(self) -> None:
        """Reset replay position while retaining answers before the Back target."""
        self._cursor = 0
        self._messages.clear()

    def ask_select(
        self,
        label: str,
        choices: Sequence[WizardChoice],
        default: str = "",
    ) -> str:
        """Select one value with arrow keys and Enter."""
        cached = self._cached_answer()
        if cached is not None:
            return cached
        if not choices:
            raise ValueError("A selection step requires at least one choice")
        selected = next(
            (index for index, item in enumerate(choices) if item.value == default),
            0,
        )
        with _raw_input_mode():
            while True:
                body: list[str] = []
                for index, item in enumerate(choices):
                    marker = ">" if index == selected else " "
                    body.append(f"{marker} {item.label}")
                    if item.description:
                        body.append(f"    {item.description}")
                self._draw(label, body, "Up/Down Move  Enter Select  Esc Back  Ctrl+C Cancel")
                key = _read_key()
                if key == "UP":
                    selected = (selected - 1) % len(choices)
                elif key == "DOWN":
                    selected = (selected + 1) % len(choices)
                elif key == "ENTER":
                    return self._remember(choices[selected].value)
                elif key == "ESC":
                    self._back()
                elif key in {"CTRL_C", "CTRL_D"}:
                    raise WizardCancelled("Wizard cancelled.")

    def ask_text(
        self,
        label: str,
        default: str = "",
        *,
        secret: bool = False,
    ) -> str:
        """Read editable text without leaving previous steps on screen."""
        cached = self._cached_answer()
        if cached is not None:
            return cached
        buffer = list(default)
        cursor = len(buffer)
        with _raw_input_mode():
            while True:
                raw = "".join(buffer)
                visible = "*" * len(raw) if secret else raw
                self._draw(
                    label,
                    [f"> {visible}"],
                    "Enter Continue  Esc Back  Ctrl+C Cancel",
                )
                key = _read_key()
                if key == "ENTER":
                    return self._remember(raw)
                if key == "ESC":
                    self._back()
                if key in {"CTRL_C", "CTRL_D"}:
                    raise WizardCancelled("Wizard cancelled.")
                if key == "LEFT":
                    cursor = max(0, cursor - 1)
                elif key == "RIGHT":
                    cursor = min(len(buffer), cursor + 1)
                elif key == "HOME":
                    cursor = 0
                elif key == "END":
                    cursor = len(buffer)
                elif key == "BACKSPACE" and cursor:
                    del buffer[cursor - 1]
                    cursor -= 1
                elif len(key) == 1 and key.isprintable():
                    buffer.insert(cursor, key)
                    cursor += 1

    def ask_confirm(self, label: str, *, default: bool = True) -> bool:
        """Read a Yes/No decision as a regular selection step."""
        choices = (
            WizardChoice("yes", "Yes"),
            WizardChoice("no", "No"),
        )
        answer = self.ask_select(label, choices, "yes" if default else "no")
        return answer == "yes"

    def _cached_answer(self) -> str | None:
        if self._cursor >= len(self._answers):
            return None
        answer = self._answers[self._cursor]
        self._cursor += 1
        self._messages.clear()
        return answer

    def _remember(self, value: str) -> str:
        self._answers.append(value)
        self._cursor += 1
        self._messages.clear()
        return value

    def _back(self) -> None:
        if self._cursor == 0:
            raise WizardCancelled("Wizard cancelled.")
        target = self._cursor - 1
        del self._answers[target:]
        self._messages.clear()
        raise _WizardRestart()

    def _draw(self, label: str, body: Sequence[str], footer: str) -> None:
        width = max(40, min(_term_width(), 100))
        context = [
            line
            for line in self._messages[-8:]
            if not _NUMBERED_LINE.match(line) and set(line.strip()) != {"-"}
        ]
        lines = [
            self.title,
            "",
            *context,
            *(("",) if context else ()),
            label.strip(),
            "",
            *body,
            "",
            footer,
        ]
        clipped = [line[:width] for line in lines]
        self._terminal.write("\x1b[H\x1b[2J" + "\n".join(clipped))
        self._terminal.flush()


@contextmanager
def plain_wizard_mode() -> Iterator[None]:
    """Temporarily force legacy line-oriented prompts."""
    previous = os.environ.get("NOUS_TUI")
    os.environ["NOUS_TUI"] = "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("NOUS_TUI", None)
        else:
            os.environ["NOUS_TUI"] = previous
