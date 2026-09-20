# -*- coding: utf-8 -*-
"""
Shell History — persistent command history for the interactive shell.

Stores one command per line in ``.nous/history``.  Up/Down arrow
navigation is provided by Python's ``readline`` module (Unix) or falls
back to plain ``input()`` on Windows.

Usage:
    from nous_runtime.cli.history import ShellHistory

    hist = ShellHistory(workspace_path)
    hist.add("nous pack install .")
    hist.recent(5)
"""

from __future__ import annotations

from pathlib import Path as _Path


class ShellHistory:
    """Ring-buffer command history persisted to a plain-text file.

    One command per line.  The file is only written on ``add()``, never
    read back (readline handles recall).  The file serves as a durable
    record across sessions.
    """

    def __init__(self, workspace: str | _Path):
        self._path = _Path(workspace) / "history"
        self._buffer: list[str] = []

    def add(self, command: str) -> None:
        """Append a command to the history file."""
        self._buffer.append(command)
        if len(self._buffer) > 1000:
            self._buffer = self._buffer[-1000:]
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(command + "\n")
        except Exception:
            pass

    def recent(self, limit: int = 10) -> list[str]:
        """Return the most recent commands from the file."""
        if not self._path.is_file():
            return []
        lines: list[str] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                lines = [line.rstrip("\n") for line in fh if line.strip()]
        except Exception:
            return []
        return lines[-limit:]

    def clear(self) -> None:
        """Truncate the history file."""
        try:
            self._path.write_text("", encoding="utf-8")
            self._buffer.clear()
        except Exception:
            pass
