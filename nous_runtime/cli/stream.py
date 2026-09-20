# -*- coding: utf-8 -*-
"""
Streaming output and progress UI for the CLI.

Provides real-time streaming display, progress bars, and task trace
visualization for the interactive terminal and CLI commands.
"""

from __future__ import annotations

import sys
import time
import threading
from dataclasses import dataclass


# Streaming Output

class StreamWriter:
    """Writes token-by-token streaming output to the terminal."""

    def __init__(self, file=sys.stdout, prefix: str = ""):
        self.file = file
        self.prefix = prefix
        self._buffer: list[str] = []
        self._line_start = True

    def write(self, text: str) -> None:
        """Write a chunk of text."""
        if self._line_start and self.prefix:
            self.file.write(self.prefix)
            self._line_start = False
        self.file.write(text)
        self.file.flush()
        self._buffer.append(text)
        if "\n" in text:
            self._line_start = True

    def writeln(self, text: str = "") -> None:
        """Write a line of text."""
        self.write(text + "\n")
        self._line_start = True

    def clear_line(self) -> None:
        """Clear the current line."""
        self.file.write("\r\033[K")
        self.file.flush()
        self._line_start = True

    def get_buffer(self) -> str:
        return "".join(self._buffer)


# Progress Indicator

class Spinner:
    """Simple terminal spinner for long-running operations."""

    FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, message: str = ""):
        self.message = message
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_idx = 0

    def start(self, message: str = "") -> None:
        if message:
            self.message = message
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        while self._running:
            frame = self.FRAMES[self._frame_idx % len(self.FRAMES)]
            sys.stderr.write(f"\r{frame} {self.message}  ")
            sys.stderr.flush()
            self._frame_idx += 1
            time.sleep(0.08)

    def stop(self, result: str = "") -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.3)
        icon = "[OK]" if "ok" in result.lower() else "[FAIL]" if "fail" in result.lower() else ""
        sys.stderr.write(f"\r{icon} {self.message} {result}\n")
        sys.stderr.flush()


# Task Trace

@dataclass
class TraceStep:
    """A step in a task trace visualization."""
    step: int
    name: str
    status: str         # pending | running | done | failed
    detail: str = ""
    duration_ms: float = 0.0


class TraceDisplay:
    """Displays an execution trace as an indented tree."""

    def __init__(self):
        self.steps: list[TraceStep] = []
        self._start = time.time()

    def add(self, name: str, status: str = "pending", detail: str = "") -> TraceStep:
        step = TraceStep(
            step=len(self.steps) + 1,
            name=name,
            status=status,
            detail=detail,
        )
        self.steps.append(step)
        return step

    def update(self, step: TraceStep, status: str, detail: str = "") -> None:
        step.status = status
        step.detail = detail
        step.duration_ms = (time.time() - self._start) * 1000

    def render(self) -> str:
        lines = ["Execution Trace:", ""]
        for s in self.steps:
            icon = {"pending": "[ ]", "running": "[>]", "done": "[OK]", "failed": "[FAIL]"}.get(s.status, "[?]")
            time_str = f" ({s.duration_ms:.0f}ms)" if s.duration_ms > 0 else ""
            lines.append(f"  {icon} {s.name}{time_str}")
            if s.detail:
                lines.append(f"     {s.detail}")
        return "\n".join(lines)


# Status Bar

def status_bar(
    running: bool = False,
    providers: int = 0,
    caps: int = 0,
    packs: int = 0,
    jobs: int = 0,
) -> str:
    """Render a compact status bar."""
    status = "online" if running else "offline"
    return (
        f"{status} Runtime | "
        f"Providers: {providers} | "
        f"Caps: {caps} | "
        f"Packs: {packs} | "
        f"Jobs: {jobs}"
    )
